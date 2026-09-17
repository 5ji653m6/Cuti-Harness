"""
WaveSpeed LTX 2.3 Lipsync tool (main-flow lip-sync): audio + image -> video.

API: POST wavespeed-ai/ltx-2.3/lipsync, inputs audio (required), image (optional), resolution.
Duration is decided by the audio; billing billable_sec = max(duration_sec, 5), rate by resolution.
"""
import logging
import random
from typing import Optional, Annotated, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.tool_enums import Resolution
from pydantic import BaseModel, Field, SkipValidation
from pydantic.json_schema import SkipJsonSchema
from app.tools.runtime import tool
from app.tools.runtime import ToolRuntime

from ...llm.wavespeed_service import get_wavespeed_service
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import ToolName, ToolType, ToolProvider, DefaultValues, TARGET_PIXELS, AspectRatio
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)

wavespeed_service = get_wavespeed_service()


class LTX23LipsyncInput(BaseModel):
    """LTX 2.3 Lipsync input: same as I2V, audio_url is read from context."""
    i2v_prompt: str = Field(
        description="Motion description prompt (for logging). LTX 2.3 duration is determined by audio."
    )
    start_image_url: str = Field(
        description="Starting image URL (first frame). Optional for API but recommended for lipsync."
    )
    duration: int = Field(
        default=5,
        description="Segment duration in seconds (for cost calculation). Actual video length follows audio."
    )
    audio_url: Optional[str] = Field(
        default=None,
        description="Audio URL. When provided via context, overrides this."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)",
    )


@tool(ToolName.LIPSYNC_LTX23, args_schema=LTX23LipsyncInput)
async def generate_video_with_wavespeed_ltx23_lipsync(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    audio_url: Optional[str] = None,
) -> VideoGenerationResult:
    """Generate lipsync video using WaveSpeed LTX 2.3 (audio + image → video).

    Resolution and audio_url from runtime.context. Duration for billing uses max(actual_sec, 5).
    """
    try:
        from ...models.tool_enums import Resolution

        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value
        res_enum = Resolution(resolution) if resolution in ("480p", "720p", "1080p") else Resolution.P720
        resolution = res_enum.value
        ar_ctx = runtime.context.aspect_ratio if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO
        tw, th = TARGET_PIXELS.get((res_enum, ar_ctx), (1920, 1080))

        final_start_image_url = runtime.context.start_image_url if runtime.context.start_image_url else start_image_url
        final_audio_url = runtime.context.audio_url if runtime.context.audio_url else audio_url
        duration_sec = runtime.context.duration if runtime.context.duration else duration

        if not final_audio_url:
            logger.error("❌ LTX 2.3 Lipsync 需要 audio_url（context 或参数）")
            return VideoGenerationResult.error_result(
                error_message="LTX 2.3 Lipsync requires audio_url.",
                provider=VideoProvider.WAVESPEED.value,
            )

        seed = random.randint(0, 2147483647)
        prompt = (i2v_prompt or "").strip() or None
        logger.info("🎭 LTX 2.3 Lipsync 开始: resolution=%s, image=%s, prompt=%s", resolution, bool(final_start_image_url), bool(prompt))

        async def _make_request(api_key: str):
            svc = get_wavespeed_service()
            svc.api_key = api_key
            request_id = await svc.create_ltx23_lipsync_task(
                audio_url=final_audio_url,
                image_url=final_start_image_url or None,
                resolution=resolution,
                seed=seed,
                prompt=prompt,
            )
            return await svc.poll_ltx23_lipsync_until_complete(
                request_id, final_audio_url, target_width=tw, target_height=th
            )

        tool_type = ToolType.LTX_2_3_LIPSYNC
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=tool_type,
            request_func=_make_request,
        )

        if result.success:
            result = result.model_copy(update={
                "model": tool_type.value,
                "resolution": resolution,
            })
            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(
                cost_type=tool_type,
                duration=duration_sec,
                resolution=res_enum,
            )
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 LTX 2.3 Lipsync 成本: ${cost:.6f} (billable from {duration_sec}s, {resolution})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.LIPSYNC_LTX23.value, tool_type=tool_type)
            result = result.model_copy(update={"billing_cost": cost})
            logger.info(f"✅ LTX 2.3 Lipsync 成功: {result.video_url}")
            return result
        logger.error(f"❌ LTX 2.3 Lipsync 失败: {result.message}")
        return result
    except Exception as e:
        logger.error(f"❌ LTX 2.3 Lipsync 异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value,
        )
