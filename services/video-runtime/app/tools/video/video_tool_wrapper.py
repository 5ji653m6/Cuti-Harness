"""
Video-generation tool wrapper - unified entry point.

Supports all video-generation models; the chain is selected in create_video_wrapper_tools(user_option):
  main model = user selection (seedance v1.0 / v1.5 / kling v3 / wan 2.5 / wan 2.6 / sora / sora-pro)
  fallback is fixed at seedance v1.0 pro fast -> wan 2.6 flash (after dedup)
  at most 3 models: 1 main + 2 fallback; Sora is never a fallback.

Flow:
  main model attempt -> retry once on the same model for retryable errors -> fall back to the fallback model -> retry once at most on the same model.
  at most 2 attempts per model.

Key parameter flow:
  start_image_url / end_image_url / duration / aspect_ratio / resolution / audio_url
    -> all passed via VideoGenerationContext through runtime.context
    -> the underlying tool reads them from runtime.context (higher priority than LLM-passed args)
    -> each tool clamps duration to its own API-supported range
    -> the wrapper only handles routing + retry + fallback, not duration / context params

The chain returns List[ToolInfo]:
  each chain entry contains a complete ToolInfo (tool object, tool_type, provider, etc.),
  at invocation it directly calls tool_info.tool.ainvoke(common_args), with no dispatch logic.

Metrics:
  written to LangSmith run metadata via VideoToolMetrics.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Annotated, Any, Dict, FrozenSet, TYPE_CHECKING

from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from app.models.image_result import VideoGenerationResult
from app.models.tool_enums import ToolType, ToolMode, ToolName
from app.models.user_options import VideoGenerationTool
from app.tools.context_schemas import VideoGenerationContext
from app.services.agent.utils.cancellation import raise_if_cancelled
from app.utils.i18n import get_i18n_message_async
from app.utils.error_classification import (
    classify_failure,
    user_facing_reason_async,
    FailureCategory,
)

if TYPE_CHECKING:
    from app.services.tool_service import ToolInfo

logger = logging.getLogger(__name__)

# ==================== Chain configuration ====================


def _get_video_chain(tool: Optional[VideoGenerationTool]) -> List["ToolInfo"]:
    """Return the video-generation attempt order by user selection (main model + fallback).

    Each user option explicitly lists the full chain, making it easy to adjust order/count later.
    Rule: a fallback must be a superset of the main model's capabilities (e.g. Kling is 480p/720p only, so fallback uses v1/w26; Sora has no 1:1, so Sora is never a fallback).
    Default fallback is seedance v1.0 -> wan 2.6 (after dedup).

    Returns List[ToolInfo], each entry containing complete tool info (tool object, tool_type, provider, etc.),
    see the get_xxx_tools() pattern in each tool module.
    """
    from app.services.tool_service import ToolInfo
    from app.models.tool_enums import ToolProvider, ToolCategory
    from app.tools.video.seedance import (
        generate_video_with_wavespeed_seedance,
        generate_video_with_wavespeed_seedance_v1_5,
    )
    from app.tools.video.seedance_2_i2v import (
        generate_video_with_wavespeed_seedance_2_i2v,
    )
    from app.tools.video.seedance_2_i2v_turbo import (
        generate_video_with_wavespeed_seedance_2_i2v_turbo,
    )
    from app.tools.video.seedance_2_fast_i2v import (
        generate_video_with_wavespeed_seedance_2_fast_i2v,
    )
    from app.tools.video.seedance_2_fast_turbo import (
        generate_video_with_wavespeed_seedance_2_fast_turbo,
    )
    from app.tools.video.seedance_2_t2v import (
        generate_video_with_wavespeed_seedance_2_t2v,
    )
    from app.tools.video.seedance_2_fast_t2v import (
        generate_video_with_wavespeed_seedance_2_fast_t2v,
    )
    from app.tools.video.seedance_2_t2v_turbo import (
        generate_video_with_wavespeed_seedance_2_t2v_turbo,
    )
    from app.tools.video.seedance_2_fast_t2v_turbo import (
        generate_video_with_wavespeed_seedance_2_fast_t2v_turbo,
    )
    from app.tools.video.kling import generate_video_with_wavespeed_kling
    from app.tools.video.happyhorse_1_0_i2v import generate_video_with_wavespeed_happyhorse_1_0_i2v
    from app.tools.video.happyhorse_1_1_i2v import generate_video_with_wavespeed_happyhorse_1_1_i2v
    from app.tools.video.wan25 import generate_video_with_wavespeed_wan25
    from app.tools.video.wan26_flash import generate_video_with_wavespeed_wan26
    from app.tools.video.sora import (
        generate_video_with_sora_2_i2v,
        generate_video_with_sora_2_pro_i2v,
    )

    def _i2v(
        tool_fn,
        tt: ToolType,
        prov: ToolProvider,
        supported_duration_seconds: FrozenSet[int],
    ) -> ToolInfo:
        # set tool.metadata so the callback can precisely obtain ToolType / Provider
        if hasattr(tool_fn, "metadata"):
            if tool_fn.metadata is None:
                tool_fn.metadata = {}
            tool_fn.metadata.update(
                tool_type=tt.value,
                provider=prov.value,
                category=ToolCategory.VIDEO_GENERATION.value,
            )
        return ToolInfo(
            tool=tool_fn,
            tool_name=tool_fn.name,
            tool_type=tt,
            provider=prov,
            category=ToolCategory.VIDEO_GENERATION,
            mode=ToolMode.I2V,
            supported_duration_seconds=supported_duration_seconds,
        )

    def _t2v(
        tool_fn,
        tt: ToolType,
        prov: ToolProvider,
        supported_duration_seconds: FrozenSet[int],
    ) -> ToolInfo:
        if hasattr(tool_fn, "metadata"):
            if tool_fn.metadata is None:
                tool_fn.metadata = {}
            tool_fn.metadata.update(
                tool_type=tt.value,
                provider=prov.value,
                category=ToolCategory.VIDEO_GENERATION.value,
            )
        return ToolInfo(
            tool=tool_fn,
            tool_name=tool_fn.name,
            tool_type=tt,
            provider=prov,
            category=ToolCategory.VIDEO_GENERATION,
            mode=ToolMode.T2V,
            supported_duration_seconds=supported_duration_seconds,
        )

    _dur_2_12 = frozenset(range(2, 13))
    _dur_3_10 = frozenset(range(3, 11))
    _dur_3_15 = frozenset(range(3, 16))
    _dur_4_15 = frozenset(range(4, 16))
    _dur_sora = frozenset({4, 8, 12})

    v1  = _i2v(generate_video_with_wavespeed_seedance,     ToolType.SEEDANCE_V1_PRO_FAST,  ToolProvider.WAVESPEED,  _dur_2_12)
    v15 = _i2v(generate_video_with_wavespeed_seedance_v1_5, ToolType.SEEDANCE_V1_5_PRO_FAST, ToolProvider.WAVESPEED, _dur_2_12)
    sd20 = _i2v(generate_video_with_wavespeed_seedance_2_i2v, ToolType.SEEDANCE_2_I2V, ToolProvider.WAVESPEED, _dur_4_15)
    sd2t = _i2v(generate_video_with_wavespeed_seedance_2_i2v_turbo, ToolType.SEEDANCE_2_I2V_TURBO, ToolProvider.WAVESPEED, _dur_4_15)
    sd2 = _i2v(generate_video_with_wavespeed_seedance_2_fast_i2v, ToolType.SEEDANCE_2_FAST_I2V, ToolProvider.WAVESPEED, _dur_4_15)
    sd2ft = _i2v(generate_video_with_wavespeed_seedance_2_fast_turbo, ToolType.SEEDANCE_2_FAST_I2V_TURBO, ToolProvider.WAVESPEED, _dur_4_15)
    kl  = _i2v(generate_video_with_wavespeed_kling,         ToolType.KLING_V3_STD,          ToolProvider.WAVESPEED,  _dur_3_15)
    hh0 = _i2v(generate_video_with_wavespeed_happyhorse_1_0_i2v, ToolType.HAPPYHORSE_1_0_I2V, ToolProvider.WAVESPEED, _dur_3_15)
    hh  = _i2v(generate_video_with_wavespeed_happyhorse_1_1_i2v, ToolType.HAPPYHORSE_1_1_I2V, ToolProvider.WAVESPEED, _dur_3_15)
    w25 = _i2v(generate_video_with_wavespeed_wan25,         ToolType.WAN_2_5_I2V,           ToolProvider.WAVESPEED,  _dur_3_10)
    w26 = _i2v(generate_video_with_wavespeed_wan26,         ToolType.WAN_2_6_FLASH_I2V,     ToolProvider.WAVESPEED,  _dur_3_15)
    s2  = _i2v(generate_video_with_sora_2_i2v,              ToolType.SORA_2,                ToolProvider.OPENAI,     _dur_sora)
    s2p = _i2v(generate_video_with_sora_2_pro_i2v,          ToolType.SORA_2_PRO,            ToolProvider.OPENAI,     _dur_sora)

    if tool == VideoGenerationTool.POLLO_SEEDANCE:
        return [v1, w26]
    elif tool == VideoGenerationTool.SEEDANCE_V1_5:
        return [v15, v1, w26]
    elif tool == VideoGenerationTool.SEEDANCE_2_I2V:
        return [sd20, sd2t, sd2, sd2ft, v1, w26]
    elif tool == VideoGenerationTool.SEEDANCE_2_I2V_TURBO:
        return [sd2t, sd2ft, sd20, sd2, v1, w26]
    elif tool == VideoGenerationTool.SEEDANCE_2_FAST_I2V:
        return [sd2, sd2ft, sd2t, sd20, v1, w26]
    elif tool == VideoGenerationTool.SEEDANCE_2_FAST_I2V_TURBO:
        return [sd2ft, sd2t, sd2, sd20, v1, w26]
    elif tool == VideoGenerationTool.KLING_V3_STD:
        return [kl, v1, w26]
    elif tool == VideoGenerationTool.HAPPYHORSE_1_0_I2V:
        return [hh0, v1, w26]
    elif tool == VideoGenerationTool.HAPPYHORSE_1_1_I2V:
        return [hh, v1, w26]
    elif tool == VideoGenerationTool.WAN_2_5:
        return [w25, v1, w26]
    elif tool == VideoGenerationTool.WAN_2_6:
        return [w26, v1]
    elif tool == VideoGenerationTool.OPENAI_SORA:
        return [s2, v1, w26]
    elif tool == VideoGenerationTool.OPENAI_SORA_PRO:
        return [s2p, v1, w26]
    else:
        # AUTO / None / unknown -> prefer seedance v1.0
        return [v1, w26]


def _get_ref_t2v_video_chain(tool: Optional[VideoGenerationTool]) -> List["ToolInfo"]:
    """Seedance 2 reference-to-video: T2V main chain + v1/w26 I2V fallback."""
    from app.services.tool_service import ToolInfo
    from app.models.tool_enums import ToolProvider, ToolCategory
    from app.tools.video.seedance import generate_video_with_wavespeed_seedance
    from app.tools.video.seedance_2_t2v import generate_video_with_wavespeed_seedance_2_t2v
    from app.tools.video.seedance_2_t2v_turbo import generate_video_with_wavespeed_seedance_2_t2v_turbo
    from app.tools.video.seedance_2_fast_t2v import generate_video_with_wavespeed_seedance_2_fast_t2v
    from app.tools.video.seedance_2_fast_t2v_turbo import generate_video_with_wavespeed_seedance_2_fast_t2v_turbo
    from app.tools.video.wan26_flash import generate_video_with_wavespeed_wan26

    _dur_4_15 = frozenset(range(4, 16))
    _dur_2_12 = frozenset(range(2, 13))
    _dur_3_15 = frozenset(range(3, 16))

    def _t2v(tool_fn, tt, prov, durs):
        if hasattr(tool_fn, "metadata"):
            if tool_fn.metadata is None:
                tool_fn.metadata = {}
            tool_fn.metadata.update(
                tool_type=tt.value,
                provider=prov.value,
                category=ToolCategory.VIDEO_GENERATION.value,
            )
        return ToolInfo(
            tool=tool_fn,
            tool_name=tool_fn.name,
            tool_type=tt,
            provider=prov,
            category=ToolCategory.VIDEO_GENERATION,
            mode=ToolMode.T2V,
            supported_duration_seconds=durs,
        )

    def _i2v(tool_fn, tt, prov, durs):
        if hasattr(tool_fn, "metadata"):
            if tool_fn.metadata is None:
                tool_fn.metadata = {}
            tool_fn.metadata.update(
                tool_type=tt.value,
                provider=prov.value,
                category=ToolCategory.VIDEO_GENERATION.value,
            )
        return ToolInfo(
            tool=tool_fn,
            tool_name=tool_fn.name,
            tool_type=tt,
            provider=prov,
            category=ToolCategory.VIDEO_GENERATION,
            mode=ToolMode.I2V,
            supported_duration_seconds=durs,
        )

    sd2t2v = _t2v(generate_video_with_wavespeed_seedance_2_t2v, ToolType.SEEDANCE_2_T2V, ToolProvider.WAVESPEED, _dur_4_15)
    sd2t2vt = _t2v(generate_video_with_wavespeed_seedance_2_t2v_turbo, ToolType.SEEDANCE_2_T2V_TURBO, ToolProvider.WAVESPEED, _dur_4_15)
    sd2ft2v = _t2v(generate_video_with_wavespeed_seedance_2_fast_t2v, ToolType.SEEDANCE_2_FAST_T2V, ToolProvider.WAVESPEED, _dur_4_15)
    sd2ft2vt = _t2v(generate_video_with_wavespeed_seedance_2_fast_t2v_turbo, ToolType.SEEDANCE_2_FAST_T2V_TURBO, ToolProvider.WAVESPEED, _dur_4_15)
    v1 = _i2v(generate_video_with_wavespeed_seedance, ToolType.SEEDANCE_V1_PRO_FAST, ToolProvider.WAVESPEED, _dur_2_12)
    w26 = _i2v(generate_video_with_wavespeed_wan26, ToolType.WAN_2_6_FLASH_I2V, ToolProvider.WAVESPEED, _dur_3_15)

    if tool == VideoGenerationTool.SEEDANCE_2_I2V:
        return [sd2t2v, sd2t2vt, sd2ft2v, sd2ft2vt, v1, w26]
    if tool == VideoGenerationTool.SEEDANCE_2_I2V_TURBO:
        return [sd2t2vt, sd2ft2vt, sd2t2v, sd2ft2v, v1, w26]
    if tool == VideoGenerationTool.SEEDANCE_2_FAST_I2V:
        return [sd2ft2v, sd2ft2vt, sd2t2v, sd2t2vt, v1, w26]
    if tool == VideoGenerationTool.SEEDANCE_2_FAST_I2V_TURBO:
        return [sd2ft2vt, sd2t2vt, sd2ft2v, sd2t2v, v1, w26]
    return [sd2ft2v, sd2ft2vt, sd2t2v, sd2t2vt, v1, w26]


# ==================== Metrics ====================


@dataclass
class VideoToolMetrics:
    """Wrapper execution stats, written to LangSmith run metadata."""

    total_attempts: int = 0
    per_model_attempts: Dict[str, int] = field(default_factory=dict)
    success: bool = False
    final_model: Optional[str] = None
    failure_reasons: List[str] = field(default_factory=list)
    best_effort_selected: bool = False

    def record_attempt(
        self,
        model: str,
        success: bool,
        failure_reason: Optional[str] = None,
    ):
        self.total_attempts += 1
        self.per_model_attempts[model] = self.per_model_attempts.get(model, 0) + 1
        if failure_reason:
            self.failure_reasons.append(f"{model}:{failure_reason}")
        if success:
            self.success = True
            self.final_model = model

    def to_metadata(self) -> dict:
        return {
            "video_wrapper_metrics": {
                "total_attempts": self.total_attempts,
                "per_model_attempts": dict(self.per_model_attempts),
                "success": self.success,
                "final_model": self.final_model,
                "failure_reasons": list(self.failure_reasons),
                "best_effort_selected": self.best_effort_selected,
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """For writing into VideoGenerationResult and persistence."""
        return {
            "total_attempts": self.total_attempts,
            "per_model_attempts": dict(self.per_model_attempts),
            "success": self.success,
            "final_model": self.final_model,
            "failure_reasons": list(self.failure_reasons),
            "best_effort_selected": self.best_effort_selected,
        }

    def flush_to_langsmith(self):
        """Write metrics into the current LangSmith run's metadata and patch to the API (works sync/async)."""
        try:
            from langsmith import get_current_run_tree

            run = get_current_run_tree()
            if run:
                run.add_metadata(self.to_metadata())
                run.patch()
        except Exception:
            pass


