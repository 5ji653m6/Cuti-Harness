"""Prompt helpers backed by the process-wide Video Skill catalog."""
from __future__ import annotations

import json
from typing import Any, Dict


def skill_instructions(skill_id: str) -> str:
    """Load one enabled Skill through the authoritative Video Skill Runtime."""

    from app.video_runtime.skills import default_video_skill_runtime

    catalog = default_video_skill_runtime().catalog
    if not catalog.has(skill_id):
        raise LookupError(f"required Skill is not installed: {skill_id}")
    loaded = catalog.load(skill_id)
    if not loaded.metadata.enabled:
        raise ValueError(f"required Skill is disabled: {skill_id}")
    return loaded.instructions.strip()


def skill_system_message(skill_id: str, *, lead: str = "") -> str:
    """Build a system prompt from a catalog-resolved Skill."""

    return "\n\n".join(
        part for part in (lead.strip(), skill_instructions(skill_id)) if part
    )


def facts_human_message(facts: Dict[str, Any]) -> str:
    """Serialize machine facts; creative and execution rules live in Skills."""

    return json.dumps(facts, ensure_ascii=False, indent=2, default=str)
