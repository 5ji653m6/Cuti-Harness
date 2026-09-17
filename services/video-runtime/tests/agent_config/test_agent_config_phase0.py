"""agent_config：转录与时长规划入口。"""

from app.agent_config import (
    TRANSCRIPTION_METHOD_CONFIG,
    get_audio_driven_duration_values,
    get_audio_driven_split_threshold,
    get_audio_segment_granularity_for_method,
    get_transcription_profile,
)
from app.agent_config.transcription import TranscriptionEngineProfile
from app.models.tool_enums import AudioSegmentGranularity
from app.models.user_options import UserOption, VideoGenerationTool


def test_transcription_hybrid_sentence():
    assert get_audio_segment_granularity_for_method("hybrid") == AudioSegmentGranularity.SENTENCE
    assert get_transcription_profile("hybrid").granularity == AudioSegmentGranularity.SENTENCE
    assert "hybrid" in TRANSCRIPTION_METHOD_CONFIG
    assert TRANSCRIPTION_METHOD_CONFIG["hybrid"]["granularity"] == "sentence"


def test_transcription_engine_profile_is_dataclass():
    assert isinstance(get_transcription_profile("gemini"), TranscriptionEngineProfile)


def test_seedance_2_duration_and_split_threshold():
    opt = UserOption(video_generation_tool=VideoGenerationTool.SEEDANCE_2_I2V)
    assert get_audio_driven_duration_values(opt) == list(range(4, 13))
    assert get_audio_driven_split_threshold(opt) == 8.0
