from app.models.tool_enums import AudioSegmentGranularity
from app.models.video_state import AudioWord
from app.tools.transcribe.hybrid import (
    SunoReshaped,
    _build_alignment_fallback_transcription,
)


def test_alignment_fallback_builds_transcription_from_timed_words():
    alignment = SunoReshaped(
        clean_words=[
            AudioWord(id=0, word="Hello", start=0.2, end=0.7),
            AudioWord(id=1, word="world", start=0.8, end=1.3),
            AudioWord(id=2, word="Next", start=2.4, end=2.9),
            AudioWord(id=3, word="line", start=3.0, end=3.5),
        ],
        vocal_gender_hint="f",
    )

    result = _build_alignment_fallback_transcription(
        "https://example.com/audio.mp3",
        "audio.mp3",
        alignment,
        generated_lyrics="Hello world\nNext line",
        alignment_provider="mureka",
        granularity=AudioSegmentGranularity.SENTENCE,
    )

    assert result is not None
    assert result.language == "en"
    assert result.duration == 3.5
    assert [segment.text for segment in result.segments] == ["Hello world", "Next line"]
    assert all(segment.vocal_presence for segment in result.segments)
    assert all(segment.vocal_gender == "f" for segment in result.segments)
    assert result.additional_data["transcription_outcome"] == "fallback_alignment_only"
    assert result.additional_data["alignment_provider"] == "mureka"
    assert len(result.additional_data["words"]) == 4


def test_alignment_fallback_requires_timed_words():
    result = _build_alignment_fallback_transcription(
        "https://example.com/audio.mp3",
        "audio.mp3",
        SunoReshaped(),
        generated_lyrics="Hello world",
        alignment_provider="mureka",
        granularity=AudioSegmentGranularity.SENTENCE,
    )

    assert result is None
