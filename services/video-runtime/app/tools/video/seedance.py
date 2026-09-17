"""
ByteDance Seedance video-generation tool (via the WaveSpeed API)
"""
import logging
import random
from typing import Optional, Annotated, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.tool_enums import ToolMode
    from ...models.user_options import UserOption
    from ...services.tool_service import ToolInfo
from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime
from langsmith import traceable

from ...llm.wavespeed_service import get_wavespeed_service, WaveSpeedService
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import Resolution, ToolName
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)

# global service instance
wavespeed_service = get_wavespeed_service()


class SeedanceVideoInput(BaseModel):
    """Input schema for ByteDance Seedance video generation."""
    i2v_prompt: str = Field(
        description="Motion description prompt for image-to-video generation. Describe actions, changes, and camera movements in detail. Must be under 800 characters (API limit: 1000 characters)."
    )
    start_image_url: str = Field(
        description="Starting image URL that serves as the first frame of the video. Supports HTTPS URLs or local file paths (local files are automatically uploaded to S3)."
    )
    duration: int = Field(
        default=5,
        description="Video duration in seconds. Recommended range: 2-12 seconds."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.SEEDANCE_V1, args_schema=SeedanceVideoInput)
async def generate_video_with_wavespeed_seedance(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    end_image_url: Optional[str] = None
) -> VideoGenerationResult:
    """Generate high-quality video clips from keyframe images using ByteDance Seedance (via WaveSpeed API).

    This tool creates professional video segments based on starting images and motion descriptions.
    Perfect for image-to-video generation with detailed motion control.

    Uses ByteDance Seedance Pro Fast model for standard generation, or Seedance Lite for start-end frame generation.
    """
    try:
        # get aspect_ratio and resolution from runtime.context (using enums)
        from ...models.tool_enums import DefaultValues, TARGET_PIXELS, Resolution, AspectRatio

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        duration = max(2, min(12, duration))  # API limit: 2-12s
        res_enum = Resolution(resolution)
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        # 🎯 prefer start_image_url and end_image_url from runtime.context (code-level passing is more accurate)
        # use them if present in runtime.context; otherwise use the LLM-passed arguments
        final_start_image_url = runtime.context.start_image_url if runtime.context.start_image_url else start_image_url
        final_end_image_url = runtime.context.end_image_url if runtime.context.end_image_url else end_image_url

        if runtime.context.start_image_url:
            logger.info(f"🎯 使用 runtime.context 中的 start_image_url（代码层面传入）")
        if runtime.context.end_image_url:
            logger.info(f"🎯 使用 runtime.context 中的 end_image_url（代码层面传入）")

        # generate a random seed (0 to 2147483647)
        seed = random.randint(0, 2147483647)

        logger.info(f"🎥 ByteDance Seedance 视频生成开始")
        logger.info(f"🎥 使用提示词: {i2v_prompt[:100]}...")
        logger.info(f"🎥 起始图片: {final_start_image_url}")
        logger.info(f"🎥 视频时长: {duration}")
        logger.info(f"🎥 宽高比: {aspect_ratio}, 分辨率: {resolution} (来源: runtime.context)")
        logger.info(f"🎥 随机种子: {seed}")

        if final_end_image_url:
            logger.info(f"🔗 检测到 end_image_url，将使用 Seedance Lite 模型支持首尾帧生成")
            logger.info(f"🔗 尾帧图片: {final_end_image_url}")

        # define the actual request function (takes api_key as the first parameter)
        async def _make_wavespeed_request(api_key: str):
            """The actual WaveSpeed API call."""
            wavespeed_service = WaveSpeedService()
            wavespeed_service.api_key = api_key
            return await wavespeed_service.generate_seedance_video(
                image=final_start_image_url,
                prompt=i2v_prompt,
                camera_fixed=False,
                duration=duration,
                resolution=resolution,
                seed=seed,
                end_image=final_end_image_url,
                target_width=target_w,
                target_height=target_h,
            )

        # use the account router
        from ...models.tool_enums import ToolProvider, ToolType
        from ...services.tool_service import get_seedance_tool_type
        router = await get_account_router()
        resolution_enum = res_enum
        tool_type = get_seedance_tool_type(resolution_enum, bool(final_end_image_url))
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=tool_type,
            request_func=_make_wavespeed_request
        )

        if result.success:
            # fill in model / aspect_ratio / resolution, for persistence and regenerate
            result = result.model_copy(update={
                "model": tool_type.value,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
            })
            logger.info(f"✅ ByteDance Seedance 视频生成成功: {result.video_url}")

            # ⭐ compute cost using the unified calculate_cost method
            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(
                cost_type=tool_type,
                duration=duration,
                resolution=resolution_enum
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Seedance 视频生成成本: ${cost:.6f} ({duration}s, {resolution})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.SEEDANCE_V1.value, tool_type=tool_type)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        else:
            logger.error(f"❌ ByteDance Seedance 视频生成失败: {result.message}")
            return result

    except Exception as e:
        logger.error(f"❌ ByteDance Seedance 视频生成异常: {str(e)}")
        result = VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )
        return result


