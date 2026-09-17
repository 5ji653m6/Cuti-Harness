"""
Per-tool video/lip-sync planning config (aligned with user_options.VideoGenerationTool).

Only holds product strategy that cannot be derived from the chain's supported_duration_seconds (e.g. scene_split_threshold_sec).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models.user_options import (
    UserOption,
    VideoGenerationTool,
    resolve_effective_lipsync_tool,
    resolve_effective_video_tool,
    should_apply_lipsync_for_planning,
)


@dataclass(frozen=True)
class VideoToolPlanningProfile:
    """Planning knobs for a single user-selectable video/lip-sync tool."""

    scene_split_threshold_sec: Optional[float] = None


VIDEO_TOOL_PLANNING_PROFILES: Dict[VideoGenerationTool, VideoToolPlanningProfile] = {
    # also raise the split threshold for the default/old Seedance chain, to avoid audio-driven cutting into fragments at min=3
    VideoGenerationTool.POLLO_SEEDANCE: VideoToolPlanningProfile(scene_split_threshold_sec=8.0),
    VideoGenerationTool.SEEDANCE_V1_5: VideoToolPlanningProfile(scene_split_threshold_sec=8.0),
    VideoGenerationTool.SEEDANCE_2_I2V: VideoToolPlanningProfile(scene_split_threshold_sec=8.0),
    VideoGenerationTool.SEEDANCE_2_I2V_TURBO: VideoToolPlanningProfile(scene_split_threshold_sec=8.0),
    VideoGenerationTool.SEEDANCE_2_FAST_I2V: VideoToolPlanningProfile(scene_split_threshold_sec=8.0),
    VideoGenerationTool.SEEDANCE_2_FAST_I2V_TURBO: VideoToolPlanningProfile(scene_split_threshold_sec=8.0),
}


def get_video_tool_planning_profile(tool: VideoGenerationTool) -> VideoToolPlanningProfile:
    return VIDEO_TOOL_PLANNING_PROFILES.get(tool, VideoToolPlanningProfile())


def resolve_scene_split_threshold(
    user_option: UserOption,
    *,
    duration_values: List[int],
) -> float:
    """Resolve this run's scene-split / planning-prefer threshold (seconds).

    Used for audio-driven splitting **and** video-driven cost/duration estimation.
    Explicit profile takes priority; otherwise preferred_planning_unit (leans to 8s); never fall back to the tool chain's min=3.
    """
    from app.agent_config.duration import preferred_planning_unit

    fallback = float(preferred_planning_unit(duration_values))
    explicit: List[float] = []

    vt = resolve_effective_video_tool(user_option)
    v_prof = get_video_tool_planning_profile(vt)
    if v_prof.scene_split_threshold_sec is not None:
        explicit.append(float(v_prof.scene_split_threshold_sec))

    if should_apply_lipsync_for_planning(user_option):
        lt = resolve_effective_lipsync_tool(user_option)
        l_prof = get_video_tool_planning_profile(lt)
        if l_prof.scene_split_threshold_sec is not None:
            explicit.append(float(l_prof.scene_split_threshold_sec))

    if explicit:
        return float(min(explicit))
    return fallback


# Back-compat alias (audio-driven call sites)
def resolve_audio_driven_scene_split_threshold(
    user_option: UserOption,
    *,
    audio_driven_duration_values: List[int],
) -> float:
    return resolve_scene_split_threshold(
        user_option, duration_values=audio_driven_duration_values
    )
