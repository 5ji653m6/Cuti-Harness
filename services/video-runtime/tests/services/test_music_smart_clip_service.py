"""单元测试：smart clip 分析（PR-3）。

直通路径 / 启发式回退两条不依赖 LLM 的分支必须稳定。

跑：
  conda run -n cuti-video-local pytest tests/services/test_music_smart_clip_service.py -v -s
"""
from typing import Any
import pytest

from app.models.video_state import AudioSegment, AudioTranscription
from app.services.agent.video.music_smart_clip_service import (
    SmartClipAnalysis,
    SmartClipSelection,
    analyze_music_smart_clip,
)


@pytest.fixture
def disable_smart_clip_ai(monkeypatch):
    async def _fail(*_a, **_k):
        raise RuntimeError("ai disabled in test")

    monkeypatch.setattr(
        "app.services.agent.video.music_smart_clip_service._ai_analyze_with_transcription",
        _fail,
    )


def _make_transcription(
    duration: float,
    sections: list[dict] | None = None,
    segments: list[AudioSegment] | None = None,
    bpm: float | None = 96.0,
) -> AudioTranscription:
    extra: dict[str, Any] = {}
    if sections is not None:
        extra["sections"] = sections
    return AudioTranscription(
        task="transcribe",
        language="en",
        duration=duration,
        text="",
        segments=segments or [],
        audio_url="https://example.com/song.mp3",
        is_instrumental=False,
        global_bpm=bpm,
        additional_data=extra or None,
    )


@pytest.mark.asyncio
async def test_passthrough_when_audio_short_enough():
    """音频 14s ≤ target 15s + gap 1s → 走 passthrough。"""
    tr = _make_transcription(duration=14.0)
    out = await analyze_music_smart_clip(
        audio_url="https://example.com/song.mp3",
        target_duration_sec=15.0,
        transcription=tr,
        audio_duration_sec=14.0,
    )
    assert isinstance(out, SmartClipAnalysis)
    assert out.method == "passthrough"
    assert out.recommended.start_sec == 0.0
    assert out.recommended.end_sec == 14.0
    assert out.recommended.fade_in_sec == 0.0
    assert out.recommended.fade_out_sec == 0.0


@pytest.mark.asyncio
async def test_heuristic_section_picks_closest_section_combo(disable_smart_clip_ai):
    """heuristic_section 在 sections 累加最接近 target 处停。"""
    sections = [
        {"section_type": "intro", "start_time": 0.0, "end_time": 8.0,
         "section_emotion": "warm", "musical_features": "soft bells"},
        {"section_type": "verse", "start_time": 8.0, "end_time": 25.0,
         "section_emotion": "uplifting", "musical_features": "vocal"},
        {"section_type": "chorus", "start_time": 25.0, "end_time": 60.0,
         "section_emotion": "high", "musical_features": "full band"},
        {"section_type": "outro", "start_time": 60.0, "end_time": 70.0,
         "section_emotion": "soft", "musical_features": "fade"},
    ]
    tr = _make_transcription(duration=70.0, sections=sections)

    out = await analyze_music_smart_clip(
        audio_url="https://example.com/song.mp3",
        target_duration_sec=25.0,
        transcription=tr,
        audio_duration_sec=70.0,
    )
    assert out.method == "heuristic_section"
    assert out.fallback_used is True
    # 累加：intro(8) → 8s；intro+verse → 25s（best）
    assert out.recommended.end_sec == pytest.approx(25.0, abs=0.01)
    assert out.recommended.start_sec == 0.0
    assert out.recommended.actual_duration_sec == pytest.approx(25.0, abs=0.01)
    assert out.recommended.duration_error_sec == pytest.approx(0.0, abs=0.01)
    assert any(c.kind.value == "section_boundary" for c in out.candidates)


@pytest.mark.asyncio
async def test_heuristic_center_when_no_sections(disable_smart_clip_ai):
    """无 sections 时走 heuristic_center。"""
    tr = _make_transcription(duration=180.0, sections=None)

    out = await analyze_music_smart_clip(
        audio_url="https://example.com/song.mp3",
        target_duration_sec=60.0,
        transcription=tr,
        audio_duration_sec=180.0,
    )
    assert out.method == "heuristic_center"
    assert out.recommended.start_sec == pytest.approx(60.0, abs=0.5)
    assert out.recommended.end_sec == pytest.approx(120.0, abs=0.5)
    assert out.recommended.actual_duration_sec == pytest.approx(60.0, abs=0.5)


