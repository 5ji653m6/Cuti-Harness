"""
OpenAI Sora 2 video-generation toolset
"""
import logging
from typing import Optional, List, Annotated, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.tool_enums import ToolMode
    from ...models.user_options import UserOption
    from ...services.tool_service import ToolInfo
from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool

from ...llm.openai_sora_service import get_openai_sora_service, OpenAISoraService
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...utils.file_utils import convert_image_url, ImageFormat
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext
from ...models.tool_enums import DefaultValues, ToolName
from app.tools.runtime import ToolRuntime
from langsmith import traceable

logger = logging.getLogger(__name__)


# ==================== Duration mapping ====================

_SORA_SUPPORTED_DURATIONS = [4, 8, 12]


def _nearest_sora_duration(duration: int) -> int:
    """Map any duration to the nearest value Sora supports (4, 8, 12)."""
    return min(_SORA_SUPPORTED_DURATIONS, key=lambda x: abs(x - duration))


# ==================== Input Schema ====================


class SoraT2VInput(BaseModel):
    """Input schema for OpenAI Sora text-to-video generation."""
    i2v_prompt: str = Field(
        description="Video description prompt. Describe the scene, actions, camera movements, and visual elements in detail."
    )
    duration: int = Field(
        default=4,
        description="Video duration in seconds. Recommended values: 4, 8, 12 seconds."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


class SoraI2VInput(BaseModel):
    """Input schema for OpenAI Sora image-to-video generation."""
    i2v_prompt: str = Field(
        description="Motion description prompt for image-to-video generation. Describe how the image should animate and what actions should occur."
    )
    start_image_url: str = Field(
        description="Starting image URL that serves as the first frame of the video. Supports HTTPS URLs or local file paths."
    )
    duration: int = Field(
        default=4,
        description="Video duration in seconds. Recommended values: 4, 8, 12 seconds."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


# ==================== Size conversion ====================

from ...models.tool_enums import AspectRatio, Resolution, DefaultValues, TARGET_PIXELS

# Sora only supports the 720p tier (no true 1080p), uniformly using 1280x720 / 720x1280; 1:1 falls back to landscape
_SORA_SIZE_BY_ASPECT_RATIO: dict[AspectRatio, str] = {
    AspectRatio.LANDSCAPE: "1280x720",
    AspectRatio.PORTRAIT: "720x1280",
    AspectRatio.SQUARE: "1280x720",
}


def _parse_aspect_ratio_for_sora(ar: str | None) -> AspectRatio:
    """Convert the frontend/context aspect_ratio string to an AspectRatio enum."""
    s = (ar or "").strip()
    if s == AspectRatio.LANDSCAPE.value:
        return AspectRatio.LANDSCAPE
    if s == AspectRatio.PORTRAIT.value:
        return AspectRatio.PORTRAIT
    if s == AspectRatio.SQUARE.value:
        return AspectRatio.SQUARE
    return DefaultValues.VIDEO_ASPECT_RATIO


def convert_aspect_ratio_and_resolution_to_sora_size(
    aspect_ratio: str | AspectRatio,
    resolution: str | Resolution | None = None,
    model: str | None = None,
) -> str:
    """Convert aspect_ratio to an OpenAI Sora size (WIDTHxHEIGHT). Sora does not support 1080p; uniformly uses the 720p tier."""
    ar_enum = aspect_ratio if isinstance(aspect_ratio, AspectRatio) else _parse_aspect_ratio_for_sora(aspect_ratio)
    return _SORA_SIZE_BY_ASPECT_RATIO.get(ar_enum, "1280x720")


# ==================== Core generation function ====================


async def _generate_video(
    i2v_prompt: str,
    start_image_url: Optional[str] = None,
    duration: int = 4,
    aspect_ratio: str = DefaultValues.VIDEO_ASPECT_RATIO.value,
    resolution: str = DefaultValues.VIDEO_RESOLUTION.value,
    model: str = "sora-2",
    runtime: Optional[Any] = None,
) -> VideoGenerationResult:
    """Core function: generate a video using OpenAI Sora."""
    try:
        size = convert_aspect_ratio_and_resolution_to_sora_size(aspect_ratio)
        res_enum = Resolution(resolution) if resolution else Resolution(DefaultValues.VIDEO_RESOLUTION.value)
        ar_str_to_enum = {"16:9": AspectRatio.LANDSCAPE, "1:1": AspectRatio.SQUARE, "9:16": AspectRatio.PORTRAIT}
        ar_enum = ar_str_to_enum.get((aspect_ratio or "").strip(), DefaultValues.VIDEO_ASPECT_RATIO)
        target = TARGET_PIXELS.get((res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        mode = "I2V" if start_image_url else "T2V"
        logger.info(f"🎬 OpenAI Sora 2 视频生成开始（{mode}模式，模型={model}）")
        logger.info(f"🎬 提示词: {i2v_prompt[:100]}...")
        logger.info(f"🎬 生成设置: duration={duration}s, aspect_ratio={aspect_ratio}, resolution={resolution} -> size={size}")

        seconds = str(duration)

        async def _make_openai_request(api_key: str):
            from openai import AsyncOpenAI
            openai_sora_service = OpenAISoraService()
            openai_sora_service.api_key = api_key
            openai_sora_service.client = AsyncOpenAI(api_key=api_key)
            return await openai_sora_service.generate_video(
                prompt=i2v_prompt,
                input_image=start_image_url,
                model=model,
                size=size,
                seconds=seconds,
                target_width=target_w,
                target_height=target_h,
            )

        from ...models.tool_enums import ToolProvider, ToolType
        router = await get_account_router()
        tool_type = ToolType.SORA_2 if model == "sora-2" else ToolType.SORA_2_PRO
        result = await router.route_tool_request(
            provider=ToolProvider.OPENAI,
            tool_type=tool_type,
            request_func=_make_openai_request
        )

        if result.success:
            logger.info(f"✅ OpenAI Sora 2 视频生成成功: {result.video_url}")
            effective_resolution = (
                "1080p"
                if (model == "sora-2-pro" and (resolution or "").strip().lower() == "1080p")
                else "720p"
            )
            result.resolution = effective_resolution
            result.aspect_ratio = aspect_ratio or None
            result.model = model

            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(
                cost_type=tool_type,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                size=size
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Sora 2 视频生成成本: ${cost:.6f} ({duration}s, {size})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=tool_type.value, tool_type=tool_type)
            result.billing_cost = cost

            return result
        else:
            logger.error(f"❌ OpenAI Sora 2 视频生成失败: {result.message}")
            return result

    except Exception as e:
        logger.error(f"❌ OpenAI Sora 2 视频生成异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"OpenAI Sora 2 视频生成异常: {str(e)}",
            provider=VideoProvider.OPENAI_SORA
        )


# ==================== Shared impl (extract context reading + duration mapping) ====================


def _read_context(runtime: Optional[ToolRuntime[VideoGenerationContext]]):
    """Read aspect_ratio / resolution from runtime.context; returns (aspect_ratio, resolution)."""
    if runtime and runtime.context:
        ar = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        res = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        return ar, res
    return DefaultValues.VIDEO_ASPECT_RATIO.value, DefaultValues.VIDEO_RESOLUTION.value


# ==================== T2V tool ====================


@tool(ToolName.SORA_2_T2V, args_schema=SoraT2VInput)
async def generate_video_with_sora_2_t2v(
    i2v_prompt: str,
    duration: int = 4,
    runtime: ToolRuntime[VideoGenerationContext] = None,
) -> VideoGenerationResult:
    """Generate professional videos from text descriptions using OpenAI Sora 2.

    Creates high-quality videos from detailed text prompts. Perfect for text-to-video generation
    with support for various durations and professional video quality.
    """
    aspect_ratio, resolution = _read_context(runtime)
    duration = _nearest_sora_duration(duration)
    return await _generate_video(i2v_prompt, None, duration, aspect_ratio, resolution, "sora-2", runtime=runtime)


@tool(ToolName.SORA_2_PRO_T2V, args_schema=SoraT2VInput)
async def generate_video_with_sora_2_pro_t2v(
    i2v_prompt: str,
    duration: int = 4,
    runtime: ToolRuntime[VideoGenerationContext] = None,
) -> VideoGenerationResult:
    """Generate professional videos from text descriptions using OpenAI Sora 2 Pro.

    Creates high-quality 1080p videos from detailed text prompts with enhanced quality.
    """
    aspect_ratio, resolution = _read_context(runtime)
    duration = _nearest_sora_duration(duration)
    return await _generate_video(i2v_prompt, None, duration, aspect_ratio, resolution, "sora-2-pro", runtime=runtime)


# ==================== I2V tool ====================


@tool(ToolName.SORA_2_I2V, args_schema=SoraI2VInput)
async def generate_video_with_sora_2_i2v(
    i2v_prompt: str,
    start_image_url: str,
    duration: int = 4,
    runtime: ToolRuntime[VideoGenerationContext] = None,
) -> VideoGenerationResult:
    """Generate dynamic videos from static images using OpenAI Sora 2.

    Animates static images into dynamic video content based on motion descriptions.
    Perfect for image-to-video generation with realistic motion and camera movements.
    """
    aspect_ratio, resolution = _read_context(runtime)
    final_start = (runtime.context.start_image_url or start_image_url) if (runtime and runtime.context) else start_image_url
    duration = _nearest_sora_duration(duration)
    return await _generate_video(i2v_prompt, final_start, duration, aspect_ratio, resolution, "sora-2", runtime=runtime)


@tool(ToolName.SORA_2_PRO_I2V, args_schema=SoraI2VInput)
async def generate_video_with_sora_2_pro_i2v(
    i2v_prompt: str,
    start_image_url: str,
    duration: int = 4,
    runtime: ToolRuntime[VideoGenerationContext] = None,
) -> VideoGenerationResult:
    """Generate dynamic videos from static images using OpenAI Sora 2 Pro.

    Animates static images into dynamic video content with enhanced 1080p quality.
    """
    aspect_ratio, resolution = _read_context(runtime)
    final_start = (runtime.context.start_image_url or start_image_url) if (runtime and runtime.context) else start_image_url
    duration = _nearest_sora_duration(duration)
    return await _generate_video(i2v_prompt, final_start, duration, aspect_ratio, resolution, "sora-2-pro", runtime=runtime)
