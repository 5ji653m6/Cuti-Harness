"""Shape v1 listen output for the coordinator.

Not a planner: window, look-lock, recut, and H3 prompts stay with the LLM.
"""
from __future__ import annotations

import re
from typing import Any
from types import SimpleNamespace


MAX_CLIP_SEC = 15.0
_STAGE_TAG = re.compile(r"\[[^\]]*\]")


def _num(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            return float(item[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        dumped = item.model_dump()
        if isinstance(dumped, dict):
            return dumped
    return {
        key: getattr(item, key, None)
        for key in ("start", "end", "start_sec", "end_sec", "text", "emotion",
                    "vocal_presence", "tempo", "vocal_gender")
    }


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def lyrics_in_window(lines: list[dict[str, Any]], start: float, duration: float) -> list[str]:
    """Timed transcript lines that overlap an already-chosen clip — facts, not a pick."""
    end = start + duration
    lyrics: list[str] = []
    for item in lines:
        if item["end"] <= start or item["start"] >= end:
            continue
        text = " ".join(_STAGE_TAG.sub(" ", str(item.get("text") or "")).split())
        if text:
            lyrics.append(text)
    return lyrics


def normalize_vocal_lines(transcription: Any) -> list[dict[str, Any]]:
    if transcription is None:
        return []
    if isinstance(transcription, list):
        items = transcription
    elif isinstance(transcription, dict):
        items = transcription.get("segments") or transcription.get("lyrics") or []
    else:
        items = _attr(transcription, "segments") or []
    lines: list[dict[str, Any]] = []
    for item in items:
        raw = item if isinstance(item, dict) else _as_dict(item)
        text = str(raw.get("text") or "").strip()
        start = _num(raw, "start", "start_sec")
        end = _num(raw, "end", "end_sec")
        if not text or start is None or end is None or end <= start:
            continue
        lines.append({"start": start, "end": end, "text": text})
    lines.sort(key=lambda item: item["start"])
    return lines


def parse_cut_segments(
    raw: Any,
    *,
    max_segment_sec: float = MAX_CLIP_SEC,
) -> list[dict[str, Any]] | None:
    """Director-supplied generate clips. None means the host may use the window itself."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("segments must be a list of {start_sec, duration}")
    if not raw:
        return []
    max_seg = float(max_segment_sec)
    if max_seg <= 0:
        raise ValueError("max_segment_sec must be > 0")
    planned: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("each segment must be an object with start_sec and duration")
        start = _num(item, "start_sec", "start")
        duration = _num(item, "duration_sec", "duration")
        if start is None or duration is None:
            raise ValueError("each segment needs start_sec and duration")
        if start < 0:
            raise ValueError("segment start_sec must be >= 0")
        if duration <= 0:
            raise ValueError("segment duration must be > 0")
        if duration > max_seg + 1e-6:
            raise ValueError(
                f"segment duration must be <= {max_seg:g}s (generate clip cap)"
            )
        start_r = round(start, 3)
        dur_r = round(duration, 3)
        planned.append({
            "index": index,
            "start_sec": start_r,
            "duration_sec": dur_r,
            "end_sec": round(start_r + dur_r, 3),
        })
    return planned


def reference_clips_for_cut(
    start_sec: float,
    duration_sec: float,
    *,
    segments: Any = None,
    max_segment_sec: float = MAX_CLIP_SEC,
) -> list[dict[str, Any]]:
    """Trim list for generate. Long windows must come with director segments."""
    planned = parse_cut_segments(segments, max_segment_sec=max_segment_sec)
    if planned is not None:
        return planned
    window = float(duration_sec)
    origin = float(start_sec)
    max_seg = float(max_segment_sec)
    if window <= 0 or max_seg <= 0:
        raise ValueError("duration and max_segment_sec must be > 0")
    if origin < 0:
        raise ValueError("start_sec must be >= 0")
    if window > max_seg + 1e-6:
        raise ValueError(
            "media.audio_cut duration over 15s requires segments"
        )
    start_r = round(origin, 3)
    dur_r = round(window, 3)
    return [{
        "index": 0,
        "start_sec": start_r,
        "duration_sec": dur_r,
        "end_sec": round(start_r + dur_r, 3),
    }]


def as_smart_clip_transcription(raw: Any) -> Any:
    """v1 smart_clip reads .segments / .additional_data; dicts from tests need a wrap."""
    if raw is None or not isinstance(raw, dict):
        return raw
    extra = dict(raw.get("additional_data") or {})
    if raw.get("sections") is not None and "sections" not in extra:
        extra["sections"] = raw["sections"]
    segments = []
    for item in raw.get("segments") or []:
        if not isinstance(item, dict):
            segments.append(item)
            continue
        start = _num(item, "start", "start_sec")
        end = _num(item, "end", "end_sec")
        if start is None or end is None:
            continue
        segments.append(SimpleNamespace(
            start=start,
            end=end,
            text=str(item.get("text") or ""),
            vocal_presence=item.get("vocal_presence"),
            emotion=item.get("emotion"),
            tempo=item.get("tempo"),
        ))
    return SimpleNamespace(
        segments=segments,
        additional_data=extra,
        global_bpm=raw.get("global_bpm") or extra.get("global_bpm"),
        global_emotion=raw.get("global_emotion") or extra.get("global_emotion"),
        genre=raw.get("genre") or extra.get("genre"),
        song_name=raw.get("song_name") or extra.get("song_name"),
        suggested_global_theme=raw.get("suggested_global_theme"),
        suggested_color_palette=raw.get("suggested_color_palette"),
        duration=raw.get("duration") or raw.get("audio_duration_sec"),
        text=raw.get("text") or "",
        language=raw.get("language") or "",
        is_instrumental=bool(raw.get("is_instrumental", False)),
        audio_url=raw.get("audio_url") or "",
    )


def transcription_public_view(
    transcription: Any,
    *,
    audio_url: str,
    audio_duration_sec: float,
) -> dict[str, Any]:
    """Coordinator-facing listen result; drop v1 alignment blobs."""
    extra = _attr(transcription, "additional_data") or {}
    if not isinstance(extra, dict):
        extra = {}
    sections = []
    for item in extra.get("sections") or _attr(transcription, "sections") or []:
        if not isinstance(item, dict):
            continue
        start = _num(item, "start_time", "start_sec", "start")
        end = _num(item, "end_time", "end_sec", "end")
        if start is None or end is None or end <= start:
            continue
        sections.append({
            "section_type": item.get("section_type") or item.get("type") or "",
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "emotion": item.get("section_emotion") or item.get("emotion"),
            "musical_features": item.get("musical_features"),
            "suggested_visual_intensity": item.get("suggested_visual_intensity"),
            "suggested_visual_theme": item.get("suggested_visual_theme"),
        })
    segments = []
    for item in _attr(transcription, "segments") or []:
        raw = item if isinstance(item, dict) else _as_dict(item)
        start = _num(raw, "start", "start_sec")
        end = _num(raw, "end", "end_sec")
        if start is None or end is None or end <= start:
            continue
        row = {
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "text": str(raw.get("text") or "").strip(),
            "emotion": raw.get("emotion"),
            "vocal_presence": raw.get("vocal_presence"),
            "tempo": raw.get("tempo"),
        }
        gender = raw.get("vocal_gender")
        if gender in ("f", "m"):
            row["vocal_gender"] = gender
        segments.append(row)
    return {
        "audio_url": audio_url,
        "audio_duration_sec": round(float(audio_duration_sec), 3),
        "song_name": _attr(transcription, "song_name") or extra.get("song_name"),
        "global_bpm": _attr(transcription, "global_bpm") or extra.get("global_bpm"),
        "genre": _attr(transcription, "genre") or extra.get("genre"),
        "global_emotion": (
            _attr(transcription, "global_emotion") or extra.get("global_emotion")
        ),
        "suggested_global_theme": (
            _attr(transcription, "suggested_global_theme")
            or extra.get("suggested_global_theme")
        ),
        "suggested_color_palette": (
            _attr(transcription, "suggested_color_palette")
            or extra.get("suggested_color_palette")
        ),
        "is_instrumental": bool(_attr(transcription, "is_instrumental", False)),
        "language": _attr(transcription, "language") or extra.get("language") or "",
        "text": _attr(transcription, "text") or "",
        "sections": sections,
        "segments": segments,
    }


def smart_clip_public_view(analysis: Any) -> dict[str, Any]:
    if analysis is None:
        return {}
    if isinstance(analysis, dict):
        return {
            "method": analysis.get("method"),
            "fallback_used": bool(analysis.get("fallback_used")),
            "recommended": analysis.get("recommended") or {},
        }
    recommended = getattr(analysis, "recommended", None)
    rec = recommended.model_dump() if hasattr(recommended, "model_dump") else recommended
    return {
        "method": getattr(analysis, "method", None),
        "fallback_used": bool(getattr(analysis, "fallback_used", False)),
        "recommended": rec,
    }
