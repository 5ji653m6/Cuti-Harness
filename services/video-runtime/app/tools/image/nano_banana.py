"""
Nano Banana (Gemini) AI image-generation toolset
"""
import asyncio
import io
from enum import Enum
import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, cast, Literal, Annotated, TYPE_CHECKING
from typing_extensions import TypedDict
from pydantic import SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from langsmith import get_current_run_tree, traceable
from pydantic import BaseModel, Field
import random
from google import genai
from PIL import Image
from app.utils.s3_utils import s3_utils
from app.utils.image_utils import downsample_to_target_sync as _downsample_to_target_sync
from app.utils import media_service_client as msc
from app.models.image_result import ImageGenerationResult
from app.services.tool_service import ToolService
from app.services.account.account_router import get_account_router

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models.tool_enums import ToolMode, AspectRatio, Resolution, ToolType, ToolProvider
    from app.services.tool_service import ToolInfo
    from app.models.user_options import UserOption


from ..context_schemas import ImageGenerationContext
from app.tools.runtime import ToolRuntime
from ...models.tool_enums import ToolType, DefaultValues, ToolName, AspectRatio, Resolution, TARGET_PIXELS
from ...models.user_options import ImageGenerationTool


# ==================== Nano Banana image sizes (used only by this tool) ====================
# Docs: https://ai.google.dev/gemini-api/docs/image-generation

class ImageSize(str, Enum):
    """Nano Banana API image_size enum (1K/2K/4K/512px)."""
    PX512 = "512px"   # only supported by Gemini 3.1 Flash Image
    ONE_K = "1K"
    TWO_K = "2K"
    FOUR_K = "4K"


# Gemini 3.1 Flash Image (Nano Banana 2): supports 512px / 1K / 2K / 4K
NANO_BANANA_2_OUTPUT_PIXELS: dict[tuple[AspectRatio, ImageSize], tuple[int, int]] = {
    (AspectRatio.SQUARE, ImageSize.PX512): (512, 512),
    (AspectRatio.SQUARE, ImageSize.ONE_K): (1024, 1024),
    (AspectRatio.SQUARE, ImageSize.TWO_K): (2048, 2048),
    (AspectRatio.SQUARE, ImageSize.FOUR_K): (4096, 4096),
    (AspectRatio.PORTRAIT, ImageSize.PX512): (384, 688),
    (AspectRatio.PORTRAIT, ImageSize.ONE_K): (768, 1376),
    (AspectRatio.PORTRAIT, ImageSize.TWO_K): (1536, 2752),
    (AspectRatio.PORTRAIT, ImageSize.FOUR_K): (3072, 5504),
    (AspectRatio.LANDSCAPE, ImageSize.PX512): (688, 384),
    (AspectRatio.LANDSCAPE, ImageSize.ONE_K): (1376, 768),
    (AspectRatio.LANDSCAPE, ImageSize.TWO_K): (2752, 1536),
    (AspectRatio.LANDSCAPE, ImageSize.FOUR_K): (5504, 3072),
}

# Gemini 3 Pro Image (Nano Banana Pro): supports 1K / 2K / 4K (no 512px)
NANO_BANANA_PRO_OUTPUT_PIXELS: dict[tuple[AspectRatio, ImageSize], tuple[int, int]] = {
    (AspectRatio.SQUARE, ImageSize.ONE_K): (1024, 1024),
    (AspectRatio.SQUARE, ImageSize.TWO_K): (2048, 2048),
    (AspectRatio.SQUARE, ImageSize.FOUR_K): (4096, 4096),
    (AspectRatio.PORTRAIT, ImageSize.ONE_K): (768, 1376),
    (AspectRatio.PORTRAIT, ImageSize.TWO_K): (1536, 2752),
    (AspectRatio.PORTRAIT, ImageSize.FOUR_K): (3072, 5504),
    (AspectRatio.LANDSCAPE, ImageSize.ONE_K): (1376, 768),
    (AspectRatio.LANDSCAPE, ImageSize.TWO_K): (2752, 1536),
    (AspectRatio.LANDSCAPE, ImageSize.FOUR_K): (5504, 3072),
}

# Gemini 2.5 Flash Image: does not support imageSize, fixed output (for downsampling reference)
NANO_BANANA_25_FLASH_OUTPUT_PIXELS: dict[AspectRatio, tuple[int, int]] = {
    AspectRatio.SQUARE: (1024, 1024),
    AspectRatio.PORTRAIT: (768, 1344),
    AspectRatio.LANDSCAPE: (1344, 768),
}

NANO_BANANA_2_IMAGE_SIZE_ORDER: tuple[ImageSize, ...] = (ImageSize.PX512, ImageSize.ONE_K, ImageSize.TWO_K, ImageSize.FOUR_K)
NANO_BANANA_PRO_IMAGE_SIZE_ORDER: tuple[ImageSize, ...] = (ImageSize.ONE_K, ImageSize.TWO_K, ImageSize.FOUR_K)


def convert_resolution_to_nano_banana_size(
    resolution: "Resolution",
    aspect_ratio: "AspectRatio",
    model: "ToolType",
) -> Optional[str]:
    """Pick the Nano Banana API image_size (1K/2K/4K/512px) based on the target resolution and aspect ratio.
    Choose the smallest tier that meets the target pixels, for later downsampling to TARGET_PIXELS.
    2.5 Flash does not support imageSize; returns None and the caller omits imageSize.
    2.5 Flash 1080p: API max output is 1344x768 (landscape) / 768x1344 (portrait) / 1024x1024 (square), cannot reach 1920x1080,
    the downsampling stage keeps scale=1 at the original size; if the product needs "standard 1080p only", the option layer can restrict 2.5 Flash to 480p/720p only.
    """
    from ...models.tool_enums import ToolType, Resolution, AspectRatio, TARGET_PIXELS
    if model == ToolType.GEMINI_2_5_FLASH_IMAGE:
        return None
    target = TARGET_PIXELS.get((resolution, aspect_ratio))
    if not target:
        return ImageSize.ONE_K.value
    tw, th = target
    if model == ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW:
        table = NANO_BANANA_2_OUTPUT_PIXELS
        order = NANO_BANANA_2_IMAGE_SIZE_ORDER
    elif model == ToolType.GEMINI_3_PRO_IMAGE_PREVIEW:
        table = NANO_BANANA_PRO_OUTPUT_PIXELS
        order = NANO_BANANA_PRO_IMAGE_SIZE_ORDER
    else:
        return ImageSize.ONE_K.value
    for size in order:
        out = table.get((aspect_ratio, size))
        if out and out[0] >= tw and out[1] >= th:
            return size.value
    return ImageSize.FOUR_K.value




