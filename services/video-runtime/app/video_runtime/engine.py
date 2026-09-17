from __future__ import annotations

from collections import defaultdict, deque

from .models import (
    ArtifactDependency,
    ArtifactInvalidationPolicy,
    ChangeRequest,
    MediaArtifactVersion,
    RebuildPlan,
    RebuildPlanItem,
)


class ArtifactDependencyCycle(ValueError):
    pass


class IncrementalBuildEngine:
    """Deterministic artifact invalidation and rebuild planning."""

    def preview(
        self,
        *,
        change: ChangeRequest,
        artifacts: list[MediaArtifactVersion],
        dependencies: list[ArtifactDependency],
    ) -> RebuildPlan:
        by_id = {artifact.id: artifact for artifact in artifacts}
        roots = set(change.target_artifact_version_ids)
        unknown = roots - by_id.keys()
        if unknown:
            raise LookupError(f"unknown target artifact versions: {sorted(unknown)}")

        children: dict[str, list[ArtifactDependency]] = defaultdict(list)
        for edge in dependencies:
            if edge.source_version_id in by_id and edge.target_version_id in by_id:
                children[edge.source_version_id].append(edge)

        stale = set(roots)
        validate: set[str] = set()
        queue = deque((artifact_id, True) for artifact_id in sorted(roots))
        seen_states: set[tuple[str, bool]] = set()
        while queue:
            source_id, source_is_stale = queue.popleft()
            state = (source_id, source_is_stale)
            if state in seen_states:
                continue
            seen_states.add(state)
            for edge in children[source_id]:
                target_id = edge.target_version_id
                policy = edge.invalidation_policy
                if source_is_stale and policy == ArtifactInvalidationPolicy.HARD:
                    if target_id not in stale:
                        stale.add(target_id)
                        validate.discard(target_id)
                    queue.append((target_id, True))
                elif policy in {ArtifactInvalidationPolicy.HARD, ArtifactInvalidationPolicy.VALIDATE}:
                    if target_id not in stale:
                        validate.add(target_id)
                        queue.append((target_id, False))

        rebuild_order = self._topological_subset(stale, dependencies)
        reused = set(by_id) - stale - validate
        cost = sum(float(by_id[item].metadata.get("estimated_cost", 1.0)) for item in stale)
        order_index = {artifact_id: index for index, artifact_id in enumerate(rebuild_order)}
        items = [
            RebuildPlanItem(
                artifact_version_id=artifact_id,
                action="rebuild",
                order=order_index[artifact_id],
                reason="changed directly" if artifact_id in roots else "hard downstream dependency",
            )
            for artifact_id in rebuild_order
        ]
        items.extend(
            RebuildPlanItem(artifact_version_id=item, action="validate", reason="dependency requires validation")
            for item in sorted(validate)
        )
        items.extend(
            RebuildPlanItem(artifact_version_id=item, action="reuse", reason="unaffected by this change")
            for item in sorted(reused)
        )
        return RebuildPlan(
            project_id=change.project_id,
            change_request_id=change.id,
            base_project_version_id=change.base_project_version_id,
            items=items,
            estimated_cost=cost,
        )

    @staticmethod
    def _topological_subset(
        selected: set[str], dependencies: list[ArtifactDependency],
    ) -> list[str]:
        indegree = {item: 0 for item in selected}
        children: dict[str, list[str]] = defaultdict(list)
        for edge in dependencies:
            if edge.source_version_id in selected and edge.target_version_id in selected:
                children[edge.source_version_id].append(edge.target_version_id)
                indegree[edge.target_version_id] += 1
        ready = deque(sorted(item for item, degree in indegree.items() if degree == 0))
        ordered: list[str] = []
        while ready:
            current = ready.popleft()
            ordered.append(current)
            for child in sorted(children[current]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(ordered) != len(selected):
            raise ArtifactDependencyCycle("artifact dependency graph contains a cycle")
        return ordered
