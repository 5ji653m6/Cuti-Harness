"""Speech tool wrapper 与 Minimax 定价单元测试"""
import pytest

from app.models.tool_enums import ToolType
from app.services.tool_service import ToolService
from app.tools.narration.speech_tool_wrapper import (
    _duration_within_tolerance,
    _resolve_voice_id,
    create_speech_wrapper_tools,
    DURATION_TOLERANCE_SEC,
)
from app.tools.context_schemas import SpeechGenerationContext
from app.models.image_result import VoiceID, normalize_emotion, Emotion


def test_minimax_speech_cost_per_character():
    cost = ToolService.calculate_cost(ToolType.MINIMAX_SPEECH_2_5, text="a" * 1000)
    assert cost == pytest.approx(0.04)


def test_duration_within_tolerance():
    assert _duration_within_tolerance(3.4, 3.0) is True
    assert _duration_within_tolerance(3.0 + DURATION_TOLERANCE_SEC, 3.0) is True
    assert _duration_within_tolerance(3.0 + DURATION_TOLERANCE_SEC + 0.01, 3.0) is False


def test_resolve_voice_id_zh_default():
    ctx = SpeechGenerationContext(detected_language="zh")
    assert _resolve_voice_id(VoiceID.WISE_WOMAN.value, ctx) == VoiceID.CHINESE_NEWS_ANCHOR.value


def test_resolve_voice_id_en_default():
    ctx = SpeechGenerationContext(detected_language="en")
    assert _resolve_voice_id(VoiceID.WISE_WOMAN.value, ctx) == VoiceID.ENGLISH_EXPRESSIVE_NARRATOR.value


def test_normalize_emotion_calm_maps_to_neutral():
    assert normalize_emotion("calm") == Emotion.NEUTRAL.value


def test_normalize_emotion_allowed_passthrough():
    assert normalize_emotion("happy") == "happy"
    assert normalize_emotion("NEUTRAL") == "neutral"


def test_normalize_emotion_unknown_defaults_neutral():
    assert normalize_emotion("mysterious") == Emotion.NEUTRAL.value
    assert normalize_emotion(None) == Emotion.NEUTRAL.value


def test_resolve_voice_id_enforces_male_when_speaker_gender_set():
    ctx = SpeechGenerationContext(detected_language="zh", speaker_gender="m")
    assert _resolve_voice_id(VoiceID.CHINESE_NEWS_ANCHOR.value, ctx) == (
        VoiceID.CHINESE_MALE_ANNOUNCER.value
    )


def test_create_speech_wrapper_tools():
    tools = create_speech_wrapper_tools()
    assert len(tools) == 1
    assert tools[0].tool.name == "generate_speech_with_fallback"
