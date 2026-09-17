"""Expand failed-task replacement into append-only tasks and pending cancellations."""
from .plan_utils import topological_steps
from .models import CheckpointResolution, RebuildPlan, BuildStep
from .step_references import remap_step_parameters


def expand_repair(plan: RebuildPlan, states: dict[str, BuildStep], resolution: CheckpointResolution) -> CheckpointResolution:
    """Clone unstarted descendants with rewired dependencies; retain execution history."""
    result = resolution.model_copy(deep=True)
    mapping = dict(result.replace_failed_step_ids)
    proposed = {item.step_id: item for item in result.proposed_steps}
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("each failed task requires a distinct replacement")
    for old, new in mapping.items():
        if old not in states or states[old].status != "failed":
            raise ValueError(f"replacement requires a failed task: {old}")
        if new in states or new not in proposed:
            raise ValueError(f"replacement requires a new proposed task: {new}")
        # A replacement is a new operation, never a reconciliation of the failed one.
        proposed[new].idempotency_key = ""
        proposed[new].parameters.pop("remote_operation_id", None)
    for item in topological_steps(plan.items):
        if item.step_id in mapping or not set(item.depends_on).intersection(mapping):
            continue
        state = states[item.step_id]
        if state.status == "cancelled":
            continue
        if state.status != "pending":
            raise ValueError(f"cannot automatically replace started descendant: {item.step_id}")
        clone = item.model_copy(deep=True)
        clone.step_id = f"{item.step_id}:repair:{plan.current_revision + 1}"
        if clone.step_id in states or clone.step_id in proposed:
            raise ValueError(f"repair task id collision: {clone.step_id}")
        mapping[item.step_id] = clone.step_id
        clone.idempotency_key = ""
        clone.parameters.pop("remote_operation_id", None)
        proposed[clone.step_id] = clone
        result.proposed_steps.append(clone)
        result.cancel_step_ids.append(item.step_id)
    for item in result.proposed_steps:
        item.depends_on = [mapping.get(dependency, dependency) for dependency in item.depends_on]
        item.parameters = remap_step_parameters(item.parameters, mapping)
    result.cancel_step_ids = list(dict.fromkeys(result.cancel_step_ids))
    return result
