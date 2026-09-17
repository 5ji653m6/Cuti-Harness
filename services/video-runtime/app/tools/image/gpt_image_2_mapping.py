"""
GPT Image 2: mapping of product resolution / aspect_ratio to WaveSpeed API tiers and downsample targets.

The API uses resolution=1k|2k|4k (named differently from the product's 480p/720p/1080p); after generation the Media Service scales to TARGET_PIXELS.

Tier-selection strategy is consistent with Nano Banana's `convert_resolution_to_nano_banana_size`: on the measured output grid,
pick the **smallest** API tier that meets the TARGET width/height, to avoid needless 4k billing. Tier output pixels come from
`scripts/gpt_image_2_specs_results.json`（WaveSpeed openai/gpt-image-2 text-to-image, quality=medium）。

This module depends only on tool_enums, for cost estimation and unit-test imports; it does not start Redis / account_router.
"""
from typing import Optional, Tuple, Union

from app.models.tool_enums import AspectRatio, Resolution, TARGET_PIXELS

# WaveSpeed GPT Image 2 measured output per tier (WxH), consistent with tool-output-specs section 3.5
_GPT_IMAGE_2_OUTPUT_PIXELS: dict[tuple[AspectRatio, str], tuple[int, int]] = {
    (AspectRatio.LANDSCAPE, "1k"): (1360, 768),
    (AspectRatio.SQUARE, "1k"): (1024, 1024),
    (AspectRatio.PORTRAIT, "1k"): (768, 1360),
    (AspectRatio.LANDSCAPE, "2k"): (2560, 1440),
    (AspectRatio.SQUARE, "2k"): (1920, 1920),
    (AspectRatio.PORTRAIT, "2k"): (1440, 2560),
    (AspectRatio.LANDSCAPE, "4k"): (3840, 2160),
    (AspectRatio.SQUARE, "4k"): (2880, 2880),
    (AspectRatio.PORTRAIT, "4k"): (2160, 3840),
}

_GPT_IMAGE_2_TIER_ORDER: tuple[str, ...] = ("1k", "2k", "4k")


def _coerce_resolution(resolution: Union[Resolution, str]) -> Resolution:
    try:
        return Resolution(resolution) if isinstance(resolution, str) else resolution
    except (ValueError, TypeError):
        return Resolution.P1080


def _coerce_aspect_ratio(aspect_ratio: Union[AspectRatio, str, None]) -> AspectRatio:
    if aspect_ratio is None:
        return AspectRatio.LANDSCAPE
    try:
        return AspectRatio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
    except (ValueError, TypeError):
        return AspectRatio.LANDSCAPE


def gpt_image_2_api_resolution_and_quality(
    resolution: Union[Resolution, str],
    aspect_ratio: Optional[Union[AspectRatio, str]] = None,
) -> Tuple[str, str]:
    """Product tier + aspect ratio -> the smallest API resolution + quality meeting TARGET (currently fixed at medium)."""
    res_enum = _coerce_resolution(resolution)
    ar_enum = _coerce_aspect_ratio(aspect_ratio)
    target = TARGET_PIXELS.get((res_enum, ar_enum))
    quality = "medium"
    if not target:
        return ("4k", quality)
    tw, th = target[0], target[1]
    for tier in _GPT_IMAGE_2_TIER_ORDER:
        out = _GPT_IMAGE_2_OUTPUT_PIXELS.get((ar_enum, tier))
        if out and out[0] >= tw and out[1] >= th:
            return (tier, quality)
    return ("4k", quality)


def gpt_image_2_target_pixels(
    resolution: Union[Resolution, str],
    aspect_ratio: Union[AspectRatio, str],
) -> Tuple[int, int]:
    """Consistent with the keyframe pipeline: the final (width, height) to align to."""
    try:
        res = Resolution(resolution) if isinstance(resolution, str) else resolution
    except (ValueError, TypeError):
        res = Resolution.P1080
    try:
        ar = AspectRatio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
    except (ValueError, TypeError):
        ar = AspectRatio.LANDSCAPE
    t = TARGET_PIXELS.get((res, ar))
    if not t:
        return (1920, 1080)
    return (t[0], t[1])
