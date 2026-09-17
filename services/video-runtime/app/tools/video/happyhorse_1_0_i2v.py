"""
Alibaba HappyHorse 1.0 image-to-video tool (via the WaveSpeed API)
720p/1080p, duration 3-15 seconds. No end frame, no aspect_ratio parameter; 480p is produced by a 720p request + ensure_on_s3 alignment.
"""
import logging
import random
from typing import Optional, Annotated, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.tool_enums import ToolMode, Resolution
    from ...models.user_options import UserOption
    from ...services.tool_service import ToolInfo
from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from ...llm.wavespeed_service import WaveSpeedService
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import ToolType, ToolProvider, ToolName
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)

HAPPYHORSE_1_0_MODEL = "happyhorse-1.0-i2v"


class HappyHorse10VideoInput(BaseModel):
    """Input schema for Alibaba HappyHorse 1.0 image-to-video generation."""
    i2v_prompt: str = Field(
        description="Motion description prompt for image-to-video. Describe actions, changes, and camera movements."
    )
    start_image_url: str = Field(
        description="Starting image URL (first frame). HTTPS or local path (local files uploaded to S3). Image min 300px, aspect 1:2.5~2.5:1."
    )
    duration: int = Field(
        default=5,
        description="Video duration in seconds. Recommended range: 3-15."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.HAPPYHORSE_1_0_I2V, args_schema=HappyHorse10VideoInput)
async def generate_video_with_wavespeed_happyhorse_1_0_i2v(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
) -> VideoGenerationResult:
    """Generate video from a keyframe image using Alibaba HappyHorse 1.0 (via WaveSpeed API).

    Resolution 720p or 1080p only (480p via 720p downscale). Duration 3-15s. Cost: $0.70/5s (720p), $1.40/5s (1080p).
    """
    try:
        from ...models.tool_enums import DefaultValues, Resolution, TARGET_PIXELS
        from ...services.tool_service import ToolService

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        final_start_image_url = runtime.context.start_image_url if runtime.context.start_image_url else start_image_url
        duration = runtime.context.duration if runtime.context.duration else duration
        duration = max(3, min(15, duration))
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        user_res_enum = Resolution(resolution)
        api_res_enum = user_res_enum if user_res_enum in (Resolution.P720, Resolution.P1080) else Resolution.P720
        resolution = api_res_enum.value
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((user_res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        seed = random.randint(0, 2147483647)

        logger.info("🎥 HappyHorse 1.0 视频生成开始")
        logger.info(f"🎥 提示词: {i2v_prompt[:100]}...")
        logger.info(f"🎥 起始图: {final_start_image_url}, 时长: {duration}s, 分辨率: {resolution}")

        async def _make_wavespeed_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_happyhorse_1_0_i2v(
                image=final_start_image_url,
                prompt=i2v_prompt,
                duration=duration,
                resolution=resolution,
                seed=seed,
                target_width=target_w,
                target_height=target_h,
            )

        tool_type = ToolType.HAPPYHORSE_1_0_I2V
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=tool_type,
            request_func=_make_wavespeed_request
        )

        if result.success:
            result = result.model_copy(update={
                "aspect_ratio": aspect_ratio,
                "model": HAPPYHORSE_1_0_MODEL,
                "resolution": user_res_enum.value,
            })
            logger.info(f"✅ HappyHorse 1.0 视频生成成功: {result.video_url}")
            cost = ToolService.calculate_cost(
                cost_type=tool_type,
                duration=duration,
                resolution=api_res_enum,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 HappyHorse 1.0 视频成本: ${cost:.6f} ({duration}s, {resolution})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.HAPPYHORSE_1_0_I2V.value, tool_type=tool_type)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        logger.error(f"❌ HappyHorse 1.0 视频生成失败: {result.message}")
        return result
    except Exception as e:
        logger.error(f"❌ HappyHorse 1.0 视频生成异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )
