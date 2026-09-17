"""规划层 duration API：与 video_tool_duration_capabilities 工具链交集一致。"""

from app.agent_config.duration import (
    get_audio_driven_duration_values,
    get_audio_driven_split_threshold,
    get_video_driven_duration_values,
    get_video_driven_split_threshold,
)
from app.models.user_options import UserOption
from app.services.agent.utils.video_tool_duration_capabilities import (
    AUDIO_DRIVEN_PLANNING_DURATION_VALUES,
    VIDEO_DRIVEN_PLANNING_DURATION_VALUES,
)


def test_none_user_option_matches_module_constants():
    assert get_audio_driven_duration_values() == list(AUDIO_DRIVEN_PLANNING_DURATION_VALUES)
    assert get_audio_driven_duration_values(None) == list(AUDIO_DRIVEN_PLANNING_DURATION_VALUES)
    assert get_video_driven_duration_values() == list(VIDEO_DRIVEN_PLANNING_DURATION_VALUES)
    assert get_video_driven_duration_values(None) == list(VIDEO_DRIVEN_PLANNING_DURATION_VALUES)


def test_default_user_option_uses_effective_video_chain_not_global_constants():
    """UserOption.default() 为 pollo_seedance；规划应跟该链而非全产品常量。"""
    opt = UserOption.default()
    from app.services.agent.utils.video_tool_duration_capabilities import (
        get_audio_driven_duration_values_for_user,
        get_video_driven_duration_values_for_user,
    )

    assert get_video_driven_duration_values(opt) == get_video_driven_duration_values_for_user(opt)
    assert get_audio_driven_duration_values(opt) == get_audio_driven_duration_values_for_user(opt)


def test_split_threshold_none_user_option_is_global_min():
    from app.agent_config.duration import preferred_planning_unit

    exp = float(min(AUDIO_DRIVEN_PLANNING_DURATION_VALUES))
    assert get_audio_driven_split_threshold(None, None) == exp
    # video-driven: prefer unit (≈8), never advertise API min as planning target
    assert get_video_driven_split_threshold(None) == float(
        preferred_planning_unit(VIDEO_DRIVEN_PLANNING_DURATION_VALUES)
    )


def test_default_user_option_split_threshold_follows_profile_prefer():
    opt = UserOption.default()
    # 默认 POLLO / Seedance 规划 profile = 8s（audio + video-driven 同源）
    assert get_audio_driven_split_threshold(opt, None) == 8.0
    assert get_video_driven_split_threshold(opt) == 8.0


def test_global_fallback_lists_exclude_sora_and_are_sorted():
    """无 user_option 时的全产品交集（排除 Sora）；随链配置演进，只断言结构性不变量。"""
    assert VIDEO_DRIVEN_PLANNING_DURATION_VALUES == sorted(set(VIDEO_DRIVEN_PLANNING_DURATION_VALUES))
    assert AUDIO_DRIVEN_PLANNING_DURATION_VALUES == sorted(set(AUDIO_DRIVEN_PLANNING_DURATION_VALUES))
    assert min(VIDEO_DRIVEN_PLANNING_DURATION_VALUES) >= 4
    assert min(AUDIO_DRIVEN_PLANNING_DURATION_VALUES) >= 5
    assert max(VIDEO_DRIVEN_PLANNING_DURATION_VALUES) <= 12
    assert max(AUDIO_DRIVEN_PLANNING_DURATION_VALUES) <= 10
