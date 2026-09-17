from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from .models import RebuildPlanItem


class BuildPlanValidationError(ValueError):
    pass


def topological_steps(items: Iterable[RebuildPlanItem]) -> list[RebuildPlanItem]:
    """Return a stable topological order and reject missing or cyclic dependencies."""
    steps = list(items)
    by_id = {item.step_id: item for item in steps}
    if len(by_id) != len(steps):
        raise BuildPlanValidationError("build step ids must be unique")
    missing = sorted({dep for item in steps for dep in item.depends_on if dep not in by_id})
    if missing:
        raise BuildPlanValidationError(
            f"build step dependencies do not exist: {', '.join(missing)}"
        )
    incoming = {item.step_id: len(set(item.depends_on)) for item in steps}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for item in steps:
        for dependency in set(item.depends_on):
            outgoing[dependency].append(item.step_id)
    queue = deque(
        sorted(
            (step_id for step_id, count in incoming.items() if count == 0),
            key=lambda value: (by_id[value].order or 0, value),
        )
    )
    ordered: list[RebuildPlanItem] = []
    while queue:
        step_id = queue.popleft()
        ordered.append(by_id[step_id])
        for target in outgoing[step_id]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
        queue = deque(sorted(queue, key=lambda value: (by_id[value].order or 0, value)))
    if len(ordered) != len(steps):
        raise BuildPlanValidationError("build plan contains a dependency cycle")
    return ordered
