from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.skills.lock import SkillLock


class ResolvedSkillRef(BaseModel):
    skill_id: str
    version: str | None = None
    content_hash: str
    roles: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    source: str


class SkillHardConstraint(BaseModel):
    """Model-extracted requirement that an executor can enforce mechanically."""

    constraint_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    required_terms: list[str] = Field(default_factory=list)
    required_fields: dict[str, str] = Field(default_factory=dict)


class SkillConstraintContract(BaseModel):
    """Stage-specific classification of mandatory rules and creative guidance."""

    hard_constraints: list[SkillHardConstraint] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)


class SkillContext(BaseModel):
    """Immutable Skill instructions and provenance resolved for one execution step."""

    instructions: str = ""
    applied_skills: list[ResolvedSkillRef] = Field(default_factory=list)
    constraint_contract: SkillConstraintContract | None = None

    def apply_to(self, text: str) -> str:
        if not self.instructions.strip():
            return text
        rendered = (
            f"{text}\n\n"
            "Authoritative instructions from Skills resolved for this step:\n"
            f"{self.instructions.strip()}"
        )
        if self.constraint_contract is not None:
            rendered += (
                "\n\nFrozen Skill constraint contract (hard constraints must not be "
                "omitted or weakened):\n"
                + self.constraint_contract.model_dump_json(exclude_none=True)
            )
        return rendered


class SkillResolutionRequest(BaseModel):
    """Agent-independent inputs required to resolve Skills for one build step."""

    workflow_skill_id: str | None = None
    activated_skill_ids: list[str] = Field(default_factory=list)
    project_skill_locks: list[SkillLock] = Field(default_factory=list)
    declared_skill_ids: list[str] = Field(default_factory=list)
    capability_id: str
    output_type: str
    capability_skill_id: str | None = None
    constraint_contract: SkillConstraintContract | None = None
    require_constraint_contract: bool = True

