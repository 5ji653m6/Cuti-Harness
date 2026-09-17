"""
convert_resolution_to_nano_banana_size 单元测试。

按 TARGET_PIXELS 与模型输出表，选满足目标像素的最小 image_size（1K/2K/4K/512px）；
2.5 Flash 不支持 imageSize，返回 None。

运行：
  pytest tests/tools/test_nano_banana_resolution.py -v
"""
import pytest

from app.models.tool_enums import Resolution, AspectRatio, ToolType
from app.tools.image.nano_banana import convert_resolution_to_nano_banana_size


@pytest.mark.parametrize(
    "resolution,aspect_ratio,model,expected",
    [
        # 16:9：480p/720p 用 1K 即够，1080p 需 2K（目标 1920x1080，1K=1376x768 不足）
        (Resolution.P480, AspectRatio.LANDSCAPE, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, "1K"),
        (Resolution.P720, AspectRatio.LANDSCAPE, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, "1K"),
        (Resolution.P1080, AspectRatio.LANDSCAPE, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, "2K"),
        (Resolution.P480, AspectRatio.LANDSCAPE, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, "1K"),
        (Resolution.P720, AspectRatio.LANDSCAPE, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, "1K"),
        (Resolution.P1080, AspectRatio.LANDSCAPE, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, "2K"),
        # 2.5 Flash：不传 imageSize
        (Resolution.P720, AspectRatio.LANDSCAPE, ToolType.GEMINI_2_5_FLASH_IMAGE, None),
        (Resolution.P1080, AspectRatio.LANDSCAPE, ToolType.GEMINI_2_5_FLASH_IMAGE, None),
        # 9:16
        (Resolution.P720, AspectRatio.PORTRAIT, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, "1K"),
        (Resolution.P1080, AspectRatio.PORTRAIT, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, "2K"),
        # 1:1：1080p 需 2K（1024<1080）；480p 1:1 Nano Banana 2 可用 512px（512>=480）
        (Resolution.P1080, AspectRatio.SQUARE, ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, "2K"),
        (Resolution.P480, AspectRatio.SQUARE, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW, "512px"),
    ],
)
def test_convert_resolution_to_nano_banana_size(
    resolution: Resolution,
    aspect_ratio: AspectRatio,
    model: ToolType,
    expected: str | None,
) -> None:
    assert convert_resolution_to_nano_banana_size(resolution, aspect_ratio, model) == expected
