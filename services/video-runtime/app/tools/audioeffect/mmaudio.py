"""
MMAudio V2 sound-effect generation tool (WaveSpeed AI model)
"""
import logging
from typing import List, TYPE_CHECKING
from app.tools.runtime import tool
from langsmith import traceable

if TYPE_CHECKING:
    from ...services.tool_service import ToolInfo

from ...llm.wavespeed_service import get_wavespeed_service
from ...models.image_result import AudioGenerationResult, AudioProvider
from ...models.tool_enums import ToolName, ToolType
from ...services.tool_service import ToolService

logger = logging.getLogger(__name__)

# global service instance
wavespeed_service = get_wavespeed_service()


@tool(ToolName.MMAUDIO)
@traceable(run_type='llm')
async def generate_audio_with_wavespeed(
    video_url: str,
    prompt: str,
    duration: float = 8.0
) -> AudioGenerationResult:
    """Professional MMAudio V2 sound-effect generation tool (WaveSpeed AI model).

    A high-quality AI sound-effect tool that uses WaveSpeed AI's MMAudio V2 model to generate matching sound effects for videos.
    It generates realistic sound effects from the video content and a text description, perfectly matching the video's visuals.

    🎯 Important notes:
    1. Requires a video URL as input; the tool analyzes the video content
    2. The prompt should describe the desired sound-effect type and mood
    3. The generated sound effects are synced with the video content

    Parameters:
    - video_url: the input video's URL (required)
    - prompt: sound-effect description, describing the desired type, mood, and characteristics
      e.g. "Shot in extreme macro perspective, a glowing, heat-rippled, and semi-translucent molten lava cube..."
    - duration: sound-effect duration (seconds), default 8.0s, range 1-30s

    Sound-effect type examples:
    - natural: wind, rain, waves, birdsong, etc.
    - mechanical: engine sounds, metal collisions, running electronics, etc.
    - ambient: city noise, forest atmosphere, indoor reverb, etc.
    - special effects: explosions, magic, sci-fi sounds, etc.
    - ASMR: gentle touches, liquid flow, subtle friction, etc.

    Returns: JSON-format data with the generation result"""
    try:
        logger.info(f"🎵 MMAudio V2 音效生成开始")
        logger.info(f"🎵 视频URL: {video_url[:100]}...")
        logger.info(f"🎵 音效描述: {prompt[:100]}...")
        logger.info(f"🎵 生成设置: duration={duration}s")

        # call the WaveSpeed sound-effect service (actually uses the MMAudio V2 model)
        result = await wavespeed_service.generate_audio(
            video_url=video_url,
            prompt=prompt,
            duration=duration
        )

        if result.success:
            logger.info(f"✅ MMAudio V2 音效生成成功: {result.audio_url}")
            cost = ToolService.calculate_cost(ToolType.MMAUDIO_V2, duration=duration)
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 MMAudio 音效成本: ${cost:.6f} ({duration}s)")
                cb = ToolService.get_credit_callback()
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.MMAUDIO.value, tool_type=ToolType.MMAUDIO_V2)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        else:
            logger.error(f"❌ MMAudio V2 音效生成失败: {result.message}")
            return result

    except Exception as e:
        logger.error(f"❌ MMAudio V2 音效生成异常: {str(e)}")
        result = AudioGenerationResult.error_result(
            error_message=f"MMAudio V2 音效生成异常: {str(e)}",
            provider=AudioProvider.WAVESPEED,
            video_url=video_url
        )
        return result


def get_mmaudio_tools() -> List['ToolInfo']:
    """Get the MMAudio V2 sound-effect tool info list.

    Returns:
        List[ToolInfo]: tool info list
    """
    from ...models.tool_enums import ToolType, ToolProvider, ToolCategory
    from ...services.tool_service import ToolInfo

    tool_type = ToolType.MMAUDIO_V2
    provider = ToolProvider.WAVESPEED

    # create the tool's ToolInfo
    tool_info = ToolInfo(
        tool=generate_audio_with_wavespeed,
        tool_name=generate_audio_with_wavespeed.name,
        tool_type=tool_type,
        provider=provider,
        category=ToolCategory.AUDIO_EFFECT,
        mode=None
    )

    # ✅ add metadata to the tool object (so the callback can precisely obtain ToolType)
    try:
        if hasattr(tool_info.tool, 'metadata'):
            if tool_info.tool.metadata is None:
                tool_info.tool.metadata = {}
            tool_info.tool.metadata.update({
                "tool_type": tool_type.value,
                "provider": provider.value,
                "category": ToolCategory.AUDIO_EFFECT.value
            })
    except Exception as e:
        logger.warning(f"添加tool metadata失败: {e}")

    return [tool_info]
