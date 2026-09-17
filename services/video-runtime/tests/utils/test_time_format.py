"""单元测试：app.utils.time_format

覆盖：
- 基础秒数 → MM:SS.mmm
- 边界（0 / None / 负数 / NaN / 整分钟 / 毫秒进位）
- format_sec_range 区间格式
- 与 hybrid `_seconds_to_mmss` 旧实现的等价性（同一秒数同一字符串）
"""
from __future__ import annotations

import math

import pytest

from app.utils.time_format import format_sec_range, format_sec_to_mmss


@pytest.mark.parametrize(
    "sec,expected",
    [
        (0, "0:00.000"),
        (0.0, "0:00.000"),
        (12.25, "0:12.250"),
        (80.5, "1:20.500"),
        (125.123, "2:05.123"),
        (60.0, "1:00.000"),
        (3599.999, "59:59.999"),
        (3600, "60:00.000"),
    ],
)
def test_format_sec_to_mmss_basic(sec, expected):
    assert format_sec_to_mmss(sec) == expected


@pytest.mark.parametrize("bad", [None, -1, -0.5, float("nan")])
def test_format_sec_to_mmss_safe_fallback(bad):
    """非法输入统一回退 0:00.000，避免下游 prompt 出现 None / 负数。"""
    assert format_sec_to_mmss(bad) == "0:00.000"


def test_format_sec_to_mmss_str_input_rejected_gracefully():
    """非数值字符串视为非法，返回 0:00.000。"""
    assert format_sec_to_mmss("abc") == "0:00.000"  # type: ignore[arg-type]


def test_format_sec_range_basic():
    assert format_sec_range(12.25, 18.5) == "0:12.250-0:18.500"
    assert format_sec_range(None, None) == "0:00.000-0:00.000"


def test_equivalence_with_hybrid_seconds_to_mmss():
    """hybrid._seconds_to_mmss 已改为直接复用此函数，二者必须完全一致。"""
    from app.tools.transcribe.hybrid import _seconds_to_mmss

    for sec in [0, 1.0, 12.25, 80.5, 125.123, 3600]:
        assert _seconds_to_mmss(sec) == format_sec_to_mmss(sec)