# ==================== Tool helper functions ====================


def _is_retryable_error(result: VideoGenerationResult) -> bool:
    """Decide whether a transient API-level error is retryable."""
    if result.success:
        return False
    error_msg = (result.raw_error_msg or result.error_msg or result.message or "").lower()
    retryable_keywords = [
        "504",
        "deadline_exceeded",
        "rate limit",
        "too many requests",
        "quota",
        "capacity",
        "temporarily unavailable",
        "service unavailable",
        "timeout",
        "暂时不可用",
        "使用量",
        "限流",
    ]
    return any(kw in error_msg for kw in retryable_keywords)


def _inject_video_metrics(
    result: VideoGenerationResult,
    metrics: VideoToolMetrics,
    duration_sec: float,
    accumulated_tool_cost: float,
) -> VideoGenerationResult:
    """Write metrics and elapsed time/cost into result for upstream persistence. accumulated_tool_cost is the cumulative cost across fallback attempts, consistent with the credits charged."""
    data = result.model_dump()
    data["video_tool_metrics"] = metrics.to_dict()
    data["tool_duration_sec"] = round(duration_sec, 3)
    data["tool_cost"] = accumulated_tool_cost or None
    out = VideoGenerationResult(**data)
    logger.info(
        "[video_wrapper] _inject_video_metrics 写入: tool_duration_sec=%s, tool_cost=%s",
        out.tool_duration_sec,
        out.tool_cost,
    )
    return out


