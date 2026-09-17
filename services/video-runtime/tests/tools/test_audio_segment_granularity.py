"""单元测试：audio segment granularity 相关纯逻辑

覆盖：
- `AudioSegmentGranularity.from_value` 容错（None/str/enum/未知）
- `_resolve_granularity` 优先级：显式入参 > UserOption > DefaultValues
- `snap_segment_edges_to_bar_grid` 各路径：
    1. 端点在 tolerance 内 → 吸附到 bar 网格
    2. 端点离 bar 太远（> tolerance） → 不动
    3. 吸附点落在词内部 + 附近有词边界 → 漂到词边界
    4. 吸附点落在词内部 + 无附近词边界 → 不动
    5. 相邻段端点保持连续（seg[i].end == seg[i+1].start）
    6. 末段不超出 total_duration

不依赖 LLM / 网络 / DB。
"""
from __future__ import annotations

from typing import List

import pytest

from app.agent_config import (
    TRANSCRIPTION_METHOD_CONFIG,
    get_audio_segment_granularity_for_method,
    get_transcription_method_config,
)
from app.models.tool_enums import AudioSegmentGranularity, DefaultValues
from app.models.video_state import AudioSegment
from app.tools.transcribe.gemini import (
    _resolve_granularity,
    snap_segment_edges_to_bar_grid,
)


# ============================================================================
# Enum 容错
# ============================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, AudioSegmentGranularity.SENTENCE),
        ("phrase", AudioSegmentGranularity.PHRASE),
        ("sentence", AudioSegmentGranularity.SENTENCE),
        ("beat", AudioSegmentGranularity.BEAT),
        ("BEAT", AudioSegmentGranularity.BEAT),
        ("  sentence  ", AudioSegmentGranularity.SENTENCE),
        ("garbage", AudioSegmentGranularity.PHRASE),
        (AudioSegmentGranularity.BEAT, AudioSegmentGranularity.BEAT),
    ],
)
def test_granularity_from_value(raw, expected):
    assert AudioSegmentGranularity.from_value(raw) == expected


def test_default_value_consistent_with_enum():
    """DefaultValues.AUDIO_SEGMENT_GRANULARITY 必须能被 enum 解析回 SENTENCE。"""
    assert (
        AudioSegmentGranularity.from_value(DefaultValues.AUDIO_SEGMENT_GRANULARITY)
        == AudioSegmentGranularity.SENTENCE
    )


def test_resolve_granularity_explicit_wins():
    """显式入参直接命中；不再读 UserOption（granularity 不是用户产品选项）。"""
    assert _resolve_granularity(AudioSegmentGranularity.BEAT) == AudioSegmentGranularity.BEAT
    assert _resolve_granularity(AudioSegmentGranularity.SENTENCE) == AudioSegmentGranularity.SENTENCE


def test_resolve_granularity_falls_back_to_default_values():
    """入参为 None 时退回 DefaultValues.AUDIO_SEGMENT_GRANULARITY (= SENTENCE)。"""
    assert _resolve_granularity(None) == AudioSegmentGranularity.SENTENCE


def test_transcription_method_config_has_known_methods():
    """`gemini` / `hybrid` 都必须配置 granularity，避免 caller 拿到空表。"""
    assert "gemini" in TRANSCRIPTION_METHOD_CONFIG
    assert "hybrid" in TRANSCRIPTION_METHOD_CONFIG
    for cfg in TRANSCRIPTION_METHOD_CONFIG.values():
        # `granularity` 必须能被 enum 解析
        assert AudioSegmentGranularity.from_value(cfg.get("granularity")) in (
            AudioSegmentGranularity.PHRASE,
            AudioSegmentGranularity.SENTENCE,
            AudioSegmentGranularity.BEAT,
        )


@pytest.mark.parametrize("method", ["gemini", "hybrid", "GEMINI", "  Hybrid  "])
def test_get_audio_segment_granularity_for_method_known(method):
    """已知 method（大小写/空白不敏感）必须返回 sentence。"""
    assert get_audio_segment_granularity_for_method(method) == AudioSegmentGranularity.SENTENCE


@pytest.mark.parametrize("method", ["", None, "unknown_method", "whisper"])
def test_get_audio_segment_granularity_for_method_unknown_falls_back(method):
    """未配置的 method 退回 DefaultValues.AUDIO_SEGMENT_GRANULARITY，避免 KeyError。"""
    assert get_audio_segment_granularity_for_method(method) == AudioSegmentGranularity.from_value(
        DefaultValues.AUDIO_SEGMENT_GRANULARITY
    )


def test_get_transcription_method_config_unknown_returns_empty_dict():
    """未知 method 返回 {}，让 caller 走兜底而不是抛错。"""
    assert get_transcription_method_config("nope") == {}
    assert get_transcription_method_config("") == {}