class SeedanceV15VideoInput(BaseModel):
    """Input schema for ByteDance Seedance v1.5 Pro (image-to-video-fast)."""
    i2v_prompt: str = Field(
        description="Motion description prompt for image-to-video generation. Describe actions, changes, and camera movements. Must be under 800 characters."
    )
    start_image_url: str = Field(
        description="Starting image URL for the first frame of the video. HTTPS URLs or local file paths (local files are uploaded to S3)."
    )
    duration: int = Field(
        default=5,
        description="Video duration in seconds. Recommended range: 2-12 seconds."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.SEEDANCE_V1_5, args_schema=SeedanceV15VideoInput)
async def generate_video_with_wavespeed_seedance_v1_5(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5
) -> VideoGenerationResult:
    """Generate video using ByteDance Seedance v1.5 Pro (image-to-video-fast) via WaveSpeed API.
    Supports 720p/1080p, no end-frame; audio generation is off by default.
    """
    try:
        from ...models.tool_enums import DefaultValues, ToolProvider, ToolType, Resolution, TARGET_PIXELS
        from ...services.tool_service import ToolService

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        user_res_enum = Resolution(resolution)
        api_res_enum = user_res_enum if user_res_enum in (Resolution.P720, Resolution.P1080) else Resolution.P720
        resolution = api_res_enum.value
        duration = max(2, min(12, duration))  # API limit: 2-12s
        final_start = runtime.context.start_image_url or start_image_url
        seed = random.randint(0, 2147483647)
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((user_res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_seedance_v1_5_video(
                image=final_start,
                prompt=i2v_prompt,
                camera_fixed=False,
                duration=duration,
                resolution=resolution,
                seed=seed,
                target_width=target_w,
                target_height=target_h,
            )

        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.SEEDANCE_V1_5_PRO_FAST,
            request_func=_make_request
        )
        if result.success:
            # persistence/regenerate uses the user-selected resolution (user_res_enum); billing uses the actual requested API tier (720p/1080p)
            result = result.model_copy(update={
                "model": ToolType.SEEDANCE_V1_5_PRO_FAST.value,
                "aspect_ratio": aspect_ratio,
                "resolution": user_res_enum.value,
            })
            cost = ToolService.calculate_cost(
                cost_type=ToolType.SEEDANCE_V1_5_PRO_FAST,
                duration=duration,
                resolution=api_res_enum,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Seedance v1.5 视频成本: ${cost:.6f} ({duration}s, {resolution})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.SEEDANCE_V1_5.value, tool_type=ToolType.SEEDANCE_V1_5_PRO_FAST)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        return result
    except Exception as e:
        logger.error(f"❌ Seedance v1.5 视频生成异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )
