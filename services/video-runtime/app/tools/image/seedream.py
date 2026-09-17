"""
ByteDance Seedream image-generation tool (via the WaveSpeed API)
"""
import logging
from typing import List, Annotated, Any, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from ....models.tool_enums import ToolMode, ToolType, ToolProvider
    from ....services.tool_service import ToolInfo
    from ....models.user_options import UserOption
from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime
from langsmith import traceable

from ...llm.wavespeed_service import WaveSpeedService
from ...models.image_result import ImageGenerationResult
from ..context_schemas import ImageGenerationContext
from ...services.tool_service import ToolService
from ...models.tool_enums import ToolProvider, ToolType, ToolName, Resolution, AspectRatio, TARGET_PIXELS
from ...services.account.account_router import get_account_router

logger = logging.getLogger(__name__)


# Seedream API requires a minimum pixel count; the user's requested resolution+aspect_ratio is satisfied in two steps: "this function returns the API size + downsample to TARGET_PIXELS"
SEEDREAM_MIN_PIXELS = 3_686_400  # 2560*1440, 1440*2560, 1920*1920


def convert_to_seedream_size(
    aspect_ratio: Union["AspectRatio", str],
    resolution: Union["Resolution", str],
) -> str:
    """Convert the user's requested aspect_ratio + resolution into a Seedream API size. The user's request must be met; here is how, under the API's minimum-pixel limit.

    The user asks for: resolution (e.g. 480p/720p/1080p) + aspect_ratio (e.g. 16:9/9:16/1:1).
    API limits: output >= 3,686,400 pixels, and cannot be specified by "resolution tier", only by width/height W*H.

    How to satisfy the user while meeting the API:
    1. Request from the API, for the user's aspect_ratio, the tier that "meets the minimum 3,686,400 pixels at that ratio" (e.g. 16:9 -> 2560*1440).
    2. Downsample the returned image per TARGET_PIXELS[(resolution, aspect_ratio)] (e.g. 480p 16:9 -> 854*480, 1080p 16:9 -> 1920*1080).
    This way the final image = the user's requested resolution + aspect_ratio, both satisfied.

    Args:
        aspect_ratio: user aspect ratio, AspectRatio or "16:9"/"9:16"/"1:1"
        resolution: user resolution, Resolution or "480p"/"720p"/"1080p" (together with aspect_ratio decides the downsample target TARGET_PIXELS)

    Returns:
        str: the size passed to the API in this step, e.g. "2560*1440", "1440*2560", "1920*1920"
    """
    if isinstance(aspect_ratio, AspectRatio):
        ar = aspect_ratio
    else:
        try:
            ar = AspectRatio((aspect_ratio or "").strip())
        except (ValueError, TypeError):
            ar = AspectRatio.LANDSCAPE
    if ar == AspectRatio.PORTRAIT:
        return "1440*2560"   # 9:16, 3,686,400
    if ar == AspectRatio.SQUARE:
        return "1920*1920"   # 1:1, 3,686,400
    # LANDSCAPE (16:9) or default
    return "2560*1440"       # 16:9, 3,686,400


class SeedreamInput(BaseModel):
    """Input schema for ByteDance Seedream image editing."""
    prompt: str = Field(
        description="Detailed editing instruction prompt. Describe what changes you want to make to the image. For example: 'Keep the model's pose and the flowing shape of the liquid clothing unchanged. Change the clothing material from silver metal to completely transparent clear water (or glass).'"
    )
    images: List[str] = Field(
        description="List of input image URLs to be edited. Currently supports single image editing."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.SEEDREAM_I2I, args_schema=SeedreamInput)
