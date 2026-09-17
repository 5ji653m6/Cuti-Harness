"""Music Smart Clip analysis service.

Goal: when the actual duration of a Suno-generated song deviates significantly from the user's target,
infer the best cut points + a recommended selection from the existing transcription sections / vocal_presence.

Key design (same as archive/pre-harness-dev):
1. Only invoked on the lyrics_provided / auto_lyrics_song path (pure BGM does no smart clipping; it is handled by the backend mix loop).
2. Input: transcription (already containing sections / segments / vocal_presence / global_bpm) + target_duration.
3. Gemini + ``music-smart-clip-director`` first (transcription JSON only; audio is not re-uploaded).
4. On AI failure, fall back to the sections heuristic; if sections are unavailable, fall back to a centered window.
5. The result is written into ``music_generations.additional_data.smart_clip``, carried to the frontend by ``gate_after_music_node`` in the
   ``interrupt()`` payload; the user confirms in the after_music pause UI -> the trim is applied on resume.
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from ....utils.time_format import format_sec_to_mmss

logger = logging.getLogger(__name__)


# ==================== Pydantic schemas ====================


class SmartCutKind(str, Enum):
    """Candidate cut-point type."""
    PHRASE_END = "phrase_end"            # phrase end
    BAR_LINE = "bar_line"                # bar line (inferred from BPM)
    LOW_ENERGY = "low_energy"            # low-energy trough (good fade-out anchor)
    NATURAL_FADEOUT = "natural_fadeout"  # natural song fade-out / section close
    SECTION_BOUNDARY = "section_boundary"  # Verse/Chorus/Outro boundary


class SmartCutCandidate(BaseModel):
    """Candidate cut point."""
    time_sec: float = Field(description="候选裁切点（秒，相对音频起点）")
    kind: SmartCutKind = Field(description="候选点类型")
    vocal_safe: bool = Field(description="VAD：该点附近 ±300ms 是否无人声")
    energy_score: float = Field(ge=0.0, le=1.0, description="能量分（0=最静，1=爆音）；越低越适合 fade-out")
    score: float = Field(ge=0.0, le=1.0, description="综合推荐分；越高越优")
    rationale: str = Field(description="为何选此点（音乐学角度，简短）")


class SmartClipSelection(BaseModel):
    """Recommended selection: start ~ end is the time range of the trimmed segment."""
    start_sec: float = Field(ge=0.0, description="起点（秒）")
    end_sec: float = Field(description="终点（秒）")
    fade_in_sec: float = Field(ge=0.0, le=8.0, description="淡入时长（秒）")
    fade_out_sec: float = Field(ge=0.0, le=8.0, description="淡出时长（秒）")
    target_duration_sec: float = Field(description="用户目标时长")
    actual_duration_sec: float = Field(description="选区实际时长 = end_sec - start_sec")
    duration_error_sec: float = Field(description="actual - target 的绝对差")
    reasoning: str = Field(description="为何选这一段（章节命中、人声完整、能量起伏等）")


class SmartClipAnalysis(BaseModel):
    """Smart-clip analysis output."""
    audio_duration_sec: float
    target_duration_sec: float
    candidates: List[SmartCutCandidate] = Field(
        default_factory=list,
        description="候选裁切点（按 score 降序）",
    )
    recommended: SmartClipSelection
    fallback_used: bool = Field(default=False, description="AI 失败启用启发式")
    method: str = Field(description="ai_reuse_transcription / heuristic_section / heuristic_center / passthrough")


# ==================== Main entry ====================


_PASSTHROUGH_GAP_SEC = 1.0  # when the audio is already shorter than target+gap, use the whole thing


async def analyze_music_smart_clip(
    audio_url: str,
    target_duration_sec: float,
    transcription: Any,
    *,
    audio_duration_sec: Optional[float] = None,
) -> SmartClipAnalysis:
    """Reuse the existing transcription's sections / vocal_presence for cut-candidate analysis.

    Args:
        audio_url: music URL (only for logging / persistence reference; no longer re-uploaded to Gemini)
        target_duration_sec: the user's desired target duration (seconds)
        transcription: the ``AudioTranscription`` returned by ``transcribe_audio_with_gemini``,
            which **must** contain ``sections`` (song structure) and the ``vocal_presence`` of ``segments``.
        audio_duration_sec: optional; when not passed, try to derive it from transcription / media service.

    Returns:
        ``SmartClipAnalysis``, containing the candidate list + recommended selection.
    """
    # -- 1. fall back to obtaining audio_duration_sec
    if audio_duration_sec is None or audio_duration_sec <= 0.0:
        td = getattr(transcription, "duration", None)
        if isinstance(td, (int, float)) and td > 0:
            audio_duration_sec = float(td)
    if audio_duration_sec is None or audio_duration_sec <= 0.0:
        try:
            from app.utils.media_service_client import audio_info
            info = await audio_info(audio_url)
            audio_duration_sec = float(info.get("duration") or 0.0)
        except Exception as e:
            logger.warning("smart_clip: audio_info 失败 %s，回退使用 transcription.segments 末尾", e)
            audio_duration_sec = _max_segment_end(transcription)

    if not audio_duration_sec or audio_duration_sec <= 0.0:
        raise ValueError("smart_clip: 无法确定 audio_duration_sec")

    # -- 2. already shorter than target: pass through
    if audio_duration_sec <= float(target_duration_sec) + _PASSTHROUGH_GAP_SEC:
        return _passthrough_analysis(audio_duration_sec, target_duration_sec)

    # -- 3. Gemini director first; heuristic fallback on failure
    try:
        result = await _ai_analyze_with_transcription(
            audio_duration_sec, target_duration_sec, transcription,
        )
    except Exception as e:
        logger.warning("smart_clip AI failed, falling back to heuristic: %s", e)
        try:
            result = _heuristic_section_based_analysis(
                audio_duration_sec, target_duration_sec, transcription,
            )
        except Exception as heuristic_exc:
            logger.warning("smart_clip sections heuristic failed, falling back to center: %s", heuristic_exc)
            result = _heuristic_center_analysis(audio_duration_sec, target_duration_sec)
    return _normalize_analysis(result, audio_duration_sec, target_duration_sec)


async def _ai_analyze_with_transcription(
    audio_duration_sec: float,
    target_duration_sec: float,
    transcription: Any,
) -> SmartClipAnalysis:
    """Text-only Gemini call: transcription facts + music-smart-clip-director."""
    from google import genai
    from google.genai import types

    from app.chat.v2.media_prompts import media_system_instruction
    from app.models.tool_enums import ToolProvider, ToolType
    from app.services.account.account_router import get_account_router

    extra = getattr(transcription, "additional_data", None) or {}
    if not isinstance(extra, dict):
        extra = {}
    facts = {
        "audio_duration_sec": round(float(audio_duration_sec), 2),
        "target_duration_sec": round(float(target_duration_sec), 2),
        "global_bpm": extra.get("global_bpm") or getattr(transcription, "global_bpm", None),
        "global_emotion": extra.get("global_emotion") or getattr(transcription, "global_emotion", None),
        "genre": extra.get("genre") or getattr(transcription, "genre", None),
        "sections": _build_sections_view(transcription),
        "segments": _build_segments_view(transcription),
    }
    prompt = (
        "Recommend a clip window from these transcription facts. "
        "Return JSON matching the schema exactly.\n"
        + json.dumps(facts, ensure_ascii=False)
    )
    system_instruction = media_system_instruction("music-smart-clip-director")

    async def _request(api_key: str):
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=120_000),
        )
        return await client.aio.models.generate_content(
            model=ToolType.GEMINI_2_5_FLASH.value,
            contents=types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            ),
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=SmartClipAnalysis,
            ),
        )

    router = await get_account_router()
    response = await router.route_tool_request(
        provider=ToolProvider.GOOGLE,
        tool_type=ToolType.GEMINI_2_5_FLASH,
        request_func=_request,
    )
    raw_result = getattr(response, "parsed", None)
    if raw_result is None and getattr(response, "text", None):
        raw_result = json.loads(response.text)
    if raw_result is None:
        raise RuntimeError("smart_clip Gemini returned no parsed result")
    result = (
        raw_result
        if isinstance(raw_result, SmartClipAnalysis)
        else SmartClipAnalysis.model_validate(raw_result)
    )
    return result.model_copy(update={
        "method": "ai_reuse_transcription",
        "fallback_used": False,
        "audio_duration_sec": float(audio_duration_sec),
        "target_duration_sec": float(target_duration_sec),
    })


# ==================== Heuristic fallback ====================


def _passthrough_analysis(audio_duration_sec: float, target_duration_sec: float) -> SmartClipAnalysis:
    """Audio is already shorter than target: no cut, use the whole thing."""
    return SmartClipAnalysis(
        audio_duration_sec=float(audio_duration_sec),
        target_duration_sec=float(target_duration_sec),
        candidates=[],
        recommended=SmartClipSelection(
            start_sec=0.0,
            end_sec=float(audio_duration_sec),
            fade_in_sec=0.0,
            fade_out_sec=0.0,
            target_duration_sec=float(target_duration_sec),
            actual_duration_sec=float(audio_duration_sec),
            duration_error_sec=abs(float(audio_duration_sec) - float(target_duration_sec)),
            reasoning="音频已短于（或接近）目标时长，无需裁切。",
        ),
        fallback_used=False,
        method="passthrough",
    )


def _heuristic_section_based_analysis(
    audio_duration_sec: float,
    target_duration_sec: float,
    transcription: Any,
) -> SmartClipAnalysis:
    """Without AI, find a contiguous section combination close to target based on sections."""
    sections = _build_sections_view(transcription)
    if not sections:
        return _heuristic_center_analysis(audio_duration_sec, target_duration_sec)

    # candidates: each section's start / end is a potential cut point
    candidates: List[SmartCutCandidate] = []
    for s in sections:
        for ts_str in (s.get("end_time"),):
            try:
                t = float(ts_str)
            except (TypeError, ValueError):
                continue
            if t <= 0.0 or t >= audio_duration_sec - 0.1:
                continue
            candidates.append(SmartCutCandidate(
                time_sec=t,
                kind=SmartCutKind.SECTION_BOUNDARY,
                vocal_safe=True,
                energy_score=0.3,
                score=0.7,
                rationale=f"section {s.get('section_type')} 结束",
            ))

    # recommended selection: accumulate sections from 0, find the accumulation point with the smallest |actual - target|
    target = float(target_duration_sec)
    best_end = None
    best_err = None
    cum = 0.0
    for s in sections:
        try:
            sec_dur = max(0.0, float(s.get("end_time")) - float(s.get("start_time")))
        except (TypeError, ValueError):
            continue
        cum += sec_dur
        err = abs(cum - target)
        if best_err is None or err < best_err:
            best_err = err
            best_end = cum
    if best_end is None or best_end <= 0.0:
        return _heuristic_center_analysis(audio_duration_sec, target_duration_sec)

    end_sec = min(best_end, audio_duration_sec)
    duration = end_sec
    fade_in = 0.5 if duration >= 4.0 else 0.0
    fade_out = min(1.5, max(0.5, duration * 0.05))
    return SmartClipAnalysis(
        audio_duration_sec=float(audio_duration_sec),
        target_duration_sec=target,
        candidates=sorted(candidates, key=lambda c: c.score, reverse=True)[:12],
        recommended=SmartClipSelection(
            start_sec=0.0,
            end_sec=float(end_sec),
            fade_in_sec=float(fade_in),
            fade_out_sec=float(fade_out),
            target_duration_sec=target,
            actual_duration_sec=float(duration),
            duration_error_sec=float(abs(duration - target)),
            reasoning="按曲式段落组合时长最接近目标的节点裁切。",
        ),
        fallback_used=True,
        method="heuristic_section",
    )


def _heuristic_center_analysis(
    audio_duration_sec: float,
    target_duration_sec: float,
) -> SmartClipAnalysis:
    """Ultimate fallback: take a centered target-length window."""
    target = float(target_duration_sec)
    half = target / 2.0
    mid = float(audio_duration_sec) / 2.0
    start = max(0.0, mid - half)
    end = min(float(audio_duration_sec), start + target)
    duration = end - start
    return SmartClipAnalysis(
        audio_duration_sec=float(audio_duration_sec),
        target_duration_sec=target,
        candidates=[],
        recommended=SmartClipSelection(
            start_sec=float(start),
            end_sec=float(end),
            fade_in_sec=1.0,
            fade_out_sec=2.0,
            target_duration_sec=target,
            actual_duration_sec=float(duration),
            duration_error_sec=float(abs(duration - target)),
            reasoning="居中截取目标时长。",
        ),
        fallback_used=True,
        method="heuristic_center",
    )


# ==================== helpers ====================


def _max_segment_end(transcription: Any) -> float:
    segs = getattr(transcription, "segments", None) or []
    end_max = 0.0
    for s in segs:
        try:
            e = float(getattr(s, "end", 0.0))
        except (TypeError, ValueError):
            continue
        if e > end_max:
            end_max = e
    return end_max


def _extra_get(transcription: Any, key: str) -> Any:
    extra = getattr(transcription, "additional_data", None) or {}
    if isinstance(extra, dict):
        return extra.get(key)
    return None


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _build_sections_view(transcription: Any) -> List[dict]:
    """Generate a pure-string prompt view from the transcription's ``additional_data["sections"]`` or its own ``sections`` field
    (avoiding serialization of complex objects like datetime / pydantic)."""
    raw = _extra_get(transcription, "sections")
    if not raw:
        raw = getattr(transcription, "sections", None) or []
    out: List[dict] = []
    if not isinstance(raw, list):
        return out
    for s in raw:
        if not isinstance(s, dict):
            continue
        try:
            st = float(s.get("start_time") or 0.0)
            et = float(s.get("end_time") or 0.0)
        except (TypeError, ValueError):
            continue
        if et <= st:
            continue
        out.append({
            "section_type": _safe_str(s.get("section_type")),
            "start_time": f"{st:.2f}",
            "end_time": f"{et:.2f}",
            "start_display": format_sec_to_mmss(st),
            "end_display": format_sec_to_mmss(et),
            "section_emotion": _safe_str(s.get("section_emotion")),
            "musical_features": _safe_str(s.get("musical_features")),
        })
    return out


def _build_segments_view(transcription: Any) -> List[dict]:
    """Generate a simplified view of segments: start, end, vocal_presence."""
    segs = getattr(transcription, "segments", None) or []
    out: List[dict] = []
    for seg in segs:
        try:
            st = float(getattr(seg, "start", 0.0))
            et = float(getattr(seg, "end", 0.0))
        except (TypeError, ValueError):
            continue
        if et <= st:
            continue
        vp = getattr(seg, "vocal_presence", None)
        if vp is None:
            vp = bool((getattr(seg, "text", "") or "").strip())
        out.append({
            "start": f"{st:.2f}",
            "end": f"{et:.2f}",
            "start_display": format_sec_to_mmss(st),
            "end_display": format_sec_to_mmss(et),
            "vocal_presence": bool(vp),
        })
    return out


def _normalize_analysis(
    analysis: SmartClipAnalysis,
    audio_duration_sec: float,
    target_duration_sec: float,
) -> SmartClipAnalysis:
    """Clamp / consistency-fix the AI output: times do not exceed audio duration, recompute duration_error."""
    rec = analysis.recommended
    start = max(0.0, min(float(rec.start_sec), float(audio_duration_sec)))
    end = max(start + 0.1, min(float(rec.end_sec), float(audio_duration_sec)))
    duration = end - start
    fi = max(0.0, min(float(rec.fade_in_sec or 0.0), 8.0))
    fo = max(0.0, min(float(rec.fade_out_sec or 0.0), 8.0))
    rec_fixed = rec.model_copy(update={
        "start_sec": start,
        "end_sec": end,
        "fade_in_sec": fi,
        "fade_out_sec": fo,
        "actual_duration_sec": duration,
        "target_duration_sec": float(target_duration_sec),
        "duration_error_sec": abs(duration - float(target_duration_sec)),
    })
    # candidates: clamp time_sec to [0, audio_duration]
    new_cands: List[SmartCutCandidate] = []
    for c in analysis.candidates or []:
        t = max(0.0, min(float(c.time_sec), float(audio_duration_sec)))
        new_cands.append(c.model_copy(update={"time_sec": t}))
    return analysis.model_copy(update={
        "audio_duration_sec": float(audio_duration_sec),
        "target_duration_sec": float(target_duration_sec),
        "recommended": rec_fixed,
        "candidates": new_cands,
    })
