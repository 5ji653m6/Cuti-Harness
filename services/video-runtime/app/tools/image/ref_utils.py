"""
Image reference-image utilities: truncate by model capability, keep characters after character-first sorting.
Shared by image_tool_wrapper, nano_banana, seedream.
"""
import logging
from typing import Dict, List, Optional

from app.models.tool_enums import ToolType

logger = logging.getLogger(__name__)

# per-model max reference-image counts (aligned with ToolService.get_max_reference_images_for_keyframe)
_MAX_REFERENCE_IMAGES_BY_MODEL = {
    ToolType.GEMINI_3_PRO_IMAGE_PREVIEW: 5,
    ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW: 4,  # 4 per the docs
    ToolType.GEMINI_2_5_FLASH_IMAGE: 3,
    ToolType.SEEDREAM_V4_5: 6,
    ToolType.GPT_IMAGE_2: 6,
}

# each image model's support for location (venue) reference images. Only GPT Image 2 can actually use a location image without the "giant" problem in practice;
# others default to False, to avoid distorting character proportions in wide shots. New image models must be registered here explicitly, otherwise they default to False.
_SUPPORTS_VENUE_REF_IMAGE_BY_MODEL: Dict[ToolType, bool] = {
    ToolType.GEMINI_2_5_FLASH_IMAGE: False,
    ToolType.GEMINI_3_PRO_IMAGE_PREVIEW: False,
    ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW: False,
    ToolType.SEEDREAM_V4_5: False,
    ToolType.GPT_IMAGE_2: True,
}


def get_max_reference_images_for_model(tool_type: ToolType) -> int:
    """Return the model's max reference-image count by ToolType. Used to truncate before I2I calls."""
    return _MAX_REFERENCE_IMAGES_BY_MODEL.get(tool_type, 3)


def supports_venue_ref_image(tool_type: Optional[ToolType]) -> bool:
    """Return, by ToolType, whether this image model supports feeding a location (venue) reference image without the wide-shot "giant" proportion distortion.
    Unregistered models are treated conservatively as False. When adding a model, be sure to register it in _SUPPORTS_VENUE_REF_IMAGE_BY_MODEL."""
    if tool_type is None:
        return False
    return _SUPPORTS_VENUE_REF_IMAGE_BY_MODEL.get(tool_type, False)


def truncate_reference_urls_for_model(
    urls: Optional[List[str]], tool_type: ToolType
) -> Optional[List[str]]:
    """Truncate the reference-image list by model capability (upstream should already sort characters first, so truncation keeps the first N)."""
    if not urls:
        return urls
    max_n = get_max_reference_images_for_model(tool_type)
    if len(urls) <= max_n:
        return urls
    logger.info(f"📐 按模型 {tool_type.value} 上限截断参考图: {len(urls)} -> {max_n}")
    return urls[:max_n]
