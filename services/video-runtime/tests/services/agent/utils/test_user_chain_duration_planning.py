"""用户链规划：duration 交集与 per-tool scene_split_threshold。"""

from app.models.tool_enums import ContentCategory
from app.models.user_options import (
    UserOption,
    VideoGenerationTool,
)
from app.agent_config.video_tool_profiles import (
    VIDEO_TOOL_PLANNING_PROFILES,
    resolve_audio_driven_scene_split_threshold,
)
from app.agent_config.duration import (
    get_audio_driven_duration_values,
    get_audio_driven_split_threshold,
    get_video_driven_duration_values,
)
from app.services.agent.utils.video_tool_duration_capabilities import (
    get_audio_driven_duration_values_for_user,
    get_video_driven_duration_values_for_user,
)


def _opt(video_tool: VideoGenerationTool, lipsync_coverage: int = 0) -> UserOption:
    return UserOption(
        video_generation_tool=video_tool,
        lipsync_coverage=lipsync_coverage,
    )


def test_seedance_2_video_chain_intersection_4_to_12():
    opt = _opt(VideoGenerationTool.SEEDANCE_2_I2V)
    values = get_video_driven_duration_values_for_user(opt)
    assert values == list(range(4, 13))
    assert get_video_driven_duration_values(opt) == values


def test_seedance_2_audio_without_lipsync_same_as_video_chain():
    opt = _opt(VideoGenerationTool.SEEDANCE_2_I2V, lipsync_coverage=0)
    assert get_audio_driven_duration_values_for_user(opt) == list(range(4, 13))


def test_seedance_2_audio_with_lipsync_tightens_to_5_to_10():
    opt = _opt(VideoGenerationTool.SEEDANCE_2_I2V, lipsync_coverage=50)
    assert get_audio_driven_duration_values_for_user(opt) == list(range(5, 11))


def test_seedance_2_scene_split_threshold_profile_8():
    opt = _opt(VideoGenerationTool.SEEDANCE_2_I2V, lipsync_coverage=0)
    assert get_audio_driven_split_threshold(opt) == 8.0


def test_seedance_2_scene_split_with_lipsync_uses_explicit_min():
    """SD2 配置 8s；默认口型链无显式阈值 → 仍 8。"""
    opt = _opt(VideoGenerationTool.SEEDANCE_2_I2V, lipsync_coverage=50)
    assert get_audio_driven_split_threshold(opt) == 8.0


def test_lipsync_profile_can_cap_scene_split_when_configured(monkeypatch):
    from app.agent_config import video_tool_profiles as vtp
    from app.agent_config.video_tool_profiles import VideoToolPlanningProfile

    opt = UserOption(
        video_generation_tool=VideoGenerationTool.SEEDANCE_2_I2V,
        lipsync_video_tool=VideoGenerationTool.WAN_2_2_SPEECH_TO_VIDEO,
        lipsync_coverage=50,
    )
    values = get_audio_driven_duration_values(opt)
    monkeypatch.setitem(
        vtp.VIDEO_TOOL_PLANNING_PROFILES,
        VideoGenerationTool.WAN_2_2_SPEECH_TO_VIDEO,
        VideoToolPlanningProfile(scene_split_threshold_sec=5.0),
    )
    assert resolve_audio_driven_scene_split_threshold(opt, audio_driven_duration_values=values) == 5.0


def test_unconfigured_tool_falls_back_to_min_duration_values():
    # POLLO 已配置 scene_split_threshold_sec=8，避免落到链 min=3
    opt = _opt(VideoGenerationTool.POLLO_SEEDANCE, lipsync_coverage=0)
    assert get_audio_driven_split_threshold(opt) == 8.0