# define the function first, then set the description dynamically
async def _generate_image_with_nano_banana(
    prompt: str,
    reference_image_urls: Optional[List[str]] = None,
    aspect_ratio: Optional['AspectRatio'] = None,
    resolution: Optional['Resolution'] = None,
    model: Optional['ToolType'] = None,
) -> ImageGenerationResult:

    from ...models.tool_enums import AspectRatio, Resolution, ToolType, ToolProvider, DefaultValues, TARGET_PIXELS

    # use the default value
    if aspect_ratio is None:
        aspect_ratio = DefaultValues.IMAGE_ASPECT_RATIO
    if resolution is None:
        resolution = DefaultValues.IMAGE_RESOLUTION
    if model is None:
        model = DefaultValues.IMAGE_MODEL

    # truncate reference images by model capability (upstream keyframe already sorts characters first, so truncation keeps characters)
    from .ref_utils import truncate_reference_urls_for_model
    reference_image_urls = truncate_reference_urls_for_model(reference_image_urls, model)

    try:
        logger.info(f"🍌 Nano Banana图像生成开始")
        logger.info(f"📝 提示词: {prompt}")

        # handle reference images
        processed_reference_urls = None
        contents = [prompt]

        if reference_image_urls:
            logger.info(f"🖼️  参考图片数量: {len(reference_image_urls)}")
            processed_reference_urls = []
            for i, image_url in enumerate(reference_image_urls):
                try:
                    processed_reference_urls.append(image_url)

                    # get the file extension from the URL
                    ext = Path(image_url).suffix
                    if not ext:
                        ext = '.webp'  # default image extension

                    # use a temp file to download from S3 (similar to transcribe_audio_with_whisper)
                    with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as temp_file:
                        # download the image from S3 to a temp file
                        success = await s3_utils.download_file(image_url, temp_file.name)
                        if not success:
                            logger.error(f"无法从S3下载图片: {image_url}")
                            continue

                        # put PIL decode in a thread pool to avoid blocking the event loop
                        loop = asyncio.get_event_loop()
                        image = await loop.run_in_executor(
                            None,
                            lambda p=temp_file.name: Image.open(p).copy(),
                        )
                        contents.append(image)
                        # the file is auto-deleted after the with block ends
                except Exception as e:
                    logger.warning(f"⚠️ 参考图片 {i+1} 加载失败: {e}")
        else:
            logger.info(f"📝 纯文生图模式")

        # call the Gemini API
        model_name = model.value

        logger.info(f"🚀 调用 Gemini API，使用模型: {model_name}")

        # google-genai 1.56.0+ uses camelCase: aspectRatio, imageSize
        # image_size is supported by Pro and 3.1 Flash Image (Nano Banana 2)
        is_pro = model in (ToolType.GEMINI_3_PRO_IMAGE_PREVIEW, ToolType.GEMINI_3_1_FLASH_IMAGE_PREVIEW)

        aspect_ratio_str = aspect_ratio.value
        resolution_str = resolution.value

        # generate a seed for the API call and result logging
        api_seed = random.randint(0, 2147483647)

        # define the actual request function (takes api_key as the first parameter)
        async def _make_gemini_request(api_key: str):
            """The actual Gemini API call."""
            client = genai.Client(api_key=api_key, http_options=genai.types.HttpOptions(timeout=120_000))  # 5-minute timeout

            if is_pro:
                # Pro / Nano Banana 2: supports imageSize (1K/2K/4K/512px), pick the smallest tier that meets the target pixels
                image_size = convert_resolution_to_nano_banana_size(resolution, aspect_ratio, model)
                logger.info(f"📐 参数: aspectRatio={aspect_ratio_str}, resolution={resolution_str} -> imageSize={image_size}")
                image_config_kw: dict = {"aspectRatio": aspect_ratio_str}
                if image_size is not None:
                    image_config_kw["imageSize"] = image_size
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=genai.types.GenerateContentConfig(
                        response_modalities=['TEXT', 'IMAGE'],  # the Pro version needs this specified explicitly
                        image_config=genai.types.ImageConfig(**image_config_kw),
                        seed=api_seed
                    )
                )
            else:
                # non-Pro version (Gemini 2.5 Flash Image): only supports aspectRatio
                # ⭐ add response_modalities=['Image'] to ensure only image output, no text
                logger.info(f"📐 参数: aspectRatio={aspect_ratio_str} (非Pro版本不支持imageSize)")

                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=genai.types.GenerateContentConfig(
                        response_modalities=['Image'],  # ⭐ ensure image-only output
                        image_config=genai.types.ImageConfig(
                            aspectRatio=aspect_ratio_str  # camelCase
                        ),
                        seed=api_seed
                    )
                )

            return response

        # use the account router
        from ...models.tool_enums import ToolProvider
        router = await get_account_router()
        response = await router.route_tool_request(
            provider=ToolProvider.GOOGLE,
            tool_type=model,  # model is already a ToolType
            request_func=_make_gemini_request
        )

        logger.info(f"✅ Gemini API 调用完成")

        # ⭐ extract usage_metadata (for cost calculation)
        if not hasattr(response, 'usage_metadata') or not response.usage_metadata:
            raise Exception("Gemini API 响应缺少 usage_metadata")

        usage_metadata = response.usage_metadata
        logger.info(f"📊 Usage Metadata: prompt_tokens={usage_metadata.prompt_token_count}, "
                   f"candidates_tokens={usage_metadata.candidates_token_count}, "
                   f"total_tokens={usage_metadata.total_token_count}")

        # use response.parts directly, no longer via candidates
        if not response or not getattr(response, "parts", None):
            raise Exception("Gemini API 返回无效响应（无 parts）")

        generated_image_url = None
        generated_text = None

        for part in response.parts:
            if part.text is not None:
                generated_text = part.text
            elif part.inline_data is not None:
                # take the image -> downsample to TARGET_PIXELS -> upload to S3
                # note: cost calculation depends only on the API-returned usage_metadata (token/image tier), independent of downsampling, see the ⭐ compute-cost-with-usage_metadata below
                if hasattr(part.inline_data, "data") and part.inline_data.data:
                    image_bytes = part.inline_data.data
                else:
                    pil_img = part.as_image()
                    buf = io.BytesIO()
                    pil_img.save(buf, format="PNG")
                    image_bytes = buf.getvalue()
                # Local downsample: Gemini returns raw bytes (not a URL), so msc.image_resize
                # (which requires an HTTP URL) is not applicable here without an extra upload round-trip.
                target = TARGET_PIXELS.get((resolution, aspect_ratio))
                if target:
                    tw, th = target
                    loop = asyncio.get_event_loop()
                    image_bytes, _ = await loop.run_in_executor(None, _downsample_to_target_sync, image_bytes, tw, th)
                logger.info(f"💾 上传图像到S3...")
                generated_image_url = await s3_utils.upload_image(image_bytes)
                logger.info(f"✅ 图像生成成功: {generated_image_url}")

        # return a uniform-format result
        if generated_image_url:
            result = ImageGenerationResult.success_result(
                image_url=generated_image_url,
                generated_prompt=prompt,
                provider=ToolProvider.GOOGLE.value,  # use ToolProvider
                message="✅ Nano Banana图像生成成功",
                reference_image_urls=processed_reference_urls if processed_reference_urls else reference_image_urls,
                seed=api_seed,  # use the seed passed to the API
                aspect_ratio=aspect_ratio_str,
                resolution=resolution_str,
                model=model.value,  # use the ToolType enum value
            )

            # ⭐ cost calculation: depends only on the API-returned usage_metadata (requested token/image tier), independent of local downsampling or upload format, unaffected by later TARGET_PIXELS or imageSize processing
            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(
                cost_type=model,
                usage_metadata=usage_metadata
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Nano Banana 成本: ${cost:.6f}")
                cb = ToolService.get_credit_callback()
                if cb:
                    cb.add_tool_cost(cost, tool_name=model.value, tool_type=model)
            result = result.model_copy(update={"billing_cost": cost})

            # I2I character-consistency validation and retry are handled uniformly by the wrapper (_run_i2i_one_model), not repeated here
            logger.info(f"🎉 Nano Banana 图像生成完成")
            return result
        else:
            error_message = f"Nano Banana图像生成失败: 未获取到生成的图像"
            if generated_text:
                error_message += f" (API返回文本: {generated_text})"
            result = ImageGenerationResult.error_result(
                error_message=error_message,
                provider=ToolProvider.GOOGLE.value,
                generated_prompt=prompt,
                reference_image_urls=processed_reference_urls if processed_reference_urls else reference_image_urls,
                aspect_ratio=aspect_ratio_str,
                resolution=resolution_str,
                model=model.value
            )
            logger.error(f"❌ {error_message}")
            return result

    except Exception as e:
        logger.error(f"❌ Nano Banana 图像生成失败: {str(e)}")

        # use the original exception message directly, it contains important debug info
        error_msg = f"Nano Banana图像生成失败: {str(e)}"

        result = ImageGenerationResult.error_result(
            error_message=error_msg,
            provider=ToolProvider.GOOGLE.value,
            generated_prompt=prompt,
            reference_image_urls=reference_image_urls,
            aspect_ratio=aspect_ratio.value if aspect_ratio else None,
            resolution=resolution.value if resolution else None,
            model=model.value if model else None,
            raw_error_msg=str(e)
        )
        return result



class NanoBananaT2IInput(BaseModel):
    """Input schema for Nano Banana text-to-image generation."""
    prompt: str = Field(
        description="Detailed image description prompt. Describe the image content, style, composition, character appearance, scene environment, artistic style, etc. Be specific and detailed for better results."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )

@tool(ToolName.NANO_BANANA_T2I, args_schema=NanoBananaT2IInput)
async def generate_image_with_nano_banana_t2i(
    prompt: str,
    runtime: ToolRuntime[ImageGenerationContext]
) -> ImageGenerationResult:
    """Professional Nano Banana (Gemini) AI image generation tool - T2I text-to-image

    This is an AI image generation tool based on Google Gemini 2.5 Flash Image Preview.
    Specifically designed for generating high-quality images from text prompts without reference images.

    Args:
        prompt: Detailed image description prompt describing the desired image content, style, composition, etc.

    Returns:
        JSON format data containing the generation results
    """
    # get aspect_ratio, resolution, model from runtime.context (using enums)
    from ...models.tool_enums import DefaultValues

    aspect_ratio = runtime.context.aspect_ratio if runtime.context.aspect_ratio else DefaultValues.IMAGE_ASPECT_RATIO
    resolution = runtime.context.resolution if runtime.context.resolution else DefaultValues.IMAGE_RESOLUTION
    model = runtime.context.model if runtime.context.model else DefaultValues.IMAGE_MODEL

    return await _generate_image_with_nano_banana(prompt, None, aspect_ratio, resolution, model)


class NanoBananaI2IInput(BaseModel):
    """Input schema for Nano Banana image-to-image generation."""
    prompt: str = Field(
        description="""Image generation prompt based on reference images.
IMPORTANT GUIDELINES:
1. When combining elements, be specific about which elements to take from which image (e.g., "the character from image 1", "the background from image 2")
2. Clearly describe how to combine the elements when needed
3. Provide a detailed description of the final desired scene
"""
    )
    reference_image_urls: List[str] = Field(
        description="List of reference image URLs for image editing or style reference. These images will be used to maintain character consistency and provide visual context for the generation."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )

@tool(ToolName.NANO_BANANA_I2I, args_schema=NanoBananaI2IInput)
async def generate_image_with_nano_banana_i2i(
    prompt: str,
    reference_image_urls: List[str],
    runtime: ToolRuntime[ImageGenerationContext]
) -> ImageGenerationResult:
    """Professional Nano Banana (Gemini) AI image generation tool - I2I image-to-image

    This is an AI image generation tool based on Google Gemini 2.5 Flash Image Preview.
    Specifically designed for generating images using reference images and text prompts.

    Args:
        prompt: Image generation prompt that must specify which elements to take from which reference images and how to combine them
        reference_image_urls: List of reference image URLs for image editing or style reference

    Returns:
        JSON format data containing the generation results
    """
    # get aspect_ratio, resolution, model from runtime.context (using enums)
    from ...models.tool_enums import DefaultValues

    aspect_ratio = runtime.context.aspect_ratio if runtime.context.aspect_ratio else DefaultValues.IMAGE_ASPECT_RATIO
    resolution = runtime.context.resolution if runtime.context.resolution else DefaultValues.IMAGE_RESOLUTION
    model = runtime.context.model if runtime.context.model else DefaultValues.IMAGE_MODEL

    # 🎯 prefer reference_image_urls from runtime.context (code-level passing is more accurate)
    # if not present in runtime.context, use the LLM-passed arguments
    if runtime.context.reference_image_urls:
        logger.info(f"🎯 使用 runtime.context 中的 reference_image_urls（代码层面传入）: {len(runtime.context.reference_image_urls)} 张")
        final_reference_urls = runtime.context.reference_image_urls
    else:
        logger.info(f"📝 使用 LLM 传入的 reference_image_urls: {len(reference_image_urls)} 张")
        final_reference_urls = reference_image_urls

    return await _generate_image_with_nano_banana(prompt, final_reference_urls, aspect_ratio, resolution, model)
