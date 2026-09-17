"""
Text-to-speech tool wrapper - unified entry point.

Flow:
  call Minimax Speech -> synthesize once with a fixed speed=1.0
  -> record the deviation between measured duration and target_duration (metrics only, no speed retry)

Key parameter flow:
  target_duration / detected_language / default_voice_id
    -> all passed via SpeechGenerationContext through runtime.context
    -> target_duration is only a reference for the LLM to control word count; the output uses the measured TTS duration

Metrics:
  written to LangSmith run metadata via SpeechToolMetrics.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Annotated, Any, Dict, TYPE_CHECKING

from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from app.models.image_result import (
    SpeechGenerationResult,
    VoiceID,
    Emotion,
    SpeechEmotionLiteral,
    infer_voice_gender,
    default_voice_for_language_and_gender,
)
from app.models.tool_enums import ToolType, ToolName
from app.tools.context_schemas import SpeechGenerationContext
from app.services.agent.utils.cancellation import raise_if_cancelled

if TYPE_CHECKING:
    from app.services.tool_service import ToolInfo

logger = logging.getLogger(__name__)

DURATION_TOLERANCE_SEC = 0.5
FIXED_SPEECH_SPEED = 1.0


# ==================== Metrics（LangSmith metadata） ====================


@dataclass
class SpeechToolMetrics:
    """Wrapper execution stats, written to LangSmith run metadata; to_dict writes into result for persistence."""

    total_attempts: int = 0
    success: bool = False
    target_duration: Optional[float] = None
    final_duration: Optional[float] = None
    duration_delta: Optional[float] = None
    duration_mismatch: bool = False
    speed_adjustments: List[float] = field(default_factory=list)
    attempt_durations: List[float] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)

    def record_attempt(
        self,
        success: bool,
        duration: Optional[float] = None,
        speed: Optional[float] = None,
        failure_reason: Optional[str] = None,
    ):
        self.total_attempts += 1
        if duration is not None:
            self.attempt_durations.append(duration)
        if speed is not None and len(self.speed_adjustments) == 0:
            self.speed_adjustments.append(speed)
        elif speed is not None:
            self.speed_adjustments.append(speed)
        if failure_reason:
            self.failure_reasons.append(failure_reason)
        if success:
            self.success = True
            self.final_duration = duration
            if self.target_duration is not None and duration is not None:
                self.duration_delta = round(duration - self.target_duration, 3)
                self.duration_mismatch = abs(self.duration_delta) > DURATION_TOLERANCE_SEC

    def to_metadata(self) -> dict:
        return {
            "speech_wrapper_metrics": {
                "total_attempts": self.total_attempts,
                "success": self.success,
                "target_duration": self.target_duration,
                "final_duration": self.final_duration,
                "duration_delta": self.duration_delta,
                "duration_mismatch": self.duration_mismatch,
                "speed_adjustments": list(self.speed_adjustments),
                "attempt_durations": list(self.attempt_durations),
                "failure_reasons": list(self.failure_reasons),
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_attempts": self.total_attempts,
            "success": self.success,
            "target_duration": self.target_duration,
            "final_duration": self.final_duration,
            "duration_delta": self.duration_delta,
            "duration_mismatch": self.duration_mismatch,
            "speed_adjustments": list(self.speed_adjustments),
            "attempt_durations": list(self.attempt_durations),
            "failure_reasons": list(self.failure_reasons),
        }

    def flush_to_langsmith(self):
        try:
            from langsmith import get_current_run_tree

            run = get_current_run_tree()
            if run:
                run.add_metadata(self.to_metadata())
                run.patch()
        except Exception as e:
            logger.debug("speech_wrapper metrics flush skipped: %s", e)


# ==================== Helper functions ====================


def _duration_within_tolerance(actual: float, target: float) -> bool:
    return abs(actual - target) <= DURATION_TOLERANCE_SEC


def _duration_mismatch_hint(actual_duration: float, target_duration: float) -> str:
    delta = actual_duration - target_duration
    direction = "缩短" if delta > 0 else "加长"
    return (
        f"⚠️ 实测 {actual_duration:.2f}s，参考 {target_duration:.2f}s（Δ{delta:+.2f}s）。"
        f"请{direction}文案后以 speed=1.0 再次调用本工具（最多再试 1 次）。"
    )


def _resolve_voice_id(voice_id: str, context: Optional[SpeechGenerationContext]) -> str:
    """Voice resolution: code-provided default_voice_id / speaker_gender take priority, preventing the LLM from picking a wrong-gender voice."""
    lang = (context.detected_language or "").lower() if context else ""
    gender = context.speaker_gender if context else None

    if context and context.default_voice_id:
        return context.default_voice_id

    if gender in ("f", "m"):
        voice_gender = infer_voice_gender(voice_id)
        if voice_gender == gender:
            return voice_id
        corrected = default_voice_for_language_and_gender(lang, gender)
        if voice_id != corrected:
            logger.info(
                "🔊 voice 性别校正: requested=%r speaker_gender=%s -> %s",
                voice_id,
                gender,
                corrected,
            )
        return corrected

    if voice_id != VoiceID.WISE_WOMAN.value:
        return voice_id
    if lang.startswith("zh"):
        return VoiceID.CHINESE_NEWS_ANCHOR.value
    return VoiceID.ENGLISH_EXPRESSIVE_NARRATOR.value


def _inject_speech_metrics(
    result: SpeechGenerationResult,
    metrics: SpeechToolMetrics,
    duration_sec: float,
    accumulated_tool_cost: float,
) -> SpeechGenerationResult:
    data = result.model_dump()
    data["speech_tool_metrics"] = metrics.to_dict()
    data["tool_duration_sec"] = round(duration_sec, 3)
    data["tool_cost"] = accumulated_tool_cost or None
    out = SpeechGenerationResult(**data)
    logger.info(
        "[speech_wrapper] metrics: tool_duration_sec=%s, tool_cost=%s, duration_delta=%s",
        out.tool_duration_sec,
        out.tool_cost,
        metrics.duration_delta,
    )
    return out


async def _invoke_minimax_speech(
    text: str,
    voice_id: str,
    emotion: str,
    speed: float,
    pitch: int,
    volume: float,
) -> SpeechGenerationResult:
    from app.tools.narration.minimax import generate_speech_with_wavespeed

    return await generate_speech_with_wavespeed.ainvoke(
        {
            "text": text,
            "voice_id": voice_id,
            "emotion": emotion,
            "speed": speed,
            "pitch": pitch,
            "volume": volume,
        }
    )


async def _run_speech_loop(
    text: str,
    voice_id: str,
    emotion: str,
    speed: float,
    pitch: int,
    volume: float,
    runtime: ToolRuntime[SpeechGenerationContext],
) -> SpeechGenerationResult:
    context = runtime.context if runtime else None
    target_duration = context.target_duration if context else None
    shot_label = context.shot_number if context and context.shot_number is not None else "?"
    resolved_voice = _resolve_voice_id(voice_id, context)

    metrics = SpeechToolMetrics(target_duration=target_duration)
    loop_start = time.perf_counter()
    accumulated_tool_cost = 0.0
    speech_speed = FIXED_SPEECH_SPEED

    await raise_if_cancelled()
    logger.info(
        "🔊 [Speech] 镜头%s 开始合成 target=%ss(参考) voice=%s speed=%.2f",
        shot_label,
        target_duration,
        resolved_voice,
        speech_speed,
    )

    result = await _invoke_minimax_speech(
        text, resolved_voice, emotion, speech_speed, pitch, volume
    )
    accumulated_tool_cost += float(getattr(result, "billing_cost", None) or 0.0)

    if result.success and result.audio_url:
        actual_duration = float(result.duration or 0.0)
        metrics.record_attempt(True, duration=actual_duration, speed=speech_speed)
        if target_duration and target_duration > 0 and actual_duration > 0:
            if not _duration_within_tolerance(actual_duration, target_duration):
                metrics.duration_mismatch = True
                metrics.duration_delta = round(actual_duration - target_duration, 3)
                logger.info(
                    "⏱️ [Speech] 镜头%s TTS 实测 %.2fs vs 分镜参考 %.2fs (Δ%+.2fs)，不调 speed，后续以 TTS 时长为准",
                    shot_label,
                    actual_duration,
                    target_duration,
                    actual_duration - target_duration,
                )
                hint = _duration_mismatch_hint(actual_duration, target_duration)
                data = result.model_dump()
                data["message"] = hint
                result = SpeechGenerationResult(**data)
        metrics.flush_to_langsmith()
        return _inject_speech_metrics(
            result, metrics, time.perf_counter() - loop_start, accumulated_tool_cost
        )

    error_reason = (result.message or "api_error")[:80]
    metrics.record_attempt(False, speed=speech_speed, failure_reason=error_reason)
    metrics.flush_to_langsmith()
    return _inject_speech_metrics(
        result, metrics, time.perf_counter() - loop_start, accumulated_tool_cost
    )


# ==================== Wrapper Tool ====================


class SpeechWrapperInput(BaseModel):
    """Input schema for speech generation wrapper."""

    text: str = Field(description="要转换为语音的文本内容（支持中英文混合）")
    voice_id: str = Field(
        default=VoiceID.WISE_WOMAN.value,
        description=(
            "语音角色 ID；须与讲解者性别一致。"
            "中文男声: Chinese (Mandarin)_Male_Announcer / Gentleman / Reliable_Executive；"
            "中文女声: Chinese (Mandarin)_News_Anchor / Mature_Woman / Radio_Host。"
            "若 runtime 已注入 default_voice_id，以程序值为准。"
        ),
    )
    emotion: SpeechEmotionLiteral = Field(
        default=Emotion.NEUTRAL.value,
        description="语音情感，仅限枚举 7 值之一；平静/专业播报用 neutral",
    )
    speed: float = Field(default=1.0, description="固定为 1.0（正常语速），请勿修改")
    pitch: int = Field(default=0, ge=-12, le=12, description="音调调节")
    volume: float = Field(default=1.0, ge=0.1, le=2.0, description="音量大小")
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


@tool(ToolName.SPEECH_WRAPPER, args_schema=SpeechWrapperInput, response_format="content_and_artifact")
async def generate_speech_with_fallback(
    text: str,
    runtime: ToolRuntime[SpeechGenerationContext],
    voice_id: str = VoiceID.WISE_WOMAN.value,
    emotion: SpeechEmotionLiteral = Emotion.NEUTRAL.value,
    speed: float = 1.0,
    pitch: int = 0,
    volume: float = 1.0,
) -> tuple[str, SpeechGenerationResult]:
    """Professional Minimax Speech 2.5 text-to-speech tool (fixed speed=1.0, single synthesis).

    target_duration is only a reference for the LLM to control word count; the measured duration is written into the result, and later video/output uses the TTS duration (no speed adjustment).
    detected_language / default_voice_id / speaker_gender are read from runtime.context;
    voice_id must match the narrator's gender; the code corrects a wrong-gender voice.
    emotion is limited to: happy, sad, angry, fearful, disgusted, surprised, neutral.
    """
    result = await _run_speech_loop(
        text, voice_id, emotion, speed, pitch, volume, runtime
    )
    return (result.model_dump_json(), result)


# ==================== Tool creation functions ====================


def create_speech_wrapper_tools() -> List["ToolInfo"]:
    """Create the text-to-speech wrapper tool with duration validation."""
    from app.models.tool_enums import ToolProvider, ToolCategory
    from app.services.tool_service import ToolInfo

    tool_type = ToolType.MINIMAX_SPEECH_2_5
    provider = ToolProvider.WAVESPEED

    if hasattr(generate_speech_with_fallback, "metadata"):
        if generate_speech_with_fallback.metadata is None:
            generate_speech_with_fallback.metadata = {}
        generate_speech_with_fallback.metadata.update(
            tool_type=tool_type.value,
            provider=provider.value,
            category=ToolCategory.SPEECH_SYNTHESIS.value,
        )

    tool_info = ToolInfo(
        tool=generate_speech_with_fallback,
        tool_name=generate_speech_with_fallback.name,
        tool_type=tool_type,
        provider=provider,
        category=ToolCategory.SPEECH_SYNTHESIS,
        mode=None,
    )
    return [tool_info]