# ============================================================================
# snap_segment_edges_to_bar_grid
# ============================================================================


def _seg(start: float, end: float, text: str = "") -> AudioSegment:
    return AudioSegment(id=0, start=start, end=end, text=text, duration=end - start)


def test_snap_no_bpm_returns_input_unchanged():
    segs = [_seg(0.0, 1.0), _seg(1.0, 2.0)]
    out = snap_segment_edges_to_bar_grid(segs, bar_dur_sec=0.0)
    assert [(s.start, s.end) for s in out] == [(0.0, 1.0), (1.0, 2.0)]


def test_snap_within_tolerance_aligns_to_bar():
    """120 BPM → bar_dur=2.0s。端点 1.95s 距 bar=2.0s 仅 0.05s → 吸附。"""
    segs = [_seg(0.0, 1.95), _seg(1.95, 3.90)]
    out = snap_segment_edges_to_bar_grid(segs, bar_dur_sec=2.0, tolerance_sec=0.20)
    assert out[0].start == 0.0
    assert pytest.approx(out[0].end, abs=1e-6) == 2.0
    assert pytest.approx(out[1].start, abs=1e-6) == 2.0
    # 末段尾巴 3.90 距 4.0 是 0.10 → 也吸附
    assert pytest.approx(out[1].end, abs=1e-6) == 4.0


def test_snap_outside_tolerance_keeps_original():
    """端点 1.5s 距 bar=2.0s 是 0.5s > tolerance 0.20 → 不动。"""
    segs = [_seg(0.0, 1.5), _seg(1.5, 3.0)]
    out = snap_segment_edges_to_bar_grid(segs, bar_dur_sec=2.0, tolerance_sec=0.20)
    assert pytest.approx(out[0].end, abs=1e-6) == 1.5
    assert pytest.approx(out[1].start, abs=1e-6) == 1.5


def test_snap_inside_word_drifts_to_word_edge():
    """bar=2.0 但 [1.8, 2.3] 是一个词，2.0 在词内部 → 漂到最近词边界 1.8。"""
    segs = [_seg(0.0, 1.95), _seg(1.95, 3.90)]
    word_edges = [0.0, 0.5, 1.0, 1.8, 2.3, 3.0, 3.8]
    out = snap_segment_edges_to_bar_grid(
        segs,
        bar_dur_sec=2.0,
        tolerance_sec=0.20,
        word_edges_sec=word_edges,
    )
    assert pytest.approx(out[0].end, abs=1e-6) == 1.8
    assert pytest.approx(out[1].start, abs=1e-6) == 1.8


def test_snap_inside_word_no_nearby_edge_keeps_original():
    """bar=2.0 在词 [1.0, 3.0] 内部，最近词边界 1.0/3.0 都 > tolerance → 不动。"""
    segs = [_seg(0.0, 1.95), _seg(1.95, 3.90)]
    word_edges = [0.0, 1.0, 3.0, 4.0]
    out = snap_segment_edges_to_bar_grid(
        segs,
        bar_dur_sec=2.0,
        tolerance_sec=0.20,
        word_edges_sec=word_edges,
    )
    assert pytest.approx(out[0].end, abs=1e-6) == 1.95


def test_snap_edges_remain_contiguous():
    """所有相邻段端点必须严格连续：seg[i].end == seg[i+1].start。"""
    segs = [_seg(0.0, 1.95), _seg(1.95, 3.95), _seg(3.95, 5.90)]
    out = snap_segment_edges_to_bar_grid(segs, bar_dur_sec=2.0, tolerance_sec=0.20)
    for a, b in zip(out, out[1:]):
        assert a.end == b.start, f"discontinuity at {a.end} vs {b.start}"


def test_snap_respects_total_duration_cap():
    """末段 end 不得超出 total_duration（即使吸附后会更长）。"""
    segs = [_seg(0.0, 1.95), _seg(1.95, 3.95)]
    out = snap_segment_edges_to_bar_grid(
        segs, bar_dur_sec=2.0, tolerance_sec=0.20, total_duration=3.50
    )
    assert out[-1].end <= 3.50 + 1e-9


def test_snap_preserves_metadata():
    """text / emotion / tempo / vocal_presence / vocal_gender 必须完整保留。"""
    seg = AudioSegment(
        id=7,
        start=0.0,
        end=1.95,
        text="hello world",
        duration=1.95,
        emotion="happy",
        tempo="fast",
        vocal_presence=True,
        vocal_gender="f",
    )
    out = snap_segment_edges_to_bar_grid([seg], bar_dur_sec=2.0, tolerance_sec=0.20)
    assert out[0].text == "hello world"
    assert out[0].emotion == "happy"
    assert out[0].tempo == "fast"
    assert out[0].vocal_presence is True
    assert out[0].vocal_gender == "f"
    assert out[0].id == 0  # snap 内统一重排序 id
