"""fallback_full_track_sections：无曲式时整轨一段的 additional_data 结构。"""
from app.models.video_state import AudioSegment
from app.tools.transcribe.gemini import fallback_full_track_sections


def test_fallback_uses_actual_duration_when_no_segments():
    out = fallback_full_track_sections(120.0, [], global_emotion="calm")
    assert len(out) == 1
    assert out[0]["section_type"] == "整曲"
    assert out[0]["start_time"] == 0.0
    assert out[0]["end_time"] == 120.0
    assert out[0]["section_emotion"] == "calm"


def test_fallback_end_covers_last_segment_end():
    segs = [
        AudioSegment(id=0, start=0.0, end=50.0, text="a", duration=50.0),
        AudioSegment(id=1, start=50.0, end=260.1, text="b", duration=210.1),
    ]
    out = fallback_full_track_sections(260.0, segs, global_emotion=None)
    assert out[0]["end_time"] == 260.1


def test_fallback_when_segments_shorter_than_file_uses_actual_duration():
    """MSC/文件时长大于最后一片 end 时，上界仍取 max，避免 section 比真实时长短。"""
    segs = [
        AudioSegment(id=0, start=0.0, end=30.0, text="a", duration=30.0),
    ]
    out = fallback_full_track_sections(120.0, segs, global_emotion=None)
    assert out[0]["end_time"] == 120.0


def test_fallback_dict_has_required_keys_for_section_crud():
    """与 music_generation 中 create_video_audio_section 前置校验一致：有 section_type 与时间。"""
    out = fallback_full_track_sections(10.0, [], global_emotion="happy")
    sec = out[0]
    assert sec["section_type"] == "整曲"
    assert sec["start_time"] == 0.0
    assert isinstance(sec["end_time"], float)
    assert sec["end_time"] >= sec["start_time"]
    assert "suggested_context" in sec