@traceable(run_type='llm')
async def edit_image_with_wavespeed_seedream(
    prompt: str,
    images: List[str],
    runtime: ToolRuntime[ImageGenerationContext]
) -> ImageGenerationResult:
    """Professional ByteDance Seedream v4.5 image editing tool (via WaveSpeed API).

    This tool provides high-quality image editing capabilities using ByteDance's Seedream v4.5 model.
    Perfect for complex image transformations and creative edits while maintaining composition and structure.

    🎯 Key Features:
    1. Advanced image editing with natural language instructions
    2. High-quality output with preserved image composition
    3. Support for complex transformations (material changes, lighting effects, etc.)
    4. Maintains pose and structure while transforming details

    Parameters:
    - prompt: Detailed editing instruction describing the desired changes
      Examples:
        - "Keep the model's pose unchanged. Change the clothing material from silver to glass."
        - "Transform the liquid flowing effect from metallic to water with transparency"
    - images: List of input image URLs (currently supports single image)

    Editing Examples:
    - Material transformation: "Change metal clothing to transparent water or glass"
    - Lighting effects: "Change light and shadow from reflection to refraction"
    - Texture modifications: "Transform solid material to liquid flowing effect"
    - Transparency effects: "Make objects semi-transparent with visible details underneath"
    - Surface properties: "Change from opaque to transparent, showing skin details through liquid"

    Returns: ImageGenerationResult object containing the editing results"""
    try:
        # get aspect_ratio and resolution from runtime.context
        # get aspect_ratio and resolution from runtime.context (using enums)
        from ...models.tool_enums import DefaultValues

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.IMAGE_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.IMAGE_RESOLUTION.value

        # 🎯 prefer reference_image_urls from runtime.context (code-level passing is more accurate)
        # if not present in runtime.context, use the LLM-passed arguments
        if runtime.context.reference_image_urls:
            logger.info(f"🎯 使用 runtime.context 中的 reference_image_urls（代码层面传入）: {len(runtime.context.reference_image_urls)} 张")
            final_images = runtime.context.reference_image_urls
        else:
            logger.info(f"📝 使用 LLM 传入的 images: {len(images)} 张")
            final_images = images

        # truncate reference images by model capability (upstream keyframe already sorts characters first)
        from .ref_utils import truncate_reference_urls_for_model
        truncated = truncate_reference_urls_for_model(final_images, ToolType.SEEDREAM_V4_5)
        final_images = truncated if truncated is not None else final_images

        # user resolution + aspect_ratio: API request uses convert_to_seedream_size, downsample target uses TARGET_PIXELS, so the final output is exactly what the user asked for
        size = convert_to_seedream_size(aspect_ratio, resolution)
        try:
            res_enum = Resolution(resolution) if isinstance(resolution, str) else resolution
            ar_enum = AspectRatio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
            target = TARGET_PIXELS.get((res_enum, ar_enum))
        except (ValueError, TypeError):
            target = None
        target_w, target_h = (target[0], target[1]) if target else (None, None)

        logger.info(f"🖼️ ByteDance Seedream 图像编辑开始")
        logger.info(f"🖼️ 编辑指令: {prompt[:100]}...")
        logger.info(f"🖼️ 输入图片数量: {len(final_images)}")
        logger.info(f"🖼️ 宽高比: {aspect_ratio}, 分辨率: {resolution} -> API size: {size}, 下采样目标: {f'{target_w}x{target_h}' if target else '无'}")

        if not final_images:
            raise ValueError("至少需要提供一张输入图片")

        # call via the account router (uses Redis rate limiting); downsampling happens inside WaveSpeed
        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.edit_image_seedream(
                prompt=prompt,
                images=final_images,
                size=size,
                target_width=target_w,
                target_height=target_h,
            )
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.SEEDREAM_V4_5,
            request_func=_make_request
        )

        if result.success:
            logger.info(f"✅ ByteDance Seedream 图像编辑成功: {result.image_url}")
            # I2I character-consistency validation and retry are handled uniformly by the wrapper (_run_i2i_one_model), not repeated here
            # ⭐ compute cost: $0.04 per generated image (simple, parameter-independent)
            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(
                cost_type=ToolType.SEEDREAM_V4_5,
                output_image_count=1
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 ByteDance Seedream 成本: ${cost:.6f}")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.SEEDREAM_I2I.value, tool_type=ToolType.SEEDREAM_V4_5)

            # consistent with nano_banana: on success also include aspect_ratio, resolution, model, for character-version persistence etc.
            data = result.model_dump()
            data.update(aspect_ratio=aspect_ratio, resolution=resolution, model=ToolType.SEEDREAM_V4_5.value, billing_cost=cost)
            return ImageGenerationResult(**data)
        else:
            logger.error(f"❌ ByteDance Seedream 图像编辑失败: {result.message}")
            return result

    except Exception as e:
        logger.error(f"❌ ByteDance Seedream 图像编辑异常: {str(e)}")
        result = ImageGenerationResult.error_result(
            error_message=f"ByteDance Seedream 图像编辑异常: {str(e)}",
            provider=ToolProvider.WAVESPEED.value,
            generated_prompt=prompt,
            reference_image_urls=final_images if 'final_images' in locals() else images,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model=ToolType.SEEDREAM_V4_5.value,
            raw_error_msg=str(e)
        )
        return result


class SeedreamT2IInput(BaseModel):
    """Input schema for ByteDance Seedream text-to-image generation."""
    prompt: str = Field(
        description="Detailed image description prompt. Describe the image content, style, composition, scene environment, etc. For example: 'Nighttime outdoor photoshoot: A young man stands inside a public phone booth, holding a blue phone receiver to his ear.'"
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.SEEDREAM_T2I, args_schema=SeedreamT2IInput)
@traceable(run_type='llm')
async def generate_image_with_wavespeed_seedream_t2i(
    prompt: str,
    runtime: ToolRuntime[ImageGenerationContext]
) -> ImageGenerationResult:
    """Professional ByteDance Seedream v4.5 image generation tool (via WaveSpeed API) - T2I text-to-image.

    This tool provides high-quality text-to-image generation using ByteDance's Seedream v4.5 model.
    Perfect for creating images from detailed text descriptions without requiring reference images.

    🎯 Key Features:
    1. Advanced text-to-image generation with natural language prompts
    2. High-quality output with detailed image generation
    3. Support for various artistic styles and compositions
    4. Flexible output size control

    Parameters:
    - prompt: Detailed image description prompt describing the desired image content, style, composition, etc.

    Prompt Examples:
    - Character scenes: "Nighttime outdoor photoshoot: A young man stands inside a public phone booth"
    - Landscapes: "A serene mountain lake at sunset with reflection of snow-capped peaks"
    - Artistic styles: "A cat sitting on a windowsill, watercolor painting style"
    - Fantasy scenes: "A magical forest with glowing mushrooms and fairy lights"

    Returns: ImageGenerationResult object containing the generation results"""
    try:
        # get aspect_ratio and resolution from runtime.context
        # get aspect_ratio and resolution from runtime.context (using enums)
        from ...models.tool_enums import DefaultValues

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.IMAGE_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.IMAGE_RESOLUTION.value

        # user resolution + aspect_ratio: API request uses convert_to_seedream_size, downsample target uses TARGET_PIXELS, so the final output is exactly what the user asked for
        size = convert_to_seedream_size(aspect_ratio, resolution)
        try:
            res_enum = Resolution(resolution) if isinstance(resolution, str) else resolution
            ar_enum = AspectRatio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
            target = TARGET_PIXELS.get((res_enum, ar_enum))
        except (ValueError, TypeError):
            target = None
        target_w, target_h = (target[0], target[1]) if target else (None, None)

        logger.info(f"🎨 ByteDance Seedream T2I 图像生成开始")
        logger.info(f"🎨 生成提示词: {prompt[:100]}...")
        logger.info(f"🎨 宽高比: {aspect_ratio}, 分辨率: {resolution} -> API size: {size}, 下采样目标: {f'{target_w}x{target_h}' if target else '无'}")

        # call via the account router (uses Redis rate limiting); downsampling happens inside WaveSpeed
        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_image_seedream_t2i(
                prompt=prompt,
                size=size,
                target_width=target_w,
                target_height=target_h,
            )
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.SEEDREAM_V4_5,
            request_func=_make_request
        )

        if result.success:
            logger.info(f"✅ ByteDance Seedream T2I 图像生成成功: {result.image_url}")

            # ⭐ compute cost: $0.04 per generated image (simple, parameter-independent)
            cost = ToolService.calculate_cost(
                cost_type=ToolType.SEEDREAM_V4_5,
                output_image_count=1
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 ByteDance Seedream T2I 成本: ${cost:.6f}")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.SEEDREAM_T2I.value, tool_type=ToolType.SEEDREAM_V4_5)

            # consistent with nano_banana: on success also include aspect_ratio, resolution, model, for character-version persistence etc.
            data = result.model_dump()
            data.update(aspect_ratio=aspect_ratio, resolution=resolution, model=ToolType.SEEDREAM_V4_5.value, billing_cost=cost)
            return ImageGenerationResult(**data)
        else:
            logger.error(f"❌ ByteDance Seedream T2I 图像生成失败: {result.message}")
            return result

    except Exception as e:
        logger.error(f"❌ ByteDance Seedream T2I 图像生成异常: {str(e)}")
        result = ImageGenerationResult.error_result(
            error_message=f"ByteDance Seedream T2I 图像生成异常: {str(e)}",
            provider=ToolProvider.WAVESPEED.value,
            generated_prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model=ToolType.SEEDREAM_V4_5.value,
            raw_error_msg=str(e)
        )
        return result
