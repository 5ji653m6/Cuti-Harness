"""
ByteDance Seedance 2.0 Text-to-Video Turbo（WaveSpeed API）

HD turbo pure text-to-video: 720p / 1080p only (480p uses 720p), near-480p speed with HD output.
Supports optional reference_images / reference_videos / reference_audios as style/character/audio references.
Resolution / ratio come from runtime.context; generate_audio defaults to True (the API default).
"""
import logging
import random
from typing import Optional, Annotated, Any, List

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


class Seedance2T2vTurboVideoInput(BaseModel):
    """Input schema for Seedance 2.0 Text-to-Video Turbo."""
    t2v_prompt: str = Field(
        description="Scene, action, camera and mood description for text-to-video generation."
    )
    duration: int = Field(
        default=5,
        description="Video duration in seconds. API range: 4–15."
    )
    reference_images: Optional[List[str]] = Field(
        default=None,
        description="Optional reference image URLs to guide visual style, characters, or scene composition."
    )
    reference_videos: Optional[List[str]] = Field(
        default=None,
        description="Optional reference video URLs (total length must not exceed 15 seconds)."
    )
    reference_audios: Optional[List[str]] = Field(
        default=None,
        description="Optional reference audio URLs (total length must not exceed 15 seconds)."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.SEEDANCE_2_T2V_TURBO, args_schema=Seedance2T2vTurboVideoInput)
async def generate_video_with_wavespeed_seedance_2_t2v_turbo(
    t2v_prompt: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    reference_images: Optional[List[str]] = None,
    reference_videos: Optional[List[str]] = None,
    reference_audios: Optional[List[str]] = None,
) -> VideoGenerationResult:
    """Generate video with ByteDance Seedance 2.0 Text-to-Video Turbo (WaveSpeed). 720p/1080p API (480p via downscale); native audio (generate_audio=True); optional reference images/videos/audios; HD output at near-480p speed."""
    try:
        from ...models.tool_enums import DefaultValues, ToolProvider, ToolType, TARGET_PIXELS
        from ...services.tool_service import ToolService

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        user_res_enum = Resolution(resolution)
        api_res_enum = user_res_enum if user_res_enum in (Resolution.P720, Resolution.P1080) else Resolution.P720
        resolution_api = api_res_enum.value
        duration = max(4, min(15, duration))
        seed = random.randint(0, 2147483647)
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((user_res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)
        ref_images = runtime.context.reference_images or reference_images
        ref_videos = runtime.context.reference_videos or reference_videos
        ref_audios = runtime.context.reference_audios or reference_audios

        async def _make_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_seedance_2_t2v_turbo(
                prompt=t2v_prompt,
                duration=duration,
                resolution=resolution_api,
                aspect_ratio=aspect_ratio,
                reference_images=ref_images,
                reference_videos=ref_videos,
                reference_audios=ref_audios,
                seed=seed,
                target_width=target_w,
                target_height=target_h,
            )

        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=ToolType.SEEDANCE_2_T2V_TURBO,
            request_func=_make_request
        )
        if result.success:
            result = result.model_copy(update={
                "model": ToolType.SEEDANCE_2_T2V_TURBO.value,
                "aspect_ratio": aspect_ratio,
                "resolution": user_res_enum.value,
            })
            cost = ToolService.calculate_cost(
                cost_type=ToolType.SEEDANCE_2_T2V_TURBO,
                duration=duration,
                resolution=api_res_enum,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Seedance 2.0 T2V Turbo 成本: ${cost:.6f} ({duration}s, {resolution_api})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.SEEDANCE_2_T2V_TURBO.value, tool_type=ToolType.SEEDANCE_2_T2V_TURBO)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        return result
    except Exception as e:
        logger.error(f"❌ Seedance 2.0 T2V Turbo 异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )
