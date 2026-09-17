"""
Time-formatting utilities

Unify the project's "seconds -> human-readable string" display format.
Consistent with the Gemini transcribe output contract (`MM:SS.mmm`), so that
time references on the LLM side can be copy-pasted directly into downstream prompts.

Underlying storage / computation stays in float seconds (see AudioSegment); this utility is only for
the **external / LLM-facing display layer**.
"""
from __future__ import annotations

from typing import Optional, Union


def format_sec_to_mmss(sec: Optional[Union[int, float]]) -> str:
    """Seconds -> MM:SS.mmm (e.g. 80.5 -> "1:20.500", 12.25 -> "0:12.250").

    - None / invalid / negative: uniformly returns "0:00.000", to avoid ``None`` in prompts
    - Does not zero-pad minutes (consistent with hybrid `_seconds_to_mmss`'s historical output), but zero-pads seconds
      to a two-digit integer + three-digit milliseconds, for easy comparison with Gemini output
    """
    try:
        s = float(sec) if sec is not None else 0.0
    except (TypeError, ValueError):
        s = 0.0
    if s < 0 or s != s:  # negative / NaN
        s = 0.0
    minutes = int(s // 60)
    seconds = s - minutes * 60
    return f"{minutes}:{seconds:06.3f}"


def format_sec_range(start: Optional[Union[int, float]], end: Optional[Union[int, float]]) -> str:
    """Second interval -> "MM:SS.mmm-MM:SS.mmm" (specifically for prompt display)."""
    return f"{format_sec_to_mmss(start)}-{format_sec_to_mmss(end)}"
