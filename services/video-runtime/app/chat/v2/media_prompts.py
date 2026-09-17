"""Gemini system instructions for host media capabilities.

These markdown files live under ``prompts/media/`` and are **not** Skill catalog
packages. Terra must not load them as helper Skills.
"""
from __future__ import annotations

import re
from pathlib import Path

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

MEDIA_PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts" / "media"


def media_system_instruction(name: str) -> str:
    """Return the body of ``prompts/media/<name>/SKILL.md`` (frontmatter stripped)."""
    slug = str(name or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug in {".", ".."}:
        raise ValueError(f"invalid media prompt name: {name!r}")
    path = MEDIA_PROMPTS_ROOT / slug / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"media prompt not found: {slug}")
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    body = text[match.end():].strip() if match else text.strip()
    if not body:
        raise ValueError(f"media prompt empty: {slug}")
    return body
