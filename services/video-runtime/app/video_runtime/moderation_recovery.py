"""Bounded moderation repair using persisted plan replacement history."""
from __future__ import annotations

from .models import BuildStep, CheckpointResolution, RebuildPlan, RebuildPlanItem


def is_moderation(error: str | None) -> bool:
    from app.utils.error_classification import FailureCategory, classify_failure
    return classify_failure(error) == FailureCategory.CONTENT_MODERATION


def repair_history(plan: RebuildPlan, step_id: str) -> list[RebuildPlanItem]:
    parents = {item.superseded_by: item for item in plan.items if item.superseded_by}
    result = []
    while step_id in parents and step_id not in {item.step_id for item in result}:
        parent = parents[step_id]
        result.append(parent)
        step_id = parent.step_id
    return result


def failure_details(plan: RebuildPlan, item: RebuildPlanItem, state: BuildStep,
                    states: dict[str, BuildStep]) -> dict | None:
    if not state.error:
        return None
    from app.utils.error_classification import classify_failure
    history = repair_history(plan, item.step_id)
    used = sum(is_moderation(states[x.step_id].error) for x in history if x.step_id in states)
    return {
        "category": classify_failure(state.error).value,
        "raw_error": state.error,
        "task_id": item.step_id,
        "provider": item.parameters.get("provider"),
        "model": item.parameters.get("model"),
        "prompt": item.parameters.get("prompt"),
        "input_artifact_version_ids": item.input_artifact_version_ids,
        "repair_history": [{"task_id": x.step_id, "parameters": x.parameters,
                            "error": states[x.step_id].error if x.step_id in states else None}
                           for x in reversed(history)],
        "automatic_repairs_remaining": max(0, 1 - used),
        "requires_user_action": is_moderation(state.error) and used >= 1,
        "trigger_source": "unknown",
    }


def validate_moderation_patch(plan: RebuildPlan, states: dict[str, BuildStep],
                              resolution: CheckpointResolution) -> None:
    """Reject duplicate submissions and second repairs before a patch can commit."""
    rejected = [x for x in plan.items if x.step_id in states and is_moderation(states[x.step_id].error)]
    if not rejected:
        return
    mapping = resolution.replace_failed_step_ids
    by_id = {x.step_id: x for x in plan.items}
    proposed = {x.step_id: x for x in resolution.proposed_steps}
    if resolution.goal_satisfied and any(not x.superseded_by for x in rejected):
        raise ValueError("Content moderation remains unresolved; do not mark the requested work complete.")
    for candidate in resolution.proposed_steps:
        if candidate.action not in {"create", "rebuild"}:
            continue
        # A renamed task or changed model cannot turn rejected inputs into a new request.
        for old in rejected:
            if (candidate.parameters.get("prompt") == old.parameters.get("prompt")
                    and candidate.input_artifact_version_ids == old.input_artifact_version_ids
                    and candidate.capability == old.capability):
                raise ValueError("Content moderation: unchanged rejected prompt cannot be resubmitted.")
        if any(not x.superseded_by for x in rejected) and (
            "generate" in candidate.capability or candidate.capability in {x.capability for x in rejected}
        ):
            if candidate.step_id not in mapping.values():
                raise ValueError("Content moderation: use replace_failed_task_ids for a bounded repair before more generation.")
    for old_id, new_id in mapping.items():
        old = by_id.get(old_id)
        if old is None or old not in rejected or new_id not in proposed:
            continue
        details = failure_details(plan, old, states[old_id], states)
        if details["requires_user_action"]:
            raise ValueError("Content moderation repair budget exhausted (1/1); user must revise the request or reference assets.")
        new = proposed[new_id]
        if new.capability != old.capability:
            raise ValueError("Content moderation repair must preserve the generation capability.")
        reference_keys = {key for key in old.parameters.keys() | new.parameters.keys()
                          if any(token in key for token in ("image", "reference", "video_url", "audio_url"))}
        for key in {"provider", "model"} | reference_keys:
            if new.parameters.get(key) != old.parameters.get(key):
                raise ValueError(f"Content moderation repair must preserve {key}; request user input for substantive changes.")
        if new.input_artifact_version_ids != old.input_artifact_version_ids:
            raise ValueError("Content moderation repair must preserve reference artifacts; request user input to change them.")


def recovery_message(plan: RebuildPlan, item: RebuildPlanItem, state: BuildStep,
                     states: dict[str, BuildStep]) -> str | None:
    details = failure_details(plan, item, state, states)
    if details and details["category"] == "content_moderation":
        if item.superseded_by:
            replacement = states.get(item.superseded_by)
            if replacement and replacement.status == "completed":
                return "Content moderation: repair succeeded"
            if replacement and replacement.status in {"pending", "running", "waiting_external"}:
                return "Content moderation: repairing (1/1)"
        return ("Content moderation: user revision required" if details["requires_user_action"]
                else "Content moderation: awaiting Agent review")
    return None


MODERATION_INSTRUCTION = (
    "Content moderation recovery: the provider may reject text, images or generated content; "
    "the specific trigger is unknown unless explicitly returned. You may make ONE compliant "
    "repair using replace_failed_task_ids: clarify ambiguous wording or remove your own additions "
    "not requested by the user. Preserve the user's core plot, characters, references, model and "
    "provider. Never evade a rejection through euphemisms, hidden changes or provider switching. "
    "Inspect failure.repair_history and automatic_repairs_remaining. If substantive changes are "
    "needed, or the repair is rejected, cancel pending dependent tasks, acknowledge the checkpoint "
    "without goal_satisfied, and explain the exact blocker and ask the user to revise the content "
    "or references. Do not keep submitting paid attempts or call missing deliverables complete."
)
