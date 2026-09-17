from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from .models import SkillConstraintContract


class SkillConstraintViolation(ValueError):
    """Raised before a vendor call when a frozen Skill contract is not covered."""


_ACTIVE_CONTRACT: ContextVar[SkillConstraintContract | None] = ContextVar(
    "active_skill_constraint_contract", default=None
)


def activate_constraint_contract(
    contract: SkillConstraintContract | None,
) -> Token[SkillConstraintContract | None]:
    return _ACTIVE_CONTRACT.set(contract)


def reset_constraint_contract(token: Token[SkillConstraintContract | None]) -> None:
    _ACTIVE_CONTRACT.reset(token)


def active_constraint_contract() -> SkillConstraintContract | None:
    return _ACTIVE_CONTRACT.get()


@dataclass(frozen=True)
class ConstraintMergeResult:
    final_prompt: str
    applied_skill_ids: list[str]
    constraint_coverage: dict[str, Any]


def merge_and_validate_prompt(
    prompt: str,
    contract: SkillConstraintContract | dict[str, Any] | None,
) -> ConstraintMergeResult:
    """Deterministically append hard requirements and verify their coverage.

    Classification is deliberately not done here: the coordinator model decides
    what is hard versus guidance.  This boundary only executes the frozen contract.
    """
    parsed = (
        contract
        if isinstance(contract, SkillConstraintContract)
        else SkillConstraintContract.model_validate(contract or {})
    )
    base = (prompt or "").strip()
    blocks = [base] if base else []
    coverage: dict[str, Any] = {}
    applied: list[str] = []

    for item in parsed.hard_constraints:
        block_parts = [item.text.strip()]
        block_parts.extend(
            f"{name}: {value}" for name, value in item.required_fields.items()
            if str(name).strip() and str(value).strip()
        )
        block = "\n".join(part for part in block_parts if part)
        if block:
            blocks.append(block)
        if item.skill_id not in applied:
            applied.append(item.skill_id)

    final_prompt = "\n\nHARD CONSTRAINTS (must be preserved exactly):\n".join(
        [blocks[0], "\n".join(f"- {value}" for value in blocks[1:])]
    ) if len(blocks) > 1 else (blocks[0] if blocks else "")

    missing: list[str] = []
    for item in parsed.hard_constraints:
        required = [term.strip() for term in item.required_terms if term.strip()]
        required.extend(str(value).strip() for value in item.required_fields.values() if str(value).strip())
        absent = [term for term in required if term.casefold() not in final_prompt.casefold()]
        covered = item.text.strip().casefold() in final_prompt.casefold() and not absent
        coverage[item.constraint_id] = {
            "skill_id": item.skill_id,
            "covered": covered,
            "missing_terms": absent,
        }
        if not covered:
            missing.append(item.constraint_id)

    if missing:
        raise SkillConstraintViolation(
            "image tool call rejected: uncovered hard Skill constraints: "
            + ", ".join(missing)
        )
    return ConstraintMergeResult(final_prompt, applied, coverage)
