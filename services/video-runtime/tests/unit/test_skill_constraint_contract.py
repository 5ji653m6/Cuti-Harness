import pytest

from app.chat.v2.models import SkillConstraintContract, SkillHardConstraint
from app.orchestration.skills.constraint_contract import (
    SkillConstraintViolation,
    merge_and_validate_prompt,
)


def test_hard_constraints_are_merged_and_audited() -> None:
    contract = SkillConstraintContract(
        hard_constraints=[
            SkillHardConstraint(
                constraint_id="palette",
                skill_id="example-style",
                text="Use the exact restrained palette.",
                required_terms=["#020202"],
                required_fields={"palette": "#020202", "saturation": "0.23"},
            )
        ],
        guidance=["Prefer a cinematic composition."],
    )

    result = merge_and_validate_prompt("A hero in a station", contract)

    assert result.applied_skill_ids == ["example-style"]
    assert result.constraint_coverage["palette"]["covered"] is True
    assert "#020202" in result.final_prompt
    assert "0.23" in result.final_prompt
    assert "cinematic composition" not in result.final_prompt


def test_unrepresentable_hard_constraint_rejects_tool_call() -> None:
    contract = SkillConstraintContract(
        hard_constraints=[
            SkillHardConstraint(
                constraint_id="missing",
                skill_id="example-style",
                text="Preserve the exact identity.",
                required_terms=["IDENTITY_TOKEN_NOT_IN_CONTRACT_TEXT"],
            )
        ]
    )

    with pytest.raises(SkillConstraintViolation, match="uncovered hard Skill constraints"):
        merge_and_validate_prompt("A portrait", contract)
