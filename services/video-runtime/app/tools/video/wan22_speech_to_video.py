"""
WaveSpeed WAN 2.2 Speech-to-Video - lip-sync shot: audio + image -> video (lip-sync/performance follows the speech).

API: POST wavespeed-ai/wan-2.2/speech-to-video; params include image, audio, resolution (official 480p/720p), optional prompt, seed.
Output duration follows the audio; billed at the WaveSpeed list price $0.15/5s (480p), $0.30/5s (720p). capabilities exposes only 480p/720p; if context mistakenly passes 1080p, the API is called as 720p and the ensure target pixels use the 720p tier, to avoid upscaling.
"""
import logging
from typing import Optional, Annotated, Any

from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from ...llm.wavespeed_service import get_wavespeed_service
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import ToolName, ToolType, ToolProvider, DefaultValues, Resolution, AspectRatio, TARGET_PIXELS
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)


def _api_resolution_from_product(resolution_value: str) -> str:
    """WAN 2.2 S2V is 480p/720p only; non-tier values like 1080p call the API as 720p (fallback, consistent with capabilities not offering 1080p)."""
    if resolution_value == Resolution.P1080.value:
        return Resolution.P720.value
    if resolution_value in (Resolution.P480.value, Resolution.P720.value):
        return resolution_value
    return Resolution.P720.value


class Wan22SpeechToVideoInput(BaseModel):
    """WAN 2.2 Speech-to-Video: like Kling Avatar, audio_url is read from context."""
    i2v_prompt: str = Field(
        description="Style/motion hint for logging; optional prompt sent to API when non-empty."
    )
    start_image_url: str = Field(
        description="Portrait or character image URL (required)."
    )
    duration: int = Field(
        default=5,
        description="Segment duration in seconds (for billing). Actual video length follows audio.",
    )
    audio_url: Optional[str] = Field(
        default=None,
        description="Audio URL; when provided via context, overrides this.",
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


@tool(ToolName.LIPSYNC_WAN_22_SPEECH_TO_VIDEO, args_schema=Wan22SpeechToVideoInput)
async def generate_video_with_wavespeed_wan22_speech_to_video(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    audio_url: Optional[str] = None,
) -> VideoGenerationResult:
    """Generate lipsync-style video using WaveSpeed WAN 2.2 Speech-to-Video (image + audio)."""
    try:
        original_res = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        api_res = _api_resolution_from_product(original_res)
        ar_ctx = runtime.context.aspect_ratio if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO
        try:
            res_enum = Resolution(original_res)
        except ValueError:
            res_enum = DefaultValues.VIDEO_RESOLUTION
        if res_enum == Resolution.P1080:
            res_enum = Resolution.P720
        normalized_resolution = res_enum.value
        tw, th = TARGET_PIXELS.get((res_enum, ar_ctx), (1280, 720))

        final_start_image_url = runtime.context.start_image_url if runtime.context.start_image_url else start_image_url
        final_audio_url = runtime.context.audio_url if runtime.context.audio_url else audio_url
        duration_sec = runtime.context.duration if runtime.context.duration else duration

        if not final_audio_url:
            logger.error("❌ WAN 2.2 Speech-to-Video 需要 audio_url（context 或参数）")
            return VideoGenerationResult.error_result(
                error_message="WAN 2.2 Speech-to-Video requires audio_url.",
                provider=VideoProvider.WAVESPEED.value,
            )
        if not final_start_image_url:
            logger.error("❌ WAN 2.2 Speech-to-Video 需要 start_image_url")
            return VideoGenerationResult.error_result(
                error_message="WAN 2.2 Speech-to-Video requires start_image_url.",
                provider=VideoProvider.WAVESPEED.value,
            )

        prompt = (i2v_prompt or "").strip() or None
        logger.info(
            "🎭 WAN 2.2 S2V 开始: product_res=%s api_res=%s ensure_target=%s×%s image=%s prompt=%s",
            original_res,
            api_res,
            tw,
            th,
            bool(final_start_image_url),
            bool(prompt),
        )

        async def _make_request(api_key: str):
            svc = get_wavespeed_service()
            svc.api_key = api_key
            request_id = await svc.create_wan22_speech_to_video_task(
                audio_url=final_audio_url,
                image_url=final_start_image_url,
                resolution=api_res,
                prompt=prompt,
            )
            return await svc.poll_wan22_speech_to_video_until_complete(
                request_id, final_audio_url, target_width=tw, target_height=th
            )

        tool_type = ToolType.WAN_2_2_SPEECH_TO_VIDEO
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=tool_type,
            request_func=_make_request,
        )

        if result.success:
            result = result.model_copy(update={
                "model": tool_type.value,
                "resolution": normalized_resolution,
            })
            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(
                cost_type=tool_type,
                duration=duration_sec,
                resolution=normalized_resolution,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 WAN 2.2 S2V 成本: ${cost:.6f} (billable from {duration_sec}s, api_res={api_res})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.LIPSYNC_WAN_22_SPEECH_TO_VIDEO.value, tool_type=tool_type)
            result = result.model_copy(update={"billing_cost": cost})
            logger.info(f"✅ WAN 2.2 S2V 成功: {result.video_url}")
            return result
        logger.error(f"❌ WAN 2.2 S2V 失败: {result.message}")
        return result
    except Exception as e:
        logger.error(f"❌ WAN 2.2 S2V 异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value,
        )