async def _maybe_add_switch_info(
    result: VideoGenerationResult,
    actual_tool_type: ToolType,
    requested_model: ToolType,
    lang: Optional[str] = None,
) -> VideoGenerationResult:
    """If a model downgrade/switch happened, add the model info; text is localized by runtime.context.language."""
    if actual_tool_type != requested_model:
        suffix = await get_i18n_message_async(
            "video_model_switched.fallback_suffix",
            default=" (A fallback model was used.)",
            lang=lang,
        )
        return result.model_copy(
            update={
                "model": actual_tool_type.value,
                "message": (result.message or "") + suffix,
            }
        )
    return result


# ==================== Underlying calls ====================


async def _invoke_t2v_video_tool(
    prompt: str,
    duration: int,
    tool_info: "ToolInfo",
    runtime: ToolRuntime[VideoGenerationContext],
) -> VideoGenerationResult:
    """T2V (incl. reference-to-video): reference_images are brought in via runtime.context."""
    common_args = {
        "t2v_prompt": prompt,
        "duration": duration,
        "runtime": runtime,
    }
    return await tool_info.tool.ainvoke(common_args)


def _generation_anchor_url(
    runtime: Optional[ToolRuntime[VideoGenerationContext]],
    start_image_url: str,
) -> str:
    """Reference-to-video fallback uses the first reference as its start frame."""
    if runtime and runtime.context:
        refs = runtime.context.reference_images or []
        if refs and refs[0]:
            return refs[0]
        if runtime.context.start_image_url:
            return runtime.context.start_image_url
    return start_image_url or ""


async def _invoke_video_tool(
    prompt: str,
    start_image_url: str,
    duration: int,
    tool_info: "ToolInfo",
    runtime: ToolRuntime[VideoGenerationContext],
) -> VideoGenerationResult:
    """Call the underlying video-generation tool directly via ToolInfo.

    All I2V video tools share the same common_args (i2v_prompt / start_image_url / duration / runtime),
    so there is no need to dispatch by tool_type -- call tool_info.tool.ainvoke(common_args) directly.

    Key design:
      - duration is clamped/mapped to its own supported range inside each tool.
      - end_image_url / aspect_ratio / resolution / audio_url
        all brought in via runtime.context, and each underlying tool reads from context itself.
      - model-specific params (Kling cfg_scale / Wan audio_url, etc.) have defaults in each tool.
    """
    common_args = {
        "i2v_prompt": prompt,
        "start_image_url": start_image_url,
        "duration": duration,
        "runtime": runtime,
    }
    return await tool_info.tool.ainvoke(common_args)


# ==================== Main loop ====================


async def _run_video_loop(
    prompt: str,
    start_image_url: str,
    duration: int,
    runtime: ToolRuntime[VideoGenerationContext],
    chain: List["ToolInfo"],
) -> VideoGenerationResult:
    """Video-generation fallback chain - at most 2 attempts per model."""
    from app.services.agent.video.agent_video_constants import (
        VIDEO_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS,
    )

    MAX_TOTAL_ATTEMPTS = VIDEO_WRAPPER_MAX_TOTAL_GENERATION_ATTEMPTS
    anchor_url = _generation_anchor_url(runtime, start_image_url)

    requested_model = chain[0].tool_type
    _lang = getattr(runtime.context, "language", None) if runtime and runtime.context else None
    metrics = VideoToolMetrics()
    last_error_result: Optional[VideoGenerationResult] = None
    best_effort_result: Optional[VideoGenerationResult] = None
    loop_start = time.perf_counter()
    accumulated_tool_cost = 0.0
    total_attempts = 0

    for info in chain:
        for attempt_num in (1, 2):
            if total_attempts >= MAX_TOTAL_ATTEMPTS:
                logger.info("🛑 [Video] 已达最大尝试次数 (%d)，停止", MAX_TOTAL_ATTEMPTS)
                break
            # cooperative cancellation: before each (retry) attempt, check whether the user has cancelled, to avoid still running/retrying video generation after cancellation
            await raise_if_cancelled()
            total_attempts += 1
            if attempt_num == 1:
                logger.info("🔄 [Video] 尝试模型: %s (duration=%ds)", info.tool_type.value, duration)
            else:
                logger.info("🔄 [Video] 重试: %s", info.tool_type.value)

            attempt_start = time.perf_counter()
            result = (
                await _invoke_t2v_video_tool(prompt, duration, info, runtime)
                if info.mode == ToolMode.T2V
                else await _invoke_video_tool(
                    prompt, anchor_url or start_image_url, duration, info, runtime
                )
            )
            attempt_duration = time.perf_counter() - attempt_start
            accumulated_tool_cost += float(getattr(result, "billing_cost", None) or 0.0)

            if result.success and result.video_url:
                metrics.record_attempt(info.tool_type.value, True)
                metrics.flush_to_langsmith()
                out = await _maybe_add_switch_info(
                    result, info.tool_type, requested_model, lang=_lang,
                )
                return _inject_video_metrics(
                    out, metrics, time.perf_counter() - loop_start,
                    accumulated_tool_cost,
                )
            elif result.success:
                metrics.record_attempt(info.tool_type.value, True)
                metrics.flush_to_langsmith()
                out = await _maybe_add_switch_info(result, info.tool_type, requested_model, lang=_lang)
                return _inject_video_metrics(out, metrics, time.perf_counter() - loop_start, accumulated_tool_cost)

            error_reason = "api_error"
            if result.raw_error_msg or result.error_msg or result.message:
                raw = result.raw_error_msg or result.error_msg or result.message or ""
                error_reason = raw[:80]
            metrics.record_attempt(info.tool_type.value, False, failure_reason=error_reason)
            last_error_result = result if getattr(result, "model", None) else result.model_copy(
                update={"model": info.tool_type.value}
            )
            if result.video_url:
                best_effort_result = result

            if _is_retryable_error(result) and attempt_num == 1:
                continue
            break
        if total_attempts >= MAX_TOTAL_ATTEMPTS:
            break

    if best_effort_result and best_effort_result.video_url:
        metrics.best_effort_selected = True
        metrics.flush_to_langsmith()
        out = await _maybe_add_switch_info(best_effort_result, chain[0].tool_type, requested_model, lang=_lang)
        return _inject_video_metrics(out, metrics, time.perf_counter() - loop_start, accumulated_tool_cost)

    metrics.flush_to_langsmith()
    logger.error("❌ [Video] 所有模型均失败")
    _raw_for_category = (
        (last_error_result.raw_error_msg or last_error_result.error_msg)
        if last_error_result else None
    )
    _category = classify_failure(_raw_for_category)
    if _category in (FailureCategory.SERVICE_UNAVAILABLE, FailureCategory.UNKNOWN):
        err_msg = await get_i18n_message_async(
            "video_model_switched.all_unavailable",
            default="All video generation models are temporarily unavailable. Please try again later.",
            lang=_lang,
        )
    else:
        err_msg = await user_facing_reason_async(category=_category, lang=_lang)
    failed = last_error_result or VideoGenerationResult(success=False, error_msg=err_msg)
    failed = failed.model_copy(update={"failure_category": _category.value})
    return _inject_video_metrics(failed, metrics, time.perf_counter() - loop_start, accumulated_tool_cost)


# ==================== Wrapper Tool (I2V) ====================


class VideoWrapperI2VInput(BaseModel):
    """Input schema for video generation wrapper I2V.

    The wrapper schema is a superset of all underlying tool schemas:
      - i2v_prompt / start_image_url / duration: common to all I2V tools
      - end_image_url: supported by some tools (e.g. Seedance), written into runtime.context for the underlying tool to read
      - runtime: provider runtime injection
    """

    i2v_prompt: str = Field(
        description="Motion description prompt for image-to-video generation. "
        "Describe actions, changes, and camera movements in detail. "
        "Must be under 800 characters."
    )
    start_image_url: str = Field(
        description="Starting image URL that serves as the first frame of the video. "
        "Supports HTTPS URLs or local file paths."
    )
    duration: int = Field(
        default=5,
        ge=3,
        le=10,
        description="Video duration in seconds. Supported range: 3-10 seconds (unified across all models).",
    )
    end_image_url: Optional[str] = Field(
        default=None,
        description="Optional ending image URL for the last frame of the video. "
        "Only supported by certain models (e.g., Seedance). "
        "If provided and not already in context, it will be written to runtime.context for the underlying tool.",
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


def _make_i2v_tool(chain: List["ToolInfo"]):
    """Create the I2V tool from the selected chain."""
    assert chain, "video chain must be non-empty"
    chain_desc = " → ".join(info.tool_type.value for info in chain)

    @tool(ToolName.VIDEO_WRAPPER_I2V, args_schema=VideoWrapperI2VInput, response_format="content_and_artifact")
    async def generate_video_with_fallback_i2v(
        i2v_prompt: str,
        start_image_url: str,
        runtime: ToolRuntime[VideoGenerationContext],
        duration: int = 5,
        end_image_url: Optional[str] = None,
    ) -> tuple[str, VideoGenerationResult]:
        f"""Professional video generation tool with automatic fallback - I2V image-to-video.
        Chain: {chain_desc}. Retry once per model on retryable errors, then fallback to next model.
        Context parameters (aspect_ratio, resolution) are read from runtime.context.
        end_image_url is written to runtime.context if provided and not already set.
        """
        # write end_image_url into context for the underlying tool (e.g. Seedance) to read
        if end_image_url and runtime and runtime.context and not runtime.context.end_image_url:
            runtime.context.end_image_url = end_image_url

        result = await _run_video_loop(
            i2v_prompt, start_image_url, duration, runtime, chain
        )
        # content=result's JSON (for the model to see), artifact=the full result object for downstream use without parsing
        return (result.model_dump_json(), result)

    return generate_video_with_fallback_i2v


class VideoWrapperRefT2VInput(BaseModel):
    """Input schema for Seedance 2 reference-to-video wrapper (T2V + reference_images)."""

    i2v_prompt: str = Field(
        description="Cinematic motion prompt (passed as T2V prompt). "
        "Describe actions, camera movement, and mood. Must be under 800 characters."
    )
    duration: int = Field(
        default=5,
        ge=4,
        le=15,
        description="Video duration in seconds. SD2 T2V supports 4-15 seconds.",
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


def _make_ref_t2v_tool(chain: List["ToolInfo"]):
    """Seedance 2 reference-to-video: T2V + reference_images (delivered via runtime.context)."""
    assert chain, "ref t2v chain must be non-empty"
    chain_desc = " → ".join(info.tool_type.value for info in chain)

    @tool(ToolName.VIDEO_WRAPPER_REF_T2V, args_schema=VideoWrapperRefT2VInput, response_format="content_and_artifact")
    async def generate_video_with_fallback_ref_t2v(
        i2v_prompt: str,
        runtime: ToolRuntime[VideoGenerationContext],
        duration: int = 5,
    ) -> tuple[str, VideoGenerationResult]:
        f"""Seedance 2 reference-to-video with automatic fallback.
        Chain: {chain_desc}. reference_images are read from runtime.context (keyframes + character refs).
        """
        anchor = _generation_anchor_url(runtime, "")
        result = await _run_video_loop(
            i2v_prompt, anchor, duration, runtime, chain
        )
        return (result.model_dump_json(), result)

    return generate_video_with_fallback_ref_t2v


# ==================== Tool creation functions ====================


def create_video_wrapper_tools(
    mode: Optional[ToolMode] = None,
    user_option: Optional[Any] = None,
    resolution: Optional[Any] = None,
    has_end_image: Optional[bool] = None,
) -> List["ToolInfo"]:
    """Create the video-generation tool wrapper with fallback.

    Supports all video-generation models. The chain order is decided by user_option.video_generation_tool:
      main model + fallback (seedance v1.0 -> wan 2.6, at most 3 after dedup).

    The chain returns List[ToolInfo], each entry containing complete tool info (tool object, tool_type, provider),
    for uniform invocation in tool_service.
    """
    from app.models.tool_enums import ToolCategory
    from app.services.tool_service import ToolInfo
    from app.models.user_options import should_use_reference_to_video

    video_tool = user_option.video_generation_tool if user_option else None
    use_ref_t2v = bool(user_option and should_use_reference_to_video(user_option))

    if use_ref_t2v:
        chain = _get_ref_t2v_video_chain(video_tool)
        primary = chain[0]
        tool_obj = _make_ref_t2v_tool(chain)
        tool_mode = ToolMode.T2V
    else:
        chain = _get_video_chain(video_tool)
        primary = chain[0]
        tool_obj = _make_i2v_tool(chain)
        tool_mode = ToolMode.I2V

    tool_info = ToolInfo(
        tool=tool_obj,
        tool_name=tool_obj.name,
        tool_type=primary.tool_type,
        provider=primary.provider,
        category=ToolCategory.VIDEO_GENERATION,
        mode=tool_mode,
        supported_duration_seconds=primary.supported_duration_seconds,
    )

    # add metadata
    if hasattr(tool_info.tool, "metadata"):
        if tool_info.tool.metadata is None:
            tool_info.tool.metadata = {}
        tool_info.tool.metadata.update(
            tool_type=primary.tool_type.value,
            provider=primary.provider.value,
            category=ToolCategory.VIDEO_GENERATION.value,
        )

    logger.info(
        "🎬 [VideoWrapper] 创建完成: ref_t2v=%s, chain=%s, provider=%s",
        use_ref_t2v,
        [info.tool_type.value for info in chain],
        primary.provider.value,
    )
    return [tool_info]


# module-level default tools (for direct import or testing, using the default chain)
generate_video_with_fallback_i2v = _make_i2v_tool(_get_video_chain(None))
