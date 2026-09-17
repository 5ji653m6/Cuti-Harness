from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import (
    ArtifactDependency,
    Build,
    BuildPlanRevision,
    BuildStep,
    ChangeRequest,
    ExportRecord,
    MediaArtifactVersion,
    PlanCheckpoint,
    Project,
    ProjectEvent,
    ProjectSessionBinding,
    ProjectSkillLock,
    ProjectVersion,
    RebuildPlan,
    ValidationResult,
    VideoSpecRevision,
)
from .repository import InMemoryVideoProjectRepository


class LocalJsonVideoProjectRepository(InMemoryVideoProjectRepository):
    """Crash-safe local persistence adapter for the reference repository.

    Production deployments continue to use Postgres. This adapter exists so a
    self-hosted checkout does not silently lose Projects, Session bindings,
    BuildSteps, remote operation ids, or draft Artifacts whenever Uvicorn is
    restarted. It deliberately reuses every transaction rule from the in-memory
    repository and only adds an atomic JSON durability boundary.
    """

    SNAPSHOT_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        super().__init__()
        self._load()

    @staticmethod
    def _items(values: dict[str, Any]) -> list[dict[str, Any]]:
        return [value.model_dump(mode="json") for value in values.values()]

    def _snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.SNAPSHOT_VERSION,
            "projects": self._items(self.projects),
            "versions": self._items(self.versions),
            "project_versions": dict(self.project_versions),
            "artifacts": {
                project_id: self._items(values)
                for project_id, values in self.artifacts.items()
            },
            "dependencies": {
                project_id: [item.model_dump(mode="json") for item in values]
                for project_id, values in self.dependencies.items()
            },
            "bindings": [item.model_dump(mode="json") for item in self.bindings.values()],
            "skill_locks": {
                project_id: self._items(values)
                for project_id, values in self.skill_locks.items()
            },
            "changes": self._items(self.changes),
            "plans": self._items(self.plans),
            "video_spec_revisions": self._items(self.video_spec_revisions),
            "project_spec_revisions": dict(self.project_spec_revisions),
            "plan_revisions": {
                plan_id: [item.model_dump(mode="json") for item in values]
                for plan_id, values in self.plan_revisions.items()
            },
            "checkpoints": self._items(self.checkpoints),
            "build_checkpoints": dict(self.build_checkpoints),
            "builds": self._items(self.builds),
            "build_steps": {
                build_id: self._items(values)
                for build_id, values in self.build_steps.items()
            },
            "validations": {
                build_id: [item.model_dump(mode="json") for item in values]
                for build_id, values in self.validations.items()
            },
            "exports": self._items(self.exports),
            "events": {
                project_id: [item.model_dump(mode="json") for item in values]
                for project_id, values in self.events.items()
            },
            "idempotency": [
                {"key": list(key), "value": value}
                for key, value in self.idempotency.items()
            ],
            "project_creation_idempotency": [
                {"key": list(key), "value": value}
                for key, value in self.project_creation_idempotency.items()
            ],
            "compatibility_runs": [
                {"key": list(key), "value": list(value)}
                for key, value in self.compatibility_runs.items()
            ],
        }

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = json.dumps(
            self._snapshot(), ensure_ascii=False, separators=(",", ":"),
        )
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _model_map(model, values: list[dict[str, Any]]) -> dict[str, Any]:
        parsed = [model.model_validate(item) for item in values]
        return {item.id: item for item in parsed}

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Video Runtime local state is unreadable: {self.path}"
            ) from exc
        if raw.get("schema_version") != self.SNAPSHOT_VERSION:
            raise RuntimeError(
                "unsupported Video Runtime local state schema: "
                f"{raw.get('schema_version')!r}"
            )

        self.projects = self._model_map(Project, raw.get("projects", []))
        self.versions = self._model_map(ProjectVersion, raw.get("versions", []))
        self.project_versions = defaultdict(list, raw.get("project_versions", {}))
        self.artifacts = defaultdict(dict, {
            project_id: self._model_map(MediaArtifactVersion, values)
            for project_id, values in raw.get("artifacts", {}).items()
        })
        self.dependencies = defaultdict(list, {
            project_id: [ArtifactDependency.model_validate(item) for item in values]
            for project_id, values in raw.get("dependencies", {}).items()
        })
        dependencies_repaired = self._repair_invalid_build_dependencies()
        bindings = [
            ProjectSessionBinding.model_validate(item)
            for item in raw.get("bindings", [])
        ]
        self.bindings = {
            (item.project_id, item.session_id): item for item in bindings
        }
        self.skill_locks = defaultdict(dict, {
            project_id: {
                item.skill_id: item
                for item in (ProjectSkillLock.model_validate(value) for value in values)
            }
            for project_id, values in raw.get("skill_locks", {}).items()
        })
        self.changes = self._model_map(ChangeRequest, raw.get("changes", []))
        self.plans = self._model_map(RebuildPlan, raw.get("plans", []))
        self.video_spec_revisions = self._model_map(
            VideoSpecRevision, raw.get("video_spec_revisions", []),
        )
        self.project_spec_revisions = defaultdict(
            list, raw.get("project_spec_revisions", {}),
        )
        self.plan_revisions = defaultdict(list, {
            plan_id: [BuildPlanRevision.model_validate(item) for item in values]
            for plan_id, values in raw.get("plan_revisions", {}).items()
        })
        self.checkpoints = self._model_map(
            PlanCheckpoint, raw.get("checkpoints", []),
        )
        self.build_checkpoints = defaultdict(
            list, raw.get("build_checkpoints", {}),
        )
        self.builds = self._model_map(Build, raw.get("builds", []))
        self.build_steps = defaultdict(dict, {
            build_id: {
                item.plan_step_id: item
                for item in (BuildStep.model_validate(value) for value in values)
            }
            for build_id, values in raw.get("build_steps", {}).items()
        })
        self.validations = defaultdict(list, {
            build_id: [ValidationResult.model_validate(item) for item in values]
            for build_id, values in raw.get("validations", {}).items()
        })
        self.exports = self._model_map(ExportRecord, raw.get("exports", []))
        self.events = defaultdict(list, {
            project_id: [ProjectEvent.model_validate(item) for item in values]
            for project_id, values in raw.get("events", {}).items()
        })
        self.idempotency = {
            tuple(item["key"]): item["value"]
            for item in raw.get("idempotency", [])
        }
        self.project_creation_idempotency = {
            tuple(item["key"]): item["value"]
            for item in raw.get("project_creation_idempotency", [])
        }
        self.compatibility_runs = {
            tuple(item["key"]): tuple(item["value"])
            for item in raw.get("compatibility_runs", [])
        }
        if dependencies_repaired:
            self._persist()

    def _repair_invalid_build_dependencies(self) -> bool:
        """Remove dependency shapes produced by the former replacement-alias bug.

        A build output cannot depend on itself, and a deterministic build-step edge
        cannot point from an artifact created after its target. Other relation types
        are left untouched because imported legacy provenance may not preserve time.
        """
        repaired = False
        for project_id, edges in list(self.dependencies.items()):
            artifacts = self.artifacts.get(project_id, {})
            kept: list[ArtifactDependency] = []
            for edge in edges:
                source = artifacts.get(edge.source_version_id)
                target = artifacts.get(edge.target_version_id)
                invalid = edge.source_version_id == edge.target_version_id
                invalid = invalid or (
                    edge.relation == "build_step_dependency"
                    and source is not None
                    and target is not None
                    and source.created_at > target.created_at
                )
                if invalid:
                    repaired = True
                else:
                    kept.append(edge)
            self.dependencies[project_id] = kept
        return repaired

    def _append_event(
        self, project_id: str, event_type: str, payload: dict,
    ) -> ProjectEvent:
        event = super()._append_event(project_id, event_type, payload)
        self._persist()
        return event

    async def stage_artifact(
        self, artifact: MediaArtifactVersion,
    ) -> MediaArtifactVersion:
        stored = await super().stage_artifact(artifact)
        self._persist()
        return stored

    async def remember_operation_result(
        self, project_id: str, operation: str, idempotency_key: str, result_id: str,
    ) -> None:
        await super().remember_operation_result(
            project_id, operation, idempotency_key, result_id,
        )
        self._persist()

    async def replace_operation_result(
        self, project_id: str, operation: str, idempotency_key: str, result_id: str,
    ) -> None:
        await super().replace_operation_result(
            project_id, operation, idempotency_key, result_id,
        )
        self._persist()

    async def remember_compatibility_run(
        self, *, user_id: str, idempotency_key: str,
        project_id: str, session_id: str,
    ) -> None:
        await super().remember_compatibility_run(
            user_id=user_id,
            idempotency_key=idempotency_key,
            project_id=project_id,
            session_id=session_id,
        )
        self._persist()

    async def close(self) -> None:
        self._persist()
