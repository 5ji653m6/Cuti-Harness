"""
Kling v3.0 Std image-to-video tool (via the WaveSpeed API)
duration 3-15s, cost $0.90/5s, sound 1.5x. Return fields align with Seedance, for easy persistence and regenerate.
"""
import logging
from typing import Optional, Annotated, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.tool_enums import ToolMode, Resolution
    from ...models.user_options import UserOption
    from ...services.tool_service import ToolInfo
from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime
from langsmith import traceable

from ...llm.wavespeed_service import get_wavespeed_service, WaveSpeedService
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import ToolType, ToolProvider, ToolCategory, ToolName
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)

wavespeed_service = get_wavespeed_service()

# Cost: Base $0.90 per 5s, sound enabled = 1.5x
KLING_V3_MODEL = "kling-v3.0-std"


class KlingVideoInput(BaseModel):
    """Input schema for Kling v3.0 Std image-to-video generation."""
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
    negative_prompt: Optional[str] = Field(
        default=None,
        description="Negative prompt for generation."
    )
    cfg_scale: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Flexibility in generation; higher = stronger relevance to prompt. Default 0.5."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.KLING_V3, args_schema=KlingVideoInput)
async def generate_video_with_wavespeed_kling(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    negative_prompt: Optional[str] = None,
    cfg_scale: float = 0.5,
) -> VideoGenerationResult:
    """Generate video from a keyframe image using Kling v3.0 Std (via WaveSpeed API).

    Duration 3-15s. Cost: $0.90 per 5s; with sound 1.5x. Result fields align with DB/regenerate (video_url, duration, model, aspect_ratio).
    """
    try:
        from ...models.tool_enums import DefaultValues
        from ...services.tool_service import ToolService

        from ...models.tool_enums import TARGET_PIXELS, Resolution

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        final_start_image_url = runtime.context.start_image_url if runtime.context.start_image_url else start_image_url
        duration = runtime.context.duration if runtime.context.duration else duration
        duration = max(3, min(15, duration))
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        res_enum = Resolution(resolution)
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        logger.info("🎥 Kling v3 视频生成开始")
        logger.info(f"🎥 提示词: {i2v_prompt[:100]}...")
        logger.info(f"🎥 起始图: {final_start_image_url}, 时长: {duration}s, cfg_scale: {cfg_scale}")

        async def _make_wavespeed_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_kling_v3_video(
                image=final_start_image_url,
                prompt=i2v_prompt,
                duration=duration,
                cfg_scale=cfg_scale,
                negative_prompt=negative_prompt,
                end_image=runtime.context.end_image_url if runtime.context.end_image_url else None,
                sound=False,
                target_width=target_w,
                target_height=target_h,
            )

        tool_type = ToolType.KLING_V3_STD
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=tool_type,
            request_func=_make_wavespeed_request
        )

        if result.success:
            # fill in model / aspect_ratio / resolution, for persistence and regenerate
            result = result.model_copy(update={
                "aspect_ratio": aspect_ratio,
                "model": KLING_V3_MODEL,
                "resolution": runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value,
            })
            logger.info(f"✅ Kling v3 视频生成成功: {result.video_url}")
            cost = ToolService.calculate_cost(
                cost_type=tool_type,
                duration=duration,
                sound=False,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Kling v3 视频成本: ${cost:.6f} ({duration}s)")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.KLING_V3.value, tool_type=tool_type)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        logger.error(f"❌ Kling v3 视频生成失败: {result.message}")
        return result
    except Exception as e:
        logger.error(f"❌ Kling v3 视频生成异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )
