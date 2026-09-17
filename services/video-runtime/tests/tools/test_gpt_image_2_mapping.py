"""
GPT Image 2：产品档位 + 宽高比 ↔ API 1k/2k/4k ↔ 最终 TARGET_PIXELS（不下真实 API）。

与 Nano/Seedream 的「capabilities + TARGET_PIXELS」单测同层：选满足 TARGET 的最小 API 档。
"""
import pytest

from app.models.tool_enums import AspectRatio, Resolution, ToolType
from app.tools.image.gpt_image_2_mapping import (
    gpt_image_2_api_resolution_and_quality,
    gpt_image_2_target_pixels,
)


@pytest.mark.parametrize(
    "user_res,ar,expected_api_res",
    [
        (Resolution.P480, AspectRatio.LANDSCAPE, "1k"),
        (Resolution.P480, AspectRatio.SQUARE, "1k"),
        (Resolution.P480, AspectRatio.PORTRAIT, "1k"),
        (Resolution.P720, AspectRatio.LANDSCAPE, "1k"),
        (Resolution.P720, AspectRatio.SQUARE, "1k"),
        (Resolution.P720, AspectRatio.PORTRAIT, "1k"),
        (Resolution.P1080, AspectRatio.LANDSCAPE, "2k"),
        (Resolution.P1080, AspectRatio.SQUARE, "2k"),
        (Resolution.P1080, AspectRatio.PORTRAIT, "2k"),
        ("480p", "16:9", "1k"),
        ("1080p", "1:1", "2k"),
    ],
)
def test_gpt_image_2_api_resolution_smallest_tier(user_res, ar, expected_api_res):
    api_res, q = gpt_image_2_api_resolution_and_quality(user_res, ar)
    assert api_res == expected_api_res
    assert q == "medium"


def test_gpt_image_2_api_mapping_invalid_string_defaults_to_1080p_target_tier():
    """无效 resolution 按 1080p 处理；16:9 下 2k 即覆盖 1920×1080。"""
    api_res, q = gpt_image_2_api_resolution_and_quality("not-a-resolution", "16:9")
    assert api_res == "2k"
    assert q == "medium"


@pytest.mark.parametrize(
    "user_res,ar,expected_wh",
    [
        (Resolution.P480, AspectRatio.LANDSCAPE, (854, 480)),
        (Resolution.P480, AspectRatio.PORTRAIT, (480, 854)),
        (Resolution.P480, AspectRatio.SQUARE, (480, 480)),
        (Resolution.P720, AspectRatio.LANDSCAPE, (1280, 720)),
        (Resolution.P720, AspectRatio.PORTRAIT, (720, 1280)),
        (Resolution.P720, AspectRatio.SQUARE, (720, 720)),
        (Resolution.P1080, AspectRatio.LANDSCAPE, (1920, 1080)),
        (Resolution.P1080, AspectRatio.PORTRAIT, (1080, 1920)),
        (Resolution.P1080, AspectRatio.SQUARE, (1080, 1080)),
        ("480p", "16:9", (854, 480)),
        ("720p", "9:16", (720, 1280)),
        ("1080p", "1:1", (1080, 1080)),
    ],
)
def test_gpt_image_2_target_pixels_match_target_pixels_table(user_res, ar, expected_wh):
    assert gpt_image_2_target_pixels(user_res, ar) == expected_wh


def test_gpt_image_2_documented_output_grid_never_requires_4k():
    """实测栅格下，产品 480/720/1080 × 三比例均可用 1k 或 2k 覆盖 TARGET。"""
    for res in (Resolution.P480, Resolution.P720, Resolution.P1080):
        for ar in (AspectRatio.LANDSCAPE, AspectRatio.SQUARE, AspectRatio.PORTRAIT):
            api_res, _ = gpt_image_2_api_resolution_and_quality(res, ar)
            assert api_res in ("1k", "2k")


@pytest.mark.parametrize(
    "qual,res,expected_usd",
    [
        ("low", "1k", 0.030),
        ("low", "2k", 0.060),
        ("low", "4k", 0.090),
        ("medium", "1k", 0.060),
        ("medium", "2k", 0.120),
        ("medium", "4k", 0.180),
        ("high", "1k", 0.220),
        ("high", "2k", 0.440),
        ("high", "4k", 0.660),
    ],
)
def test_tool_service_gpt_image_2_pricing_matrix_matches_wavespeed_table(qual, res, expected_usd):
    """ToolService 与 WaveSpeed 官方 quality × resolution 表一致（不 import cost_estimation / redis）。"""
    from app.services.tool_service import ToolService

    got = ToolService.calculate_cost(
        ToolType.GPT_IMAGE_2,
        gpt_image_resolution=res,
        gpt_image_quality=qual,
    )
    assert got == pytest.approx(expected_usd)
