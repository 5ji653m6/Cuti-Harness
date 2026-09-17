"""
Minimax Speech 2.5 text-to-speech tool (via the WaveSpeed API)
"""
import logging
from typing import List, TYPE_CHECKING
from app.tools.runtime import tool
from langsmith import traceable

if TYPE_CHECKING:
    from ...services.tool_service import ToolInfo

from ...llm.wavespeed_service import get_wavespeed_service
from ...models.image_result import (
    SpeechGenerationResult, SpeechProvider, VoiceID, Emotion
)
from ...models.tool_enums import ToolName, ToolType
from ...services.tool_service import ToolService

logger = logging.getLogger(__name__)

# global service instance
wavespeed_service = get_wavespeed_service()


@tool(ToolName.MINIMAX_SPEECH)
@traceable(run_type='llm')
async def generate_speech_with_wavespeed(
    text: str,
    voice_id: str = VoiceID.WISE_WOMAN.value,
    emotion: str = Emotion.HAPPY.value,
    speed: float = 1.0,
    pitch: int = 0,
    volume: float = 1.0
) -> SpeechGenerationResult:
    """Professional Minimax Speech 2.5 text-to-speech tool (via the WaveSpeed API).

    A high-quality AI text-to-speech tool using the Minimax Speech 2.5 model.
    It generates natural, fluent speech from input text, supporting many voices, emotions, and audio parameter tuning.

    🎯 Important notes:
    1. Supports mixed Chinese/English text with automatic language detection
    2. Offers 150+ voice choices, including professional CN/EN announcers, role-play voices, etc.
    3. Supports 7 emotion modes and fine audio-parameter tuning
    4. Generates high-quality 48kHz audio files

    Parameters:
    - text: the text to convert to speech (supports mixed Chinese/English)
    - voice_id: voice ID, default "Wise_Woman"
      * general: Wise_Woman, Friendly_Person, Deep_Voice_Man, Calm_Woman, etc.
      * English: English_expressive_narrator, English_radiant_girl, and 100+ others
      * Chinese: Chinese (Mandarin)_News_Anchor, Chinese (Mandarin)_Gentleman, and 30+ others
    - emotion: speech emotion, default "happy"
      * options: happy, sad, angry, fearful, disgusted, surprised, neutral
    - speed: speech speed, default 1.0 (normal)
      * range: 0.5-2.0, 0.5=slow, 1.0=normal, 2.0=fast
    - pitch: pitch adjustment, default 0 (normal)
      * range: -12 to 12, negative=lower pitch, positive=higher pitch
    - volume: volume, default 1.0 (normal)
      * range: 0.1-2.0, 0.1=very quiet, 1.0=normal, 2.0=very loud

    🎵 Voice recommendations:
    - news: English_captivating_female1, Chinese (Mandarin)_News_Anchor
    - education: English_GentleTeacher, Chinese (Mandarin)_Wise_Women
    - storytelling: English_CaptivatingStoryteller, Chinese (Mandarin)_Radio_Host
    - business: English_Trustworth_Man, Chinese (Mandarin)_Reliable_Executive
    - children: English_PlayfulGirl, Chinese (Mandarin)_Cute_Spirit

    Returns: JSON-format data with the generation result, including audio URL, provider info, etc."""
    try:
        logger.info(f"🔊 Minimax Speech 2.5 语音合成开始")
        logger.info(f"🔊 文本内容: {text[:100]}...")
        logger.info(f"🔊 语音设置: voice_id={voice_id}, emotion={emotion}, speed={speed}, pitch={pitch}, volume={volume}")

        # call the WaveSpeed TTS service (actually uses the Minimax Speech 2.5 model)
        result = await wavespeed_service.generate_speech(
            text=text,
            voice_id=voice_id,
            emotion=emotion,
            speed=speed,
            pitch=pitch,
            volume=volume
        )

        if result.success:
            logger.info(f"✅ Minimax Speech 2.5 语音合成成功: {result.audio_url}")
            cost = ToolService.calculate_cost(ToolType.MINIMAX_SPEECH_2_5, text=text)
            if cost > 0:
                ToolService.log_cost(cost)
                logger.info(f"💰 Minimax Speech 成本: ${cost:.6f} ({len(text)} chars)")
                cb = ToolService.get_credit_callback()
                if cb:
                    cb.add_tool_cost(cost, tool_name=ToolName.MINIMAX_SPEECH.value, tool_type=ToolType.MINIMAX_SPEECH_2_5)
            result = result.model_copy(update={"billing_cost": cost})
            return result
        else:
            logger.error(f"❌ Minimax Speech 2.5 语音合成失败: {result.message}")
            return result

    except Exception as e:
        logger.error(f"❌ Minimax Speech 2.5 语音合成异常: {str(e)}")
        result = SpeechGenerationResult.error_result(
            error_message=f"Minimax Speech 2.5 语音合成异常: {str(e)}",
            provider=SpeechProvider.WAVESPEED
        )
        return result


def get_minimax_tools() -> List['ToolInfo']:
    """Get the Minimax TTS tool info list.

    Returns:
        List[ToolInfo]: tool info list
    """
    from ...models.tool_enums import ToolType, ToolProvider, ToolCategory
    from ...services.tool_service import ToolInfo

    tool_type = ToolType.MINIMAX_SPEECH_2_5
    provider = ToolProvider.WAVESPEED

    # create the tool's ToolInfo
    tool_info = ToolInfo(
        tool=generate_speech_with_wavespeed,
        tool_name=generate_speech_with_wavespeed.name,
        tool_type=tool_type,
        provider=provider,
        category=ToolCategory.SPEECH_SYNTHESIS,
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
                "category": ToolCategory.SPEECH_SYNTHESIS.value
            })
    except Exception as e:
        logger.warning(f"添加tool metadata失败: {e}")

    return [tool_info]
