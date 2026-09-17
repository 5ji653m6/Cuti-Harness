"""
OpenAI GPT Image 2 image generation (WaveSpeed: text-to-image + edit)
"""
import logging
from typing import Annotated, Any, List, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from ....models.tool_enums import ToolType, ToolProvider
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
from .gpt_image_2_mapping import gpt_image_2_api_resolution_and_quality

logger = logging.getLogger(__name__)


class GptImage2T2IInput(BaseModel):
    """Input schema for GPT Image 2 text-to-image."""
    prompt: str = Field(description="Detailed image description prompt.")
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.GPT_IMAGE_2_T2I, args_schema=GptImage2T2IInput)
@traceable(run_type="llm")
async def generate_image_with_wavespeed_gpt_image_2_t2i(
    prompt: str,
    runtime: ToolRuntime[ImageGenerationContext],
) -> ImageGenerationResult:
    """OpenAI GPT Image 2 text-to-image (via WaveSpeed). High-quality generation from natural-language prompts."""
    try:
        from ...models.tool_enums import DefaultValues

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.IMAGE_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.IMAGE_RESOLUTION.value
        gpt_res, quality = gpt_image_2_api_resolution_and_quality(resolution, aspect_ratio)
        try:
            res_enum = Resolution(resolution) if isinstance(resolution, str) else resolution
            ar_enum = AspectRatio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
            target = TARGET_PIXELS.get((res_enum, ar_enum))
        except (ValueError, TypeError):
            target = None
        target_w, target_h = (target[0], target[1]) if target else (None, None)

        logger.info(
            f"🎨 GPT Image 2 T2I: ar={aspect_ratio}, user_res={resolution} -> api_res={gpt_res}, quality={quality}, target={target_w}x{target_h}"
        )

        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_image_gpt_image_2_t2i(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                gpt_resolution=gpt_res,
                quality=quality,
                target_width=target_w,
                target_height=target_h,
            )

        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.GPT_IMAGE_2,
            request_func=_make_request,
        )

        if result.success:
            cost = ToolService.calculate_cost(
                ToolType.GPT_IMAGE_2,
                gpt_image_resolution=gpt_res,
                gpt_image_quality=quality,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.GPT_IMAGE_2_T2I.value, tool_type=ToolType.GPT_IMAGE_2)
            data = result.model_dump()
            data.update(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                model=ToolType.GPT_IMAGE_2.value,
                billing_cost=cost,
            )
            return ImageGenerationResult(**data)
        return result
    except Exception as e:
        logger.error(f"❌ GPT Image 2 T2I 异常: {str(e)}")
        return ImageGenerationResult.error_result(
            error_message=f"GPT Image 2 T2I 异常: {str(e)}",
            provider=ToolProvider.WAVESPEED.value,
            generated_prompt=prompt,
            model=ToolType.GPT_IMAGE_2.value,
            raw_error_msg=str(e),
        )


class GptImage2EditInput(BaseModel):
    """Input schema for GPT Image 2 edit."""
    prompt: str = Field(description="Editing instruction describing the desired changes.")
    images: List[str] = Field(description="List of input image URLs for editing.")
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.GPT_IMAGE_2_I2I, args_schema=GptImage2EditInput)
@traceable(run_type="llm")
async def edit_image_with_wavespeed_gpt_image_2(
    prompt: str,
    images: List[str],
    runtime: ToolRuntime[ImageGenerationContext],
) -> ImageGenerationResult:
    """OpenAI GPT Image 2 image editing (via WaveSpeed). Natural-language edits with one or more reference images."""
    try:
        from ...models.tool_enums import DefaultValues

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.IMAGE_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.IMAGE_RESOLUTION.value
        gpt_res, quality = gpt_image_2_api_resolution_and_quality(resolution, aspect_ratio)

        if runtime.context.reference_image_urls:
            final_images = runtime.context.reference_image_urls
        else:
            final_images = images

        from .ref_utils import truncate_reference_urls_for_model
        truncated = truncate_reference_urls_for_model(final_images, ToolType.GPT_IMAGE_2)
        final_images = truncated if truncated is not None else final_images

        try:
            res_enum = Resolution(resolution) if isinstance(resolution, str) else resolution
            ar_enum = AspectRatio(aspect_ratio) if isinstance(aspect_ratio, str) else aspect_ratio
            target = TARGET_PIXELS.get((res_enum, ar_enum))
        except (ValueError, TypeError):
            target = None
        target_w, target_h = (target[0], target[1]) if target else (None, None)

        if not final_images:
            raise ValueError("至少需要提供一张输入图片")

        logger.info(
            f"🖼️ GPT Image 2 Edit: {len(final_images)} refs, ar={aspect_ratio}, user_res={resolution} -> api_res={gpt_res}"
        )

        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.edit_image_gpt_image_2(
                prompt=prompt,
                images=final_images,
                aspect_ratio=aspect_ratio,
                gpt_resolution=gpt_res,
                quality=quality,
                target_width=target_w,
                target_height=target_h,
            )

        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.GPT_IMAGE_2,
            request_func=_make_request,
        )

        if result.success:
            cost = ToolService.calculate_cost(
                ToolType.GPT_IMAGE_2,
                gpt_image_resolution=gpt_res,
                gpt_image_quality=quality,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.GPT_IMAGE_2_I2I.value, tool_type=ToolType.GPT_IMAGE_2)
            data = result.model_dump()
            data.update(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                model=ToolType.GPT_IMAGE_2.value,
                billing_cost=cost,
            )
            return ImageGenerationResult(**data)
        return result
    except Exception as e:
        logger.error(f"❌ GPT Image 2 Edit 异常: {str(e)}")
        refs = images
        try:
            refs = final_images
        except NameError:
            pass
        return ImageGenerationResult.error_result(
            error_message=f"GPT Image 2 Edit 异常: {str(e)}",
            provider=ToolProvider.WAVESPEED.value,
            generated_prompt=prompt,
            reference_image_urls=refs,
            model=ToolType.GPT_IMAGE_2.value,
            raw_error_msg=str(e),
        )