@pytest.mark.asyncio
async def test_normalize_clamps_analysis_output():
    """逻辑越界（end > audio_duration / actual_duration 错算）但 schema 合法时，
    _normalize_analysis 应 clamp 到合法范围 + 重算 duration / error。"""
    from app.services.agent.video.music_smart_clip_service import (
        SmartClipSelection,
        SmartCutCandidate,
        SmartCutKind,
    )
    bogus = SmartClipAnalysis(
        audio_duration_sec=120.0,
        target_duration_sec=30.0,
        candidates=[
            SmartCutCandidate(
                time_sec=200.0,  # 越界，应 clamp 到 120
                kind=SmartCutKind.PHRASE_END,
                vocal_safe=True,
                energy_score=0.4,
                score=0.7,
                rationale="oob",
            ),
        ],
        recommended=SmartClipSelection(
            start_sec=10.0,
            end_sec=200.0,           # 越界 → clamp 到 120
            fade_in_sec=8.0,         # schema 上限即 8
            fade_out_sec=0.0,
            target_duration_sec=30.0,
            actual_duration_sec=999.0,  # 错算 → 应被重算为 110
            duration_error_sec=999.0,   # 错算 → 应被重算为 80
            reasoning="bogus",
        ),
        fallback_used=False,
        method="ai_reuse_transcription",
    )

    from app.services.agent.video.music_smart_clip_service import _normalize_analysis
    out = _normalize_analysis(bogus, 120.0, 30.0)
    assert 0.0 <= out.recommended.start_sec <= 120.0
    assert 0.0 <= out.recommended.end_sec <= 120.0
    assert out.recommended.end_sec == 120.0  # clamp 到 audio_duration
    # actual_duration / duration_error 应被重算
    assert out.recommended.actual_duration_sec == pytest.approx(110.0, abs=0.01)
    assert out.recommended.duration_error_sec == pytest.approx(80.0, abs=0.01)
    # candidate time_sec 也被 clamp
    assert out.candidates[0].time_sec == 120.0


@pytest.mark.asyncio
async def test_segments_view_handles_missing_vocal_presence():
    """vocal_presence 缺失时应根据 text 是否非空回填 bool（不应崩）。"""
    segs = [
        AudioSegment(id=1, start=0.0, end=2.0, text="hello", duration=2.0, vocal_presence=None),
        AudioSegment(id=2, start=2.0, end=4.0, text="", duration=2.0, vocal_presence=None),
    ]
    tr = _make_transcription(duration=10.0, segments=segs)

    # 通过 _build_segments_view 直接验证（避免 LLM 调用）
    from app.services.agent.video.music_smart_clip_service import _build_segments_view
    view = _build_segments_view(tr)
    assert len(view) == 2
    assert view[0]["vocal_presence"] is True
    assert view[1]["vocal_presence"] is False


@pytest.mark.asyncio
async def test_ai_window_used_when_director_succeeds(monkeypatch):
    async def _ai(audio_duration_sec, target_duration_sec, transcription):
        return SmartClipAnalysis(
            audio_duration_sec=audio_duration_sec,
            target_duration_sec=target_duration_sec,
            candidates=[],
            recommended=SmartClipSelection(
                start_sec=25.0,
                end_sec=50.0,
                fade_in_sec=0.0,
                fade_out_sec=1.0,
                target_duration_sec=target_duration_sec,
                actual_duration_sec=25.0,
                duration_error_sec=0.0,
                reasoning="keep chorus complete",
            ),
            fallback_used=False,
            method="ai_reuse_transcription",
        )

    monkeypatch.setattr(
        "app.services.agent.video.music_smart_clip_service._ai_analyze_with_transcription",
        _ai,
    )
    tr = _make_transcription(duration=70.0, sections=[
        {"section_type": "intro", "start_time": 0.0, "end_time": 8.0,
         "section_emotion": "warm", "musical_features": "soft bells"},
        {"section_type": "chorus", "start_time": 25.0, "end_time": 50.0,
         "section_emotion": "high", "musical_features": "full band"},
    ])
    out = await analyze_music_smart_clip(
        audio_url="https://example.com/song.mp3",
        target_duration_sec=25.0,
        transcription=tr,
        audio_duration_sec=70.0,
    )
    assert out.method == "ai_reuse_transcription"
    assert out.fallback_used is False
    assert out.recommended.start_sec == pytest.approx(25.0)
    assert out.recommended.end_sec == pytest.approx(50.0)
