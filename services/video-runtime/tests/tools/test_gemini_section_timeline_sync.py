"""Gemini 转录：fill_gaps 等后置后曲式最后一节 end_time 与最终切片时间轴对齐。"""

from app.models.video_state import AudioSegment
from app.tools.transcribe.gemini import _sync_section_end_times_to_segments


def test_sync_extends_last_section_when_segments_past_gemini_end():
    sections = [
        {"section_type": "A", "start_time": 0.0, "end_time": 100.0, "section_emotion": None},
        {"section_type": "B", "start_time": 100.0, "end_time": 250.0, "section_emotion": None},
    ]
    audio_segments = [
        AudioSegment(id=0, start=0.0, end=100.0, text="a", duration=100.0, uuid="s0"),
        AudioSegment(id=1, start=100.0, end=250.0, text="b", duration=150.0, uuid="s1"),
        AudioSegment(id=2, start=259.5, end=260.0, text="", duration=0.5, uuid="tail"),
    ]
    _sync_section_end_times_to_segments(sections, audio_segments, actual_duration=260.0)
    assert sections[0]["end_time"] == 100.0
    assert sections[1]["end_time"] == 260.0


def test_sync_no_op_when_last_section_already_covers_timeline():
    sections = [
        {"section_type": "A", "start_time": 0.0, "end_time": 260.0, "section_emotion": None},
    ]
    segs = [
        AudioSegment(id=0, start=0.0, end=260.0, text="x", duration=260.0, uuid="a"),
    ]
    _sync_section_end_times_to_segments(sections, segs, actual_duration=260.0)
    assert sections[0]["end_time"] == 260.0


def test_sync_empty_sections_list():
    _sync_section_end_times_to_segments([], [], 10.0)
