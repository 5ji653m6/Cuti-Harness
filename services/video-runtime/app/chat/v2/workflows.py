"""Dynamic user-selectable workflows discovered from SKILL.md frontmatter."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.capabilities.models import CapabilityRegistry
from app.orchestration.workflow_compiler import WorkflowRegistry, WorkflowSpec


EXPLICIT_SKILL_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[$/]([a-z0-9][a-z0-9-]{0,63})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

STAGE_CAPABILITY_IDS = frozenset({
    "api.provider.generate", "api.ark_protocol.generate", "media.concat",
    "media.extract_frame", "media.audio_trim", "media.audio_analyze",
    "media.video_analyze",
    "media.audio_cut",
    "media.mix_audio", "atomic.text.generate",
    "atomic.image.generate", "atomic.music.generate", "atomic.video.generate",
    "suno.generate",
})
WORKFLOW_FREE_CAPABILITY_IDS = frozenset({
    "actions.suggest",
    # Post-production operates on existing artifacts and must not inherit
    # generation-provider parameters from the active workflow.
    "media.concat",
    "media.extract_frame",
    "media.transcribe",
    "subtitle.compose",
    "media.subtitle_burn",
    "media.audio_trim",
    "media.audio_analyze",
    "media.video_analyze",
    "media.audio_cut",
    "media.mix_audio",
    "media.hyperframes_caption",
    "media.hyperframes_render",
})

_registry = WorkflowRegistry()
WORKFLOWS = _registry.items()
_configured = False


def configure_workflows(catalog: Any, capabilities: CapabilityRegistry | None = None) -> int:
    """Atomically replace workflows from the currently installed Skill catalog."""
    global _configured
    _registry.replace_from_catalog(catalog, capabilities)
    _configured = True
    return len(WORKFLOWS)


def _ensure_default_workflows() -> None:
    """Lazy bootstrap for unit tests and non-container consumers."""
    global _configured
    if _configured:
        return
    from app.chat.v2.skill_catalog import SkillCatalog

    agent_root = Path(__file__).resolve().parents[3]
    roots = [
        agent_root / "skills" / "system",
        agent_root / "skills" / "builtin",
        agent_root / "skills" / "external",
    ]
    catalog = SkillCatalog(roots)
    catalog.discover()
    configure_workflows(catalog)


def is_workflow_skill(name: str) -> bool:
    _ensure_default_workflows()
    return _registry.get(name) is not None


def workflow_skill_names() -> frozenset[str]:
    _ensure_default_workflows()
    return _registry.names()


def parse_explicit_skill_names(text: str) -> list[str]:
    return sorted({match.group(1).lower() for match in EXPLICIT_SKILL_RE.finditer(text or "")})


def active_workflow(activated_skills: list[str] | None) -> WorkflowSpec | None:
    _ensure_default_workflows()
    for name in activated_skills or []:
        spec = _registry.get(name)
        if spec is not None:
            return spec
    return None


def capability_requires_workflow(capability_id: str) -> bool:
    if capability_id in WORKFLOW_FREE_CAPABILITY_IDS:
        return False
    return capability_id in STAGE_CAPABILITY_IDS


def inject_workflow_parameters(parameters: dict[str, Any], spec: WorkflowSpec) -> dict[str, Any]:
    merged = dict(parameters or {})
    for key, value in spec.parameters.items():
        merged.setdefault(key, value)
    merged.setdefault("activated_workflow", spec.skill_name)
    return merged
