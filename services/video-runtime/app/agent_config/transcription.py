"""
Per-method transcription-engine config (orthogonal to user_options.VideoGenerationTool).

Keys: DefaultValues.TRANSCRIPTION_METHOD values such as hybrid / gemini.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.models.tool_enums import AudioSegmentGranularity, DefaultValues


@dataclass(frozen=True)
class TranscriptionEngineProfile:
    """Backend knobs for a single transcription engine."""

    granularity: AudioSegmentGranularity
    # reserved: enable_fill_gaps, merge_short_empty_threshold_sec, etc.


TRANSCRIPTION_ENGINE_PROFILES: Dict[str, TranscriptionEngineProfile] = {
    "gemini": TranscriptionEngineProfile(
        granularity=AudioSegmentGranularity.SENTENCE,
    ),
    "hybrid": TranscriptionEngineProfile(
        granularity=AudioSegmentGranularity.SENTENCE,
    ),
}

# compatible with the historical dict shape (tool_enums / doc references)
TRANSCRIPTION_METHOD_CONFIG: Dict[str, Dict[str, Any]] = {
    name: {"granularity": prof.granularity.value}
    for name, prof in TRANSCRIPTION_ENGINE_PROFILES.items()
}


def get_transcription_profile(method: str) -> TranscriptionEngineProfile:
    """Get the config by transcription-method name; unknown methods fall back to DefaultValues."""
    key = (method or "").strip().lower()
    prof = TRANSCRIPTION_ENGINE_PROFILES.get(key)
    if prof is not None:
        return prof
    return TranscriptionEngineProfile(
        granularity=AudioSegmentGranularity.from_value(DefaultValues.AUDIO_SEGMENT_GRANULARITY),
    )


def get_transcription_method_config(method: str) -> Dict[str, Any]:
    """Get the config dict by method name; unknown methods return {} (consistent with the old tool_enums behavior)."""
    key = (method or "").strip().lower()
    if key in TRANSCRIPTION_METHOD_CONFIG:
        return dict(TRANSCRIPTION_METHOD_CONFIG[key])
    return {}


def get_audio_segment_granularity_for_method(method: str) -> AudioSegmentGranularity:
    """Single entry point: resolve granularity by method."""
    cfg = get_transcription_method_config(method)
    raw = cfg.get("granularity")
    if raw is None:
        raw = DefaultValues.AUDIO_SEGMENT_GRANULARITY
    return AudioSegmentGranularity.from_value(raw)
