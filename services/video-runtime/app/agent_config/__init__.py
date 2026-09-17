"""
MV pipeline backend strategy - stable public entry point.

See agent_config/README.md
"""
from app.agent_config.duration import (
    get_audio_driven_duration_values,
    get_audio_driven_split_threshold,
    get_video_driven_duration_values,
    get_video_driven_split_threshold,
)
from app.agent_config.transcription import (
    TRANSCRIPTION_ENGINE_PROFILES,
    TRANSCRIPTION_METHOD_CONFIG,
    TranscriptionEngineProfile,
    get_audio_segment_granularity_for_method,
    get_transcription_method_config,
    get_transcription_profile,
)
from app.agent_config.video_tool_profiles import (
    VIDEO_TOOL_PLANNING_PROFILES,
    VideoToolPlanningProfile,
    get_video_tool_planning_profile,
    resolve_audio_driven_scene_split_threshold,
)
from app.models.tool_enums import DefaultValues

__all__ = [
    "DefaultValues",
    "TranscriptionEngineProfile",
    "TRANSCRIPTION_ENGINE_PROFILES",
    "TRANSCRIPTION_METHOD_CONFIG",
    "get_transcription_profile",
    "get_transcription_method_config",
    "get_audio_segment_granularity_for_method",
    "VideoToolPlanningProfile",
    "VIDEO_TOOL_PLANNING_PROFILES",
    "get_video_tool_planning_profile",
    "resolve_audio_driven_scene_split_threshold",
    "get_audio_driven_duration_values",
    "get_video_driven_duration_values",
    "get_audio_driven_split_threshold",
    "get_video_driven_split_threshold",
]
