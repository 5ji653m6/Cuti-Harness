"""video_tool_duration_capabilities：链上 ToolInfo.supported_duration_seconds 与规划交集。"""

from app.models.tool_enums import ToolType
from app.models.user_options import LIPSYNC_CAPABLE_VIDEO_TOOLS, VideoGenerationTool
from app.services.agent.utils import video_tool_duration_capabilities as vtdc
from app.tools.video.lipsync_tool_wrapper import _get_lipsync_chain
from app.tools.video.video_tool_wrapper import _get_video_chain


def test_normal_i2v_chain_toolinfo_has_supported_duration_seconds():
    for vt in VideoGenerationTool:
        for info in _get_video_chain(vt):
            assert info.supported_duration_seconds is not None, (
                f"{vt!r} chain entry {info.tool_type!r} missing supported_duration_seconds"
            )


def test_lipsync_chain_toolinfo_has_supported_duration_seconds():
    for vt in list(LIPSYNC_CAPABLE_VIDEO_TOOLS) + [None]:
        for info in _get_lipsync_chain(vt):
            assert info.supported_duration_seconds is not None, info.tool_type


def test_video_list_is_sorted_unique_intersection():
    assert vtdc.VIDEO_DRIVEN_PLANNING_DURATION_VALUES == sorted(
        set(vtdc.VIDEO_DRIVEN_PLANNING_DURATION_VALUES)
    )
    assert len(vtdc.VIDEO_DRIVEN_PLANNING_DURATION_VALUES) >= 1


def test_audio_includes_at_least_video_types():
    assert vtdc._NORMAL_I2V_TYPES <= vtdc._AUDIO_PLANNING_TYPES
    assert vtdc._LIPSYNC_CHAIN_TYPES <= vtdc._AUDIO_PLANNING_TYPES


def test_sora_discrete_on_chain_toolinfo():
    for vt in (VideoGenerationTool.OPENAI_SORA, VideoGenerationTool.OPENAI_SORA_PRO):
        for info in _get_video_chain(vt):
            if info.tool_type in (ToolType.SORA_2, ToolType.SORA_2_PRO):
                assert info.supported_duration_seconds == frozenset({4, 8, 12})


def test_planning_intersection_excludes_sora():
    """Sora 仍挂在链上，但不参与 VIDEO/AUDIO 规划列表交集（避免压成 4、8）。"""
    assert ToolType.SORA_2 in vtdc._EXCLUDE_FROM_PLANNING_INTERSECTION
    assert 4 in vtdc.VIDEO_DRIVEN_PLANNING_DURATION_VALUES
    assert 10 in vtdc.VIDEO_DRIVEN_PLANNING_DURATION_VALUES
    assert 5 in vtdc.AUDIO_DRIVEN_PLANNING_DURATION_VALUES
    assert 3 not in vtdc.AUDIO_DRIVEN_PLANNING_DURATION_VALUES


def test_video_driven_is_video_chain_only_audio_adds_lipsync_types():
    """AUDIO 规划合并 lipsync 链；VIDEO 仅 video_tool_wrapper，不含 lipsync-only ToolType。"""
    assert ToolType.LTX_2_3_LIPSYNC in vtdc._AUDIO_BY_TYPE
    assert ToolType.LTX_2_3_LIPSYNC not in vtdc._NORMAL_BY_TYPE
