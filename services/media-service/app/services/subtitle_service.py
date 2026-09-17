from __future__ import annotations

import re
from pathlib import Path

from app.models.subtitle import SubtitleCue


_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def _timestamp_srt(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def _timestamp_vtt(seconds: float) -> str:
    return _timestamp_srt(seconds).replace(",", ".")


def _timestamp_ass(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _wrap_cjk(text: str, width: int, max_lines: int) -> str:
    compact = re.sub(r"\s+", "", text)
    if len(compact) <= width:
        return compact
    lines: list[str] = []
    remaining = compact
    punctuation = "，。！？；：、,.!?;:"
    while remaining and len(lines) < max_lines:
        if len(lines) == max_lines - 1:
            lines.append(remaining)
            break
        cut = min(width, len(remaining))
        lower = max(1, cut // 2)
        candidates = [i + 1 for i, char in enumerate(remaining[:cut]) if char in punctuation]
        sensible = [value for value in candidates if value >= lower]
        if sensible:
            cut = sensible[-1]
        lines.append(remaining[:cut])
        remaining = remaining[cut:]
    return "\n".join(lines)


def _wrap_words(text: str, width: int, max_lines: int) -> str:
    words = text.split()
    if not words:
        return text.strip()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    consumed = sum(len(line.split()) for line in lines)
    if len(lines) == max_lines - 1:
        current = " ".join(words[consumed:])
    if current:
        lines.append(current)
    return "\n".join(lines[:max_lines])


def wrap_caption(text: str, width: int, max_lines: int) -> str:
    value = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if _CJK_RE.search(value):
        return _wrap_cjk(value, width, max_lines)
    return _wrap_words(value, width, max_lines)


def normalize_cues(
    cues: list[SubtitleCue], *, max_lines: int, max_chars_per_line: int, max_cps: float,
) -> tuple[list[SubtitleCue], dict]:
    ordered = sorted(cues, key=lambda item: (item.start, item.end))
    normalized: list[SubtitleCue] = []
    overlaps = 0
    cps_violations = 0
    previous_end = 0.0
    for cue in ordered:
        if cue.start < previous_end:
            overlaps += 1
        text = wrap_caption(cue.text, max_chars_per_line, max_lines)
        duration = max(0.001, cue.end - cue.start)
        visible_chars = len(re.sub(r"\s+", "", text))
        if visible_chars / duration > max_cps:
            cps_violations += 1
        normalized.append(SubtitleCue(start=cue.start, end=cue.end, text=text))
        previous_end = max(previous_end, cue.end)
    return normalized, {
        "overlaps": overlaps,
        "cps_violations": cps_violations,
        "invalid_cues": 0,
        "max_cps": max_cps,
    }


def write_subtitle(path: str | Path, cues: list[SubtitleCue], subtitle_format: str) -> None:
    destination = Path(path)
    if subtitle_format == "srt":
        blocks = [
            f"{index}\n{_timestamp_srt(cue.start)} --> {_timestamp_srt(cue.end)}\n{cue.text}"
            for index, cue in enumerate(cues, start=1)
        ]
        destination.write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig")
        return
    if subtitle_format == "vtt":
        blocks = [
            f"{_timestamp_vtt(cue.start)} --> {_timestamp_vtt(cue.end)}\n{cue.text}"
            for cue in cues
        ]
        destination.write_text("WEBVTT\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
        return
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,80,80,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        text = cue.text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        text = text.replace("\n", r"\N")
        events.append(
            f"Dialogue: 0,{_timestamp_ass(cue.start)},{_timestamp_ass(cue.end)},Default,,0,0,0,,{text}"
        )
    destination.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
