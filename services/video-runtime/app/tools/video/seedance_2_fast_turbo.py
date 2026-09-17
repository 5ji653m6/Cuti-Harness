"""
ByteDance Seedance 2.0 Fast Image-to-Video Turbo（WaveSpeed API）
"""
import logging
import random
from typing import Optional, Annotated, Any

from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from ...llm.wavespeed_service import WaveSpeedService
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import Resolution, ToolName
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)


class Seedance2FastTurboVideoInput(BaseModel):
    """Input schema for Seedance 2.0 Fast Image-to-Video Turbo."""
    i2v_prompt: str = Field(
        description="Motion and scene description for image-to-video. Describe action, camera, and mood."
    )
    start_image_url: str = Field(
        description="First-frame image URL (HTTPS or local path uploaded to S3)."
    )
    duration: int = Field(
        default=5,
        description="Video duration in seconds. API range: 4–15."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.SEEDANCE_2_FAST_I2V_TURBO, args_schema=Seedance2FastTurboVideoInput)
async def generate_video_with_wavespeed_seedance_2_fast_turbo(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    end_image_url: Optional[str] = None,
) -> VideoGenerationResult:
    """Generate video with ByteDance Seedance 2.0 Fast Image-to-Video Turbo (WaveSpeed). 720p/1080p API; 480p via downscale; optional last frame; generate_audio off by default in API."""
    try:
        from ...models.tool_enums import DefaultValues, ToolProvider, ToolType, TARGET_PIXELS
        from ...services.tool_service import ToolService

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        user_res_enum = Resolution(resolution)
        api_res_enum = user_res_enum if user_res_enum in (Resolution.P720, Resolution.P1080) else Resolution.P720
        resolution_api = api_res_enum.value
        duration = max(4, min(15, duration))
        final_start = runtime.context.start_image_url or start_image_url
        final_end = runtime.context.end_image_url if runtime.context.end_image_url else end_image_url
        seed = random.randint(0, 2147483647)
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((user_res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        generate_audio = bool(getattr(runtime.context, "generate_audio", False))

        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_seedance_2_fast_i2v_turbo(
                image=final_start,
                prompt=i2v_prompt,
                duration=duration,
                resolution=resolution_api,
                last_image=final_end,
                aspect_ratio=aspect_ratio,
                seed=seed,
                target_width=target_w,
                target_height=target_h,
                generate_audio=generate_audio,
            )

        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.SEEDANCE_2_FAST_I2V_TURBO,
            request_func=_make_request
        )
        if result.success:
            result = result.model_copy(update={
                "model": ToolType.SEEDANCE_2_FAST_I2V_TURBO.value,
                "aspect_ratio": aspect_ratio,
                "resolution": user_res_enum.value,
            })
            cost = ToolService.calculate_cost(
                cost_type=ToolType.SEEDANCE_2_FAST_I2V_TURBO,
                duration=duration,
                resolution=api_res_enum,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Seedance 2.0 Fast Turbo 成本: ${cost:.6f} ({duration}s, {resolution_api})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.SEEDANCE_2_FAST_I2V_TURBO.value, tool_type=ToolType.SEEDANCE_2_FAST_I2V_TURBO)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        return result
    except Exception as e:
        logger.error(f"❌ Seedance 2.0 Fast Turbo 异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )
