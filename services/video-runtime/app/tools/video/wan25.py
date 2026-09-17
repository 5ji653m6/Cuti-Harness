"""
Alibaba Wan 2.5 image-to-video tool (via the WaveSpeed API)
Supports optional audio sync, no end frame (end image).
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
from langsmith import traceable

from ...llm.wavespeed_service import get_wavespeed_service, WaveSpeedService
from ...models.image_result import VideoGenerationResult, VideoProvider
from ...models.tool_enums import ToolName
from ...services.account.account_router import get_account_router
from ..context_schemas import VideoGenerationContext

logger = logging.getLogger(__name__)

wavespeed_service = get_wavespeed_service()


class Wan25VideoInput(BaseModel):
    """Input schema for Alibaba Wan 2.5 image-to-video generation."""
    i2v_prompt: str = Field(
        description="Motion description prompt for image-to-video. Describe actions, changes, and camera movements. Must be under 800 characters."
    )
    start_image_url: str = Field(
        description="Starting image URL (first frame). Supports HTTPS URLs or local file paths (local files are uploaded to S3)."
    )
    duration: int = Field(
        default=5,
        description="Video duration in seconds. Recommended range: 3-10. If audio_url is provided, duration is overridden by audio duration."
    )
    audio_url: Optional[str] = Field(
        default=None,
        description="Optional audio URL (WAV/MP3, 3-30s, ≤15MB) to sync with the generated video."
    )
    runtime: Annotated[Any, SkipValidation, SkipJsonSchema()] = Field(
        default=None,
        description="Provider runtime context (internal use only)"
    )


@tool(ToolName.WAN_2_5, args_schema=Wan25VideoInput)
async def generate_video_with_wavespeed_wan25(
    i2v_prompt: str,
    start_image_url: str,
    runtime: ToolRuntime[VideoGenerationContext],
    duration: int = 5,
    audio_url: Optional[str] = None
) -> VideoGenerationResult:
    """Generate video from a keyframe image using Alibaba Wan 2.5 (via WaveSpeed API).

    Supports optional audio sync; no end-frame image. Perfect for image-to-video with
    optional soundtrack. Resolution pricing: 480p $0.05/s, 720p $0.10/s, 1080p $0.15/s.
    """
    try:
        from ...models.tool_enums import DefaultValues, ToolProvider, ToolType, Resolution, TARGET_PIXELS

        aspect_ratio = runtime.context.aspect_ratio.value if runtime.context.aspect_ratio else DefaultValues.VIDEO_ASPECT_RATIO.value
        resolution = runtime.context.resolution.value if runtime.context.resolution else DefaultValues.VIDEO_RESOLUTION.value

        res_enum = Resolution(resolution)
        ar_enum = runtime.context.aspect_ratio or DefaultValues.VIDEO_ASPECT_RATIO
        target = TARGET_PIXELS.get((res_enum, ar_enum))
        target_w, target_h = (target[0], target[1]) if target else (None, None)

        final_start_image_url = runtime.context.start_image_url if runtime.context.start_image_url else start_image_url
        # audio_url / duration: prefer the ones passed via context (already determined at the system level), otherwise the LLM-passed ones
        final_audio_url = runtime.context.audio_url if runtime.context.audio_url else audio_url
        duration = runtime.context.duration if runtime.context.duration else duration
        duration = max(3, min(10, duration))  # tool limit: 3-10s

        seed = random.randint(0, 2147483647)

        logger.info("🎥 Alibaba Wan 2.5 视频生成开始")
        logger.info(f"🎥 提示词: {i2v_prompt[:100]}...")
        logger.info(f"🎥 起始图: {final_start_image_url}, 时长: {duration}s, 分辨率: {resolution}")
        if final_audio_url:
            logger.info(f"🎥 音频: {final_audio_url}")

        async def _make_wavespeed_request(api_key: str):
            svc = WaveSpeedService()
            svc.api_key = api_key
            return await svc.generate_wan25_video(
                image=final_start_image_url,
                prompt=i2v_prompt,
                duration=duration,
                resolution=resolution,
                seed=seed,
                enable_prompt_expansion=True,
                audio_url=final_audio_url,
                target_width=target_w,
                target_height=target_h,
            )

        resolution_enum = Resolution(resolution)
        tool_type = ToolType.WAN_2_5_I2V
        router = await get_account_router()
        result = await router.route_tool_request(
            provider=ToolProvider.WAVESPEED,
            tool_type=tool_type,
            request_func=_make_wavespeed_request
        )

        if result.success:
            # fill in model / aspect_ratio, for persistence and regenerate
            result = result.model_copy(update={
                "model": ToolType.WAN_2_5_I2V.value,
                "aspect_ratio": aspect_ratio,
            })
            # lipsync: download the real audio URL and ffprobe for the actual duration, then trim the video (same logic as merge_and_trim_lipsync_videos)
            if final_audio_url and result.video_url:
                try:
                    from ...utils.video_utils import get_audio_duration_from_url, trim_video_to_duration
                    audio_dur = await get_audio_duration_from_url(final_audio_url)  # real URL -> local probe, not the DB value
                    if audio_dur is not None and audio_dur > 0:
                        trimmed_url = await trim_video_to_duration(result.video_url, float(audio_dur))
                        result = result.model_copy(update={"video_url": trimmed_url})
                        logger.info(f"🎭 Wan 2.5 已按音频时长截断至 {audio_dur:.2f}s")
                except Exception as trim_err:
                    logger.warning("🎭 lipsync 截断失败，使用原视频: %s", trim_err)
            # no audio: the wan25 endpoint may still return a video with an audio track; strip it so video-driven can add BGM only
            elif result.video_url:
                try:
                    from ...utils.video_utils import strip_audio_from_video
                    muted_url = await strip_audio_from_video(result.video_url)
                    result = result.model_copy(update={"video_url": muted_url})
                    logger.info("🔇 Wan 2.5 无音频输入，已去音轨生成静音视频")
                except Exception as strip_err:
                    logger.warning("🔇 去音轨失败，使用原视频: %s", strip_err)
            logger.info(f"✅ Wan 2.5 视频生成成功: {result.video_url}")
            from ...services.tool_service import ToolService
            cost = ToolService.calculate_cost(cost_type=tool_type, duration=duration, resolution=resolution_enum)
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Wan 2.5 视频成本: ${cost:.6f} ({duration}s, {resolution})")
                cb = ToolService.get_credit_callback(getattr(runtime, "config", None) if runtime else None)
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.WAN_2_5.value, tool_type=tool_type)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        logger.error(f"❌ Wan 2.5 视频生成失败: {result.message}")
        return result
    except Exception as e:
        logger.error(f"❌ Wan 2.5 视频生成异常: {str(e)}")
        return VideoGenerationResult.error_result(
            error_message=f"Exception occurred: {str(e)}",
            provider=VideoProvider.WAVESPEED.value
        )


def get_wan25_tools(
    mode: Optional["ToolMode"] = None,
    user_option: Optional["UserOption"] = None,
    resolution: Optional["Resolution"] = None
) -> List["ToolInfo"]:
    """Get the Alibaba Wan 2.5 image-to-video tool list (single model, resolution is a parameter, no end frame, optional audio)."""
    from ...models.tool_enums import ToolMode, ToolType, ToolProvider, ToolCategory
    from ...services.tool_service import ToolInfo

    tool_type = ToolType.WAN_2_5_I2V

    tool_info = ToolInfo(
        tool=generate_video_with_wavespeed_wan25,
        tool_name=generate_video_with_wavespeed_wan25.name,
        tool_type=tool_type,
        provider=ToolProvider.WAVESPEED,
        category=ToolCategory.VIDEO_GENERATION,
        mode=ToolMode.I2V,
        supports_lipsync=True,
    )
    try:
        if hasattr(tool_info.tool, "metadata"):
            if tool_info.tool.metadata is None:
                tool_info.tool.metadata = {}
            tool_info.tool.metadata.update({
                "tool_type": tool_type.value,
                "provider": ToolProvider.WAVESPEED.value,
                "category": ToolCategory.VIDEO_GENERATION.value
            })
    except Exception as e:
        logger.warning("添加 wan25 tool metadata 失败: %s", e)
    return [tool_info]
