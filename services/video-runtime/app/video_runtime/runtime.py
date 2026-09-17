from __future__ import annotations

import asyncio
import json
import os
import time
from copy import deepcopy
from typing import Any, Protocol

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for

from .engine import IncrementalBuildEngine
from .models import (
    ArtifactDependency,
    Build,
    BuildPlanRevision,
    BuildStep,
    CheckpointResolution,
    ChangeRequest,
    ExportRecord,
    MediaCapabilityContract,
    MediaEditOperation,
    MediaArtifactVersion,
    PlanCheckpoint,
    Project,
    ProjectIntent,
    ProjectSessionBinding,
    ProjectSkillLock,
    ProjectVersion,
    RebuildPlan,
    RebuildPlanItem,
    ValidationResult,
    VideoSpec,
    VideoSpecRevision,
    now,
)
from .plan_utils import topological_steps
from .video_generation_contracts import validate_video_generation_steps
from .repository import InMemoryVideoProjectRepository
from .plugins import PluginContext, VideoPluginRegistry
from .capabilities import RuntimeCapabilityRegistry
from .execution import CapabilityExecutionGateway
from .security import CapabilityGrant, CapabilityGrantSigner
from .skills import VideoSkillRuntime, default_video_skill_runtime
from .step_references import STEP_REFERENCE_PARAMETER_KEYS as _STEP_REFERENCE_PARAMETER_KEYS
from app.orchestration.skills import (
    ResolvedSkillRef,
    SkillContext,
    SkillResolutionRequest,
)
from app.domain.skills.service import make_skill_lock
from app.capabilities.models import canonical_capability_id


_CHECKPOINT_METADATA_KEYS = {
    "content",
    "duration",
    "duration_seconds",
    "lyrics",
    "transcript",
    "beats",
    "segments",
    "words",
    "width",
    "height",
    "plan_step_id",
    "language",
    "language_contract",
    "language_validation",
}

_MEDIA_REFERENCE_PARAMETER_KEYS = frozenset({
    "images", "image_urls", "reference_images", "reference_urls",
    "input_image_urls", "videos", "video_urls", "reference_videos",
    "audios", "audio_urls", "reference_audios",
    "start_image_url", "start_image", "first_frame_url", "first_frame",
    "continuity_frame_url", "end_image_url", "end_image", "last_image_url",
    "last_image", "audio_url", "video_url",
})

_SHARED_IMAGE_REFERENCE_TYPES = frozenset({
    "character_reference", "character_setting_reference",
    "scene_reference", "scene_setting_reference",
    "product_reference", "product_setting_reference",
})

_FINAL_VIDEO_ARTIFACT_TYPES = frozenset({
    "final_video", "video_assembled", "video_mixed",
})

_FINAL_VIDEO_CAPABILITIES = frozenset({
    "media.concat", "media.mix_audio", "media.subtitle_burn",
    "media.hyperframes_caption", "media.hyperframes_render",
})

_CHECKPOINT_TASK_PARAMETER_KEYS = frozenset({
    "prompt", "negative_prompt", "duration", "duration_seconds",
    "segment_duration_seconds", "aspect_ratio", "resolution", "width", "height",
    "provider", "model", "generation_mode", "video_generation_mode",
    "workflow_mode", "shot_workflow_mode", "continuity_mode",
    "native_audio", "generate_audio", "dialogue", "audio_cues",
    "reference_images", "reference_videos", "start_image_url", "end_image_url",
})


def _implicit_artifact_inputs(
    parameters: dict[str, Any], known_artifact_version_ids: set[str],
) -> list[str]:
    """Recognize ArtifactVersion ids used in provider-facing media fields.

    Cuti planners historically placed ids directly in ``reference_images`` and
    sibling fields.  Treat those values as explicit task inputs so dependency
    wiring and URI resolution happen before provider dispatch.  Unknown strings
    remain ordinary URLs and are validated by the execution envelope.
    """
    result: list[str] = []
    for key in _MEDIA_REFERENCE_PARAMETER_KEYS:
        value = parameters.get(key)
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            candidate_id = str(candidate) if isinstance(candidate, str) else ""
            if candidate_id in known_artifact_version_ids and candidate_id not in result:
                result.append(candidate_id)
    return result


def _parameter_step_references(
    parameters: dict[str, Any], known_step_ids: set[str],
) -> list[str]:
    """Return provider step selectors that must also be DAG dependencies."""
    result: list[str] = []
    unknown: list[str] = []
    for key in _STEP_REFERENCE_PARAMETER_KEYS:
        value = parameters.get(key)
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            step_id = str(candidate) if isinstance(candidate, str) else ""
            if not step_id:
                continue
            if step_id not in known_step_ids:
                unknown.append(step_id)
            elif step_id not in result:
                result.append(step_id)
    if unknown:
        raise ValueError(
            "provider reference parameters name unknown tasks: "
            + ", ".join(dict.fromkeys(unknown))
        )
    return result


def _bind_shared_video_references(
    steps: list[RebuildPlanItem], proposed_steps: list[RebuildPlanItem],
) -> None:
    """Bind declared shared identity/setting references to Agent-authored video tasks.

    The Agent remains responsible for selecting references when a shot uses a
    subset. ``shared_reference_images`` is the explicit policy for the common
    Cuti case where every generated identity/setting sheet applies to every
    segment; omitting the mechanical fields must not silently degrade to T2V.
    """
    reference_steps = [
        item.step_id for item in steps
        if item.action in {"create", "reuse"}
        and not item.superseded_by
        and (
            item.output_artifact_type.strip().casefold() in _SHARED_IMAGE_REFERENCE_TYPES
            or str(item.parameters.get("artifact_role") or "").strip().casefold()
            in _SHARED_IMAGE_REFERENCE_TYPES
        )
    ]
    video_capabilities = {
        "atomic.video.generate", "api.provider.generate", "api.ark_protocol.generate",
    }
    known_ids = {item.step_id for item in steps}
    for item in proposed_steps:
        if item.action != "create" or item.capability not in video_capabilities:
            continue
        dependency_refs = _parameter_step_references(item.parameters, known_ids)
        if str(item.parameters.get("continuity_mode") or "").casefold() == "shared_reference_images":
            shared_refs = [
                step_id for step_id in reference_steps if step_id != item.step_id
            ]
            if not shared_refs and not dependency_refs and not item.input_artifact_version_ids and not any(
                item.parameters.get(key) for key in _MEDIA_REFERENCE_PARAMETER_KEYS
            ):
                raise ValueError(
                    f"PlanPatch video task {item.step_id} requests shared_reference_images "
                    "but no identity or setting reference is available"
                )
            if shared_refs:
                existing_shared = item.parameters.get("reference_from_steps") or []
                if isinstance(existing_shared, str):
                    existing_shared = [existing_shared]
                if not isinstance(existing_shared, list):
                    raise ValueError("reference_from_steps must be an array of task ids")
                item.parameters["reference_from_steps"] = list(dict.fromkeys([
                    *existing_shared, *shared_refs,
                ]))
                dependency_refs = list(dict.fromkeys([*dependency_refs, *shared_refs]))
        item.depends_on = list(dict.fromkeys([*item.depends_on, *dependency_refs]))


def uploaded_source_must_be_declared(item: RebuildPlanItem) -> None:
    """Reject image tasks that depend on an upload but never declare it as media.

    ``depends_on`` only orders the DAG. Identity sheets must pass the source
    through ``reference_from_steps`` or ``images``; otherwise the provider can
    run as text-to-image while the prompt still says "keep the subject".
    """
    if item.action != "create" or item.capability != "atomic.image.generate":
        return
    source_deps = [
        str(dep) for dep in item.depends_on if str(dep).startswith("source-")
    ]
    if not source_deps:
        return
    params = item.parameters if isinstance(item.parameters, dict) else {}
    declared: list[str] = []
    for key in (
        "reference_from_steps", "character_reference_from_steps",
        "images", "image_urls", "reference_images",
    ):
        value = params.get(key)
        if isinstance(value, list):
            declared.extend(str(entry) for entry in value if entry)
        elif isinstance(value, str) and value.strip():
            declared.append(value.strip())
    if not declared:
        raise ValueError(
            f"PlanPatch task {item.step_id} depends on uploaded source media but "
            "did not set reference_from_steps or images; depends_on only schedules "
            "the task"
        )


def _bounded_checkpoint_value(value: Any, *, limit: int = 16_000) -> Any:
    """Keep planner inputs useful while preventing an Artifact from flooding a prompt."""
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= limit:
        return value
    return {
        "truncated": True,
        "preview": encoded[:limit],
        "original_characters": len(encoded),
    }


def _checkpoint_task_parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Expose creative execution context to the planner without leaking credentials.

    Provider request dictionaries can contain keys and tokens, so checkpoints must not
    echo them wholesale.  This allowlist preserves the final prompt and continuity/model
    choices that a later PlanPatch needs in order to remain as detailed as earlier clips.
    """
    if not isinstance(parameters, dict):
        return {}
    return {
        key: _bounded_checkpoint_value(value)
        for key, value in parameters.items()
        if key in _CHECKPOINT_TASK_PARAMETER_KEYS
    }


def _artifact_generation_context(metadata: dict[str, Any]) -> dict[str, Any]:
    """Project only safe, provider-relevant fields from an Artifact into checkpoints."""
    context: dict[str, Any] = {}
    for container_name in ("resolved_generation_parameters", "generation_parameters"):
        container = metadata.get(container_name)
        if isinstance(container, dict):
            for key, value in _checkpoint_task_parameters(container).items():
                context.setdefault(key, value)
    for key in ("final_prompt", "generated_prompt", "generation_prompt"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip() and "prompt" not in context:
            context["prompt"] = _bounded_checkpoint_value(value.strip())
    return context


def _checkpoint_artifact_summary(
    artifact: MediaArtifactVersion,
    *,
    issues: list[Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        key: _bounded_checkpoint_value(value)
        for key, value in artifact.metadata.items()
        if key in _CHECKPOINT_METADATA_KEYS
    }
    generation_context = _artifact_generation_context(artifact.metadata)
    if generation_context:
        metadata["generation_context"] = generation_context
    summary: dict[str, Any] = {
        "id": artifact.id,
        "artifact_id": artifact.artifact_id,
        "type": artifact.type,
        "title": artifact.title,
        "summary": artifact.summary,
        "uri": artifact.uri,
        "metadata": metadata,
    }
    if issues is not None:
        summary["issues"] = issues
    return summary


def _merge_spec_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge object sections recursively; arrays and scalar values replace atomically."""
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_spec_patch(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _artifact_matches_media_type(actual: str, accepted: list[str]) -> bool:
    """Match Cuti's historical artifact names by media family, not Workflow."""
    normalized = actual.lower()
    for expected in accepted:
        expected = expected.lower()
        if expected == "*" or normalized == expected:
            return True
        if expected == "video" and "video" in normalized:
            return True
        if expected == "image" and any(token in normalized for token in ("image", "frame", "keyframe")):
            return True
        if expected == "audio" and any(
            token in normalized for token in ("audio", "music", "narration", "bgm", "sound")
        ):
            return True
        if expected == "subtitle" and any(token in normalized for token in ("subtitle", "caption")):
            return True
        if expected == "transcript" and "transcript" in normalized:
            return True
    return False


class BuildStepExecutor(Protocol):
    async def rebuild_artifact(
        self,
        *,
        build: Build,
        source: MediaArtifactVersion,
        completed_replacements: dict[str, MediaArtifactVersion],
        idempotency_key: str,
    ) -> MediaArtifactVersion: ...

    async def execute_plan_step(
        self,
        *,
        build: Build,
        step: RebuildPlanItem,
        completed_artifacts: dict[str, MediaArtifactVersion],
        idempotency_key: str,
        report_remote_operation: Any | None = None,
    ) -> MediaArtifactVersion: ...


class PluginBuildStepExecutor:
    """Resolves artifact rebuild metadata to one authorized plugin capability."""

    def __init__(
        self,
        capabilities: RuntimeCapabilityRegistry,
        signer: CapabilityGrantSigner,
    ) -> None:
        self.capabilities = capabilities
        self.signer = signer

    async def rebuild_artifact(
        self,
        *,
        build: Build,
        source: MediaArtifactVersion,
        completed_replacements: dict[str, MediaArtifactVersion],
        idempotency_key: str,
    ) -> MediaArtifactVersion:
        capability = canonical_capability_id(
            str(source.metadata.get("rebuild_capability") or "").strip()
        )
        if not capability:
            raise ValueError(f"artifact has no rebuild_capability: {source.id}")
        entry = self.capabilities.describe(capability)
        loaded = self.capabilities.gateway.plugins.get(entry.plugin_id)
        permissions = loaded.manifest.permissions
        grant = CapabilityGrant(
            project_id=build.project_id,
            session_id=build.session_id or "system-recovery",
            user_id=build.user_id or "system-recovery",
            plugin_id=entry.plugin_id,
            capability=capability,
            allowed_capabilities=[capability],
            allowed_domains=list(permissions.network_domains),
            max_cost_usd=permissions.max_cost_usd,
            timeout_seconds=int(source.metadata.get("timeout_seconds") or 3600),
            max_concurrency=int(source.metadata.get("max_concurrency") or 1),
            max_retries=int(source.metadata.get("max_retries") or 0),
            idempotency_key=idempotency_key,
            audit_id=f"build:{build.id}:{source.id}",
            nonce=f"{build.id}:{source.id}",
            expires_at=int(time.time()) + 7200,
        )
        result = await self.capabilities.execute(
            grant_token=self.signer.issue(grant),
            project_id=grant.project_id,
            session_id=grant.session_id,
            user_id=grant.user_id,
            capability=capability,
            payload={
                "build": build.model_dump(mode="json"),
                "source": source.model_dump(mode="json"),
                "completed_replacements": {
                    key: value.model_dump(mode="json")
                    for key, value in completed_replacements.items()
                },
            },
            cancellation_id=build.id,
        )
        if isinstance(result, MediaArtifactVersion):
            return result
        return MediaArtifactVersion.model_validate(result)

    async def execute_plan_step(
        self,
        *,
        build: Build,
        step: RebuildPlanItem,
        completed_artifacts: dict[str, MediaArtifactVersion],
        idempotency_key: str,
        report_remote_operation: Any | None = None,
    ) -> MediaArtifactVersion:
        if not step.capability:
            raise ValueError(f"build step has no capability: {step.step_id}")
        capability = canonical_capability_id(step.capability)
        entry = self.capabilities.describe(capability)
        loaded = self.capabilities.gateway.plugins.get(entry.plugin_id)
        permissions = loaded.manifest.permissions
        grant = CapabilityGrant(
            project_id=build.project_id,
            session_id=build.session_id or "system-recovery",
            user_id=build.user_id or "system-recovery",
            plugin_id=entry.plugin_id,
            capability=capability,
            allowed_capabilities=[capability],
            allowed_domains=list(permissions.network_domains),
            max_cost_usd=permissions.max_cost_usd,
            timeout_seconds=int(step.parameters.get("timeout_seconds") or 3600),
            max_concurrency=int(step.parameters.get("max_concurrency") or 1),
            max_retries=int(step.parameters.get("max_retries") or 1),
            idempotency_key=idempotency_key,
            audit_id=f"build:{build.id}:{step.step_id}",
            nonce=f"{build.id}:{step.step_id}",
            expires_at=int(time.time()) + 7200,
        )
        result = await self.capabilities.execute(
            grant_token=self.signer.issue(grant),
            project_id=grant.project_id,
            session_id=grant.session_id,
            user_id=grant.user_id,
            capability=capability,
            payload={
                "build": build.model_dump(mode="json"),
                "step": step.model_dump(mode="json"),
                "completed_artifacts": {
                    key: value.model_dump(mode="json")
                    for key, value in completed_artifacts.items()
                },
            },
            cancellation_id=build.id,
            report_remote_operation=report_remote_operation,
        )
        if isinstance(result, MediaArtifactVersion):
            return result
        return MediaArtifactVersion.model_validate(result)


class VideoBuildRuntime:
    """Project facade that keeps LLM planning outside deterministic build state."""

    def __init__(
        self,
        repository: Any | None = None,
        engine: IncrementalBuildEngine | None = None,
        plugins: VideoPluginRegistry | None = None,
        skill_runtime: VideoSkillRuntime | None = None,
        staged_planning_enabled: bool | None = None,
        continuous_plan_patch_enabled: bool | None = None,
        max_parallel_generation_tasks: int | None = None,
    ) -> None:
        self.repo = repository or InMemoryVideoProjectRepository()
        self.engine = engine or IncrementalBuildEngine()
        self.plugins = plugins or VideoPluginRegistry()
        self.skills = skill_runtime or default_video_skill_runtime()
        self.staged_planning_enabled = (
            staged_planning_enabled
            if staged_planning_enabled is not None
            else os.getenv("VIDEO_STAGED_PLANNING_ENABLED", "false").strip().lower()
            in {"1", "true", "yes"}
        )
        self.continuous_plan_patch_enabled = (
            continuous_plan_patch_enabled
            if continuous_plan_patch_enabled is not None
            else os.getenv("VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED", "false").strip().lower()
            in {"1", "true", "yes"}
        )
        # Keep the established Cuti deployment limit as the global safety cap;
        # a Workflow may declare a stricter limit but may not exceed this one.
        configured_parallelism = (
            max_parallel_generation_tasks
            if max_parallel_generation_tasks is not None
            else int(os.getenv("DEEP_AGENT_V2_MAX_PARALLEL_GENERATION_TASKS", "2"))
        )
        self.max_parallel_generation_tasks = max(1, configured_parallelism)
        self._default_executor: BuildStepExecutor | None = None
        self._grant_signer: CapabilityGrantSigner | None = None
        self._build_tasks: dict[str, asyncio.Task] = {}
        self._continuous_wakes: dict[str, asyncio.Event] = {}
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self.session_control_locks: dict[str, asyncio.Lock] = {}

    async def create_project(
        self, *, user_id: str, title: str, idempotency_key: str | None = None,
    ) -> tuple[Project, ProjectVersion]:
        project = Project(user_id=user_id, title=title)
        if idempotency_key:
            return await self.repo.create_project_idempotently(project, idempotency_key)
        return await self.repo.create_project(project)

    async def bind_session(self, *, project_id: str, session_id: str, user_id: str) -> ProjectSessionBinding:
        return await self.repo.bind_session(ProjectSessionBinding(
            project_id=project_id, session_id=session_id, user_id=user_id,
        ))

    async def list_project_skill_locks(self, project_id: str) -> list[ProjectSkillLock]:
        return await self.repo.list_project_skill_locks(project_id)

    async def set_project_skill_enabled(
        self,
        *,
        project_id: str,
        skill_id: str,
        enabled: bool,
    ) -> ProjectSkillLock:
        if not self.skills.catalog.has(skill_id):
            raise LookupError(f"unknown Skill: {skill_id}")
        metadata = self.skills.catalog.load(skill_id).metadata
        if enabled and not metadata.enabled:
            raise ValueError(f"Skill is disabled: {skill_id}")
        raw = dict(metadata.metadata or {})
        if enabled and raw.get("kind") == "workflow":
            for existing in await self.repo.list_project_skill_locks(project_id):
                if not existing.enabled or existing.skill_id == skill_id:
                    continue
                if not self.skills.catalog.has(existing.skill_id):
                    continue
                existing_metadata = self.skills.catalog.load(existing.skill_id).metadata
                if (existing_metadata.metadata or {}).get("kind") == "workflow":
                    await self.repo.upsert_project_skill_lock(
                        existing.model_copy(update={"enabled": False}),
                    )
        lock = ProjectSkillLock.model_validate(
            make_skill_lock(project_id, metadata).model_dump() | {"enabled": enabled},
        )
        return await self.repo.upsert_project_skill_lock(lock)

    async def reload_skills(self) -> int:
        from .skill_workflows import reload_workflow_skills

        await reload_workflow_skills(self.plugins, self.skills)
        self.refresh_plugin_execution()
        return len(self.skills.catalog.list_metadata())

    async def _apply_project_skill_locks(
        self,
        project_id: str,
        video_spec: VideoSpec | ProjectIntent,
    ) -> VideoSpec | ProjectIntent:
        enabled = [
            item for item in await self.repo.list_project_skill_locks(project_id)
            if item.enabled
        ]
        workflow_id = video_spec.workflow_id
        activated = list(video_spec.activated_skill_ids)
        for lock in enabled:
            if not self.skills.catalog.has(lock.skill_id):
                raise LookupError(f"project Skill is no longer installed: {lock.skill_id}")
            metadata = self.skills.catalog.load(lock.skill_id).metadata
            kind = (metadata.metadata or {}).get("kind")
            if kind != "workflow" and lock.skill_id not in activated:
                activated.append(lock.skill_id)
        return video_spec.model_copy(update={
            "workflow_id": workflow_id,
            "activated_skill_ids": activated,
        })

    async def preview_change(
        self,
        *,
        project_id: str,
        description: str,
        target_artifact_version_ids: list[str],
        idempotency_key: str | None = None,
    ) -> RebuildPlan:
        if idempotency_key:
            existing_id = await self.repo.get_operation_result(
                project_id, "preview", idempotency_key,
            )
            if existing_id is not None:
                return await self.repo.get_plan(existing_id)
        project = await self.repo.get_project(project_id)
        change = ChangeRequest(
            project_id=project_id,
            base_project_version_id=project.current_version_id,
            description=description,
            target_artifact_version_ids=target_artifact_version_ids,
        )
        if self.staged_planning_enabled and self.continuous_plan_patch_enabled:
            return await self._plan_dynamic_edit(change, idempotency_key)
        context = PluginContext(project_id=project_id, values={"change_request": change})
        for loaded in self.plugins.loaded:
            await loaded.implementation.before_plan(context)
        plan = self.engine.preview(
            change=change,
            artifacts=await self.repo.current_artifacts(project_id),
            dependencies=await self._editable_dependencies(project_id),
        )
        await self._restore_edit_steps(plan)
        for loaded in self.plugins.loaded:
            plan = await loaded.implementation.after_plan(context, plan)
        await self._resolve_plan_skills(plan)
        return await self.repo.save_change_and_plan(change, plan, idempotency_key)

    async def _plan_dynamic_edit(
        self, change: ChangeRequest, idempotency_key: str | None,
    ) -> RebuildPlan:
        """Continue edits through the same task-feedback loop as a new user goal.

        Selected artifacts are facts, not automatic provider reference inputs.
        The Agent authors the executable patch from the requested edits; no
        workflow compiler reconstructs a fixed DAG from old generation recipes.
        """
        project = await self.repo.get_project(change.project_id)
        artifacts = await self.repo.current_artifacts(change.project_id)
        for version_id in change.target_artifact_version_ids:
            await self.repo.get_artifact(change.project_id, version_id)
        version = await self.repo.get_project_version(change.base_project_version_id)
        content: dict[str, Any] = {}
        if version.video_spec_revision_id:
            content = (await self.repo.get_video_spec_revision(version.video_spec_revision_id)).content
        if not content:
            spec = next((item for item in artifacts if item.type == "video_spec"), None)
            if spec and isinstance(spec.metadata.get("content"), dict):
                content = spec.metadata["content"]
        fields = {key: deepcopy(value) for key, value in content.items()
                  if key in ProjectIntent.model_fields and key != "constraints"}
        fields.setdefault("title", project.title)
        fields.setdefault("workflow_id", "")
        if not fields["workflow_id"]:
            for build in reversed(await self.repo.list_builds(project.id)):
                previous = await self.repo.get_plan(build.plan_id)
                if previous.workflow_id:
                    fields["workflow_id"] = previous.workflow_id
                    break
        fields["brief"] = change.description or json.dumps(change.edits, ensure_ascii=False) or "Edit selected artifacts"
        fields["constraints"] = {
            "edit_existing_project": True,
            "edits": deepcopy(change.edits),
            "target_artifact_version_ids": list(change.target_artifact_version_ids),
            "previous_video_spec": {key: deepcopy(value) for key, value in content.items()
                                    if key != "constraints"},
            "preserve_existing_artifact_version_ids": [item.id for item in artifacts],
        }
        return await self.plan_project(
            project_id=project.id, base_project_version_id=change.base_project_version_id,
            project_intent=ProjectIntent.model_validate(fields),
            idempotency_key="dynamic-edit:" + (idempotency_key or change.id),
        )

    async def _editable_dependencies(self, project_id: str) -> list[ArtifactDependency]:
        """Recover selected input edges retained in recipes after output-only version changes."""
        artifacts = await self.repo.current_artifacts(project_id)
        edges = await self.repo.current_dependencies(project_id)
        ids = {item.id for item in artifacts}
        steps = {item.metadata.get("plan_step_id"): item.id for item in artifacts}
        pairs = {(item.source_version_id, item.target_version_id) for item in edges}
        for artifact in artifacts:
            inputs = set(artifact.metadata.get("input_artifact_version_ids") or [])
            for key, value in (artifact.metadata.get("generation_parameters") or {}).items():
                if key.endswith("_step") and isinstance(value, str):
                    inputs.add(steps.get(value))
                elif key.endswith("_steps") and isinstance(value, list):
                    inputs.update(steps.get(ref) for ref in value if isinstance(ref, str))
            for source_id in inputs & ids:
                pair = (source_id, artifact.id)
                if source_id != artifact.id and pair not in pairs:
                    edges.append(ArtifactDependency(project_id=project_id, source_version_id=source_id,
                                                    target_version_id=artifact.id, relation="saved_recipe_input"))
                    pairs.add(pair)
        return edges

    async def _restore_edit_steps(self, plan: RebuildPlan, overrides: dict | None = None) -> None:
        """Restore executable recipes from selected artifacts and their producing plans."""
        artifacts = {item.id: item for item in await self.repo.current_artifacts(plan.project_id)}
        recipes = {}
        for build in await self.repo.list_builds(plan.project_id):
            source_plan = await self.repo.get_plan(build.plan_id)
            for state in await self.repo.list_build_steps(plan.project_id, build.id):
                if state.result_artifact_version_id:
                    recipe = next((item for item in source_plan.items if item.step_id == state.plan_step_id), None)
                    if recipe is not None:
                        recipes[state.result_artifact_version_id] = recipe
        version = await self.repo.get_project_version(plan.base_project_version_id)
        plan.video_spec_revision_id = version.video_spec_revision_id
        by_version = {}
        for item in plan.items:
            source = artifacts[item.artifact_version_id]
            recipe = recipes.get(source.id)
            item.step_id = str(source.metadata.get("plan_step_id") or (recipe.step_id if recipe else source.id))
            item.output_artifact_id = source.artifact_id
            item.output_artifact_type = source.type
            item.capability = str(source.metadata.get("rebuild_capability") or source.metadata.get("capability") or (recipe.capability if recipe else ""))
            item.parameters = deepcopy(recipe.parameters if recipe else {})
            item.parameters.update(deepcopy(source.metadata.get("generation_parameters") or {}))
            item.parameters.update(deepcopy((overrides or {}).get(source.id, {})))
            item.parameters.pop("remote_operation_id", None)
            if recipe is not None:
                item.resolved_skills = deepcopy(recipe.resolved_skills)
                item.skill_context = deepcopy(recipe.skill_context)
                item.input_artifact_version_ids = list(recipe.input_artifact_version_ids)
            if overrides is not None and item.action == "rebuild" and not item.capability:
                raise ValueError(f"artifact {source.id} has no saved execution recipe; submit a PlanPatch with an explicit capability")
            item.estimated_cost = float(source.metadata.get("estimated_cost") or (recipe.estimated_cost if recipe else 0))
            by_version[source.id] = item
        for edge in await self._editable_dependencies(plan.project_id):
            source, target = by_version.get(edge.source_version_id), by_version.get(edge.target_version_id)
            if source and target and source.step_id not in target.depends_on:
                target.depends_on.append(source.step_id)
        topological_steps(plan.items)
        plan.estimated_cost = sum(item.estimated_cost for item in plan.items if item.action == "rebuild")

    async def preview_edits(
        self,
        *,
        project_id: str,
        base_project_version_id: str,
        edits: list[dict[str, Any]],
        description: str = "",
        idempotency_key: str | None = None,
    ) -> RebuildPlan:
        project = await self.repo.get_project(project_id)
        if project.current_version_id != base_project_version_id:
            from .repository import ProjectVersionConflict
            raise ProjectVersionConflict(base_project_version_id, project.current_version_id)
        artifacts = await self.repo.current_artifacts(project_id)
        if self.staged_planning_enabled and self.continuous_plan_patch_enabled:
            targets = [str(edit.get("artifactVersionId") or edit.get("artifact_version_id"))
                       for edit in edits if edit.get("artifactVersionId") or edit.get("artifact_version_id")]
            return await self._plan_dynamic_edit(ChangeRequest(
                project_id=project_id, base_project_version_id=base_project_version_id,
                description=description, edits=deepcopy(edits),
                target_artifact_version_ids=targets,
            ), idempotency_key)
        if edits and all(str(edit.get("type") or edit.get("kind")) == "regenerate_artifact" for edit in edits):
            overrides = {}
            for edit in edits:
                version_id = str(edit.get("artifactVersionId") or edit.get("artifact_version_id") or "")
                if not version_id:
                    target = str(edit.get("id") or edit.get("targetId") or "")
                    source = next((item for item in artifacts if target in {item.artifact_id, item.metadata.get("plan_step_id")}), None)
                    if source is None:
                        raise LookupError(f"artifact target not found: {target}")
                    version_id = source.id
                overrides.setdefault(version_id, {}).update(edit.get("patch") or {})
            change = ChangeRequest(project_id=project_id, base_project_version_id=base_project_version_id,
                                   description=description, edits=edits, target_artifact_version_ids=list(overrides))
            plan = self.engine.preview(change=change, artifacts=artifacts,
                                       dependencies=await self._editable_dependencies(project_id))
            await self._restore_edit_steps(plan, overrides)
            await self._resolve_plan_skills(plan)
            return await self.repo.save_change_and_plan(change, plan, idempotency_key)
        spec_artifact = next((item for item in artifacts if item.type == "video_spec"), None)
        persisted_spec_artifact = spec_artifact
        version = await self.repo.get_project_version(base_project_version_id)
        if version.video_spec_revision_id:
            revision = await self.repo.get_video_spec_revision(version.video_spec_revision_id)
            spec_artifact = MediaArtifactVersion(
                project_id=project_id, artifact_id=f"{project_id}:spec", type="video_spec",
                metadata={"content": deepcopy(revision.content)},
            )
        if spec_artifact is None or not isinstance(spec_artifact.metadata.get("content"), dict):
            raise ValueError("This structural edit needs a spec patch. Existing artifacts remain editable with regenerate_artifact or a PlanPatch.")
        # Revision content also carries execution history written by PlanPatch.
        # Only creative specification fields belong to the editable VideoSpec.
        spec_data = {
            key: deepcopy(value)
            for key, value in spec_artifact.metadata["content"].items()
            if key in VideoSpec.model_fields
        }
        targets: set[str] = set()
        manual_steps: set[str] = set()
        template_roots: set[str] = set()
        by_logical = {
            str(item.metadata.get("plan_step_id") or ""): item for item in artifacts
        }

        def target_step(step_id: str) -> None:
            artifact = by_logical.get(step_id)
            if artifact is not None:
                targets.add(artifact.id)

        for edit in edits:
            kind = str(edit.get("type") or edit.get("kind") or "")
            target_id = str(edit.get("id") or edit.get("targetId") or edit.get("target_id") or "")
            patch = edit.get("patch") if isinstance(edit.get("patch"), dict) else {}
            if kind == "patch_character":
                character = next((item for item in spec_data.get("characters", []) if item.get("id") == target_id), None)
                if character is None:
                    raise LookupError(f"character not found: {target_id}")
                character.update(patch)
                manual_steps.add("characters")
                target_step(f"character-{target_id}-reference")
                # Compatibility for projects created before per-character references.
                if f"character-{target_id}-reference" not in by_logical:
                    target_step("character-reference")
            elif kind == "patch_shot":
                shot = next((item for item in spec_data.get("shots", []) if item.get("id") == target_id), None)
                if shot is None:
                    raise LookupError(f"shot not found: {target_id}")
                shot.update(patch)
                manual_steps.add("storyboard")
                target_step(f"shot-{target_id}-keyframe")
            elif kind == "replace_music":
                spec_data.setdefault("audio", {})["bgm_prompt"] = str(
                    patch.get("bgm_prompt") or edit.get("prompt") or ""
                )
                target_step("bgm")
                template_roots.add("bgm")
            elif kind == "patch_timeline":
                shot_patches = patch.get("shots")
                if shot_patches is not None and not isinstance(shot_patches, list):
                    raise ValueError("patch_timeline.patch.shots must be a list")
                requested_duration = patch.get(
                    "target_duration_seconds",
                    patch.get("targetDurationSeconds"),
                )
                shots_by_id = {
                    str(item.get("id") or ""): item
                    for item in spec_data.get("shots", [])
                }
                for shot_patch in shot_patches or []:
                    if not isinstance(shot_patch, dict):
                        raise ValueError("timeline shot patches must be objects")
                    shot_id = str(shot_patch.get("id") or "")
                    shot = shots_by_id.get(shot_id)
                    if shot is None:
                        # Duration extensions often need additional creative
                        # segments. The Agent authors them as complete shot
                        # records; the Runtime validates rather than inventing
                        # creative content or forcing a Workflow-specific shape.
                        required = {"id", "order", "duration_seconds", "beat", "visual_prompt"}
                        missing = sorted(required - set(shot_patch))
                        if missing:
                            raise ValueError(
                                f"new timeline shot {shot_id or '<missing id>'} is missing: "
                                + ", ".join(missing)
                            )
                        shot = dict(shot_patch)
                        shots_by_id[shot_id] = shot
                        manual_steps.add("storyboard")
                        template_roots.add(f"shot-{shot_id}-video")
                        continue
                    previous_duration = shot.get("duration_seconds")
                    previous_narration = shot.get("narration")
                    for field in (
                        "order", "duration_seconds", "beat", "visual_prompt", "transition",
                        "narration", "character_ids", "reference_asset_ids",
                    ):
                        if field in shot_patch:
                            shot[field] = shot_patch[field]
                    if shot.get("duration_seconds") != previous_duration:
                        target_step(f"shot-{shot_id}-video")
                        template_roots.add(f"shot-{shot_id}-video")
                    if shot.get("narration") != previous_narration:
                        target_step("narration")
                        target_step("subtitles")
                        template_roots.add("narration")
                        template_roots.add("subtitles")
                if shot_patches:
                    spec_data["shots"] = sorted(
                        shots_by_id.values(), key=lambda item: int(item.get("order") or 0),
                    )
                    authored_duration = sum(
                        float(item.get("duration_seconds") or 0)
                        for item in spec_data["shots"]
                    )
                    if requested_duration is not None and abs(
                        authored_duration - float(requested_duration)
                    ) > 1:
                        raise ValueError(
                            "timeline shot durations must match target_duration_seconds; "
                            "the Agent must author the added or resized shots"
                        )
                    spec_data["target_duration_seconds"] = (
                        float(requested_duration)
                        if requested_duration is not None
                        else authored_duration
                    )
                    manual_steps.add("storyboard")
                elif requested_duration is not None and abs(
                    float(requested_duration)
                    - float(spec_data.get("target_duration_seconds") or 0)
                ) > 1:
                    raise ValueError(
                        "changing target duration requires authored shot patches; "
                        "include the revised and newly added shots in patch_timeline.patch.shots"
                    )
                target_step("timeline")
                target_step("assembled-video")
                template_roots.update({"timeline", "assembled-video"})
            elif kind == "generate_lipsync":
                target_step(f"shot-{target_id}-video" if target_id else "final-video")
            elif kind == "regenerate_artifact":
                version_id = str(edit.get("artifactVersionId") or edit.get("artifact_version_id") or "")
                if version_id:
                    targets.add(version_id)
                elif target_id:
                    target_step(target_id)
            elif kind == "patch_scene":
                target_step("storyboard")
            else:
                raise ValueError(f"unsupported edit type: {kind}")

        proposed_spec = await self._apply_project_skill_locks(
            project_id, VideoSpec.model_validate(spec_data),
        )
        if (
            spec_artifact.metadata["content"].get("execution_tasks")
            and self.staged_planning_enabled
            and self.continuous_plan_patch_enabled
        ):
            # Continue Agent-authored projects through their own planner. A
            # static workflow compiler cannot reconstruct an arbitrary task DAG.
            intent_fields = {
                key: value for key, value in proposed_spec.model_dump(mode="json").items()
                if key in ProjectIntent.model_fields
            }
            intent_fields["brief"] = description or json.dumps(edits, ensure_ascii=False)
            intent_fields["constraints"] = {
                "edit_existing_project": True,
                "edits": deepcopy(edits),
                "proposed_video_spec": proposed_spec.model_dump(mode="json"),
                "preserve_existing_artifact_version_ids": [item.id for item in artifacts],
            }
            return await self.plan_project(
                project_id=project_id,
                base_project_version_id=base_project_version_id,
                project_intent=ProjectIntent.model_validate(intent_fields),
                idempotency_key=idempotency_key or f"edit:{base_project_version_id}:{json.dumps(edits, sort_keys=True)}",
            )
        change = ChangeRequest(
            project_id=project_id,
            base_project_version_id=base_project_version_id,
            description=description or "; ".join(str(item.get("type") or item.get("kind")) for item in edits),
            target_artifact_version_ids=sorted(targets),
            edits=edits,
            proposed_video_spec=proposed_spec,
        )
        dependencies = await self.repo.current_dependencies(project_id)
        plan = self.engine.preview(
            change=change,
            artifacts=artifacts,
            dependencies=dependencies,
        )
        plan.video_spec = proposed_spec
        plan.workflow_id = proposed_spec.workflow_id
        source_by_id = {item.id: item for item in artifacts}
        template_plan = await self._compile_workflow_plan(
            PluginContext(project_id=project_id, values={
                "video_spec": proposed_spec,
                "base_project_version_id": base_project_version_id,
            }),
            proposed_spec,
        )
        template_by_step = {item.step_id: item for item in template_plan.items}
        if template_roots and template_by_step:
            affected_steps = set(template_roots)
            changed = True
            while changed:
                changed = False
                for template in template_by_step.values():
                    if template.step_id in affected_steps:
                        continue
                    if any(dependency in affected_steps for dependency in template.depends_on):
                        affected_steps.add(template.step_id)
                        changed = True
            item_by_step = {item.step_id: item for item in plan.items if item.step_id}
            for step_id in affected_steps:
                template = template_by_step.get(step_id)
                if template is None:
                    continue
                source = by_logical.get(step_id)
                if source is not None:
                    item = next(
                        (value for value in plan.items if value.artifact_version_id == source.id),
                        None,
                    )
                    if item is None:
                        item = RebuildPlanItem(
                            step_id=step_id,
                            artifact_version_id=source.id,
                            output_artifact_id=source.artifact_id,
                            output_artifact_type=source.type,
                            action="rebuild",
                        )
                        plan.items.append(item)
                    if template.action == "validate":
                        item.action = "validate"
                    elif item.action in {"reuse", "validate"}:
                        item.action = "rebuild"
                    continue
                if step_id in item_by_step:
                    continue
                created = template.model_copy(deep=True)
                created.action = "validate" if template.action == "validate" else "create"
                plan.items.append(created)
                item_by_step[step_id] = created
        capability_costs = {
            "atomic.image.generate": 0.08,
            "atomic.video.generate": 0.65,
            "atomic.music.generate": 0.10,
            "suno.generate": 0.10,
            "api.provider.generate": 0.65,
            "media.tts": 0.05,
            "media.concat": 0.02,
            "media.mix_audio": 0.01,
            "media.subtitle.burn": 0.02,
            "media.lipsync": 0.35,
            "runtime.artifact.persist": 0.0,
        }
        legacy_capabilities = {
            "video_spec": "runtime.artifact.persist",
            "script": "runtime.artifact.persist",
            "characters": "runtime.artifact.persist",
            "storyboard": "runtime.artifact.persist",
            "character_reference": "atomic.image.generate",
            "keyframe": "atomic.image.generate",
            "video_clip": "atomic.video.generate",
            "continuity_frame": "media.extract_frame",
            "audio_narration": "media.tts",
            "audio_bgm": "atomic.music.generate",
            "timeline": "media.timeline.compose",
            "video_assembled": "media.concat",
            "video_mixed": "media.mix_audio",
            "subtitle": "media.subtitle.compose",
            "final_video": "media.subtitle.burn",
        }
        regeneration_overrides = {
            str(edit.get("artifactVersionId") or edit.get("artifact_version_id")): dict(edit.get("patch") or {})
            for edit in edits
            if str(edit.get("type") or edit.get("kind")) == "regenerate_artifact"
        }
        lipsync_shots = {
            str(edit.get("id") or edit.get("targetId") or "")
            for edit in edits
            if str(edit.get("type") or edit.get("kind")) == "generate_lipsync"
        }
        narration_artifact = by_logical.get("narration")
        for item in plan.items:
            source = source_by_id.get(item.artifact_version_id)
            if source is None:
                continue
            step_id = str(source.metadata.get("plan_step_id") or "")
            template = template_by_step.get(step_id)
            item.output_artifact_id = source.artifact_id
            item.output_artifact_type = source.type
            item.capability = str(
                source.metadata.get("rebuild_capability")
                or (template.capability if template else "")
                or legacy_capabilities.get(source.type, "")
            )
            # Preserve provider-specific values that are absent from the
            # workflow template, but let the newly compiled VideoSpec win for
            # ordering, duration, prompts, and dependency references.
            item.parameters = dict(source.metadata.get("generation_parameters") or {})
            if template is not None:
                item.parameters.update(template.parameters)
            item.parameters.update(regeneration_overrides.get(source.id, {}))
            item.estimated_cost = float(
                source.metadata.get("estimated_cost")
                or capability_costs.get(item.capability, 0.0)
            )
            item.step_id = str(source.metadata.get("plan_step_id") or item.step_id)
            if item.action != "rebuild":
                continue
            if step_id == "characters":
                item.parameters["content"] = [value.model_dump(mode="json") for value in proposed_spec.characters]
            elif step_id == "character-reference" or (step_id.startswith("character-") and step_id.endswith("-reference")):
                character_id = str(item.parameters.get("character_id") or "")
                selected = [value for value in proposed_spec.characters if not character_id or value.id == character_id]
                descriptions = "; ".join(
                    f"{value.name}: {value.appearance}; clothing: {value.clothing}"
                    for value in selected
                )
                item.parameters["prompt"] = f"Consistent production character reference sheet. {descriptions}"
            elif step_id == "storyboard":
                item.parameters["content"] = [value.model_dump(mode="json") for value in proposed_spec.shots]
            elif step_id.startswith("shot-"):
                shot_id = str(item.parameters.get("shot_id") or "")
                shot = next((value for value in proposed_spec.shots if value.id == shot_id), None)
                if shot is not None:
                    item.parameters["prompt"] = shot.visual_prompt
                    if source.type == "video_clip":
                        item.parameters["duration"] = shot.duration_seconds
            elif step_id == "bgm":
                item.parameters["prompt"] = proposed_spec.audio.bgm_prompt
            if source.type == "video_clip" and str(item.parameters.get("shot_id") or "") in lipsync_shots:
                if narration_artifact is None or not narration_artifact.uri or not source.uri:
                    raise ValueError("lipsync requires an existing narration and video clip")
                item.capability = "media.lipsync"
                item.estimated_cost = capability_costs["media.lipsync"]
                item.parameters = {
                    "video_url": source.uri,
                    "audio_url": narration_artifact.uri,
                    "model": "sync/lipsync-2-pro",
                }
        for step_id in sorted(manual_steps):
            source = by_logical.get(step_id)
            if source is None:
                continue
            plan.items = [item for item in plan.items if item.artifact_version_id != source.id]
            parameters = dict(source.metadata.get("generation_parameters") or {})
            if step_id == "characters":
                parameters["content"] = [value.model_dump(mode="json") for value in proposed_spec.characters]
            elif step_id == "storyboard":
                parameters["content"] = [value.model_dump(mode="json") for value in proposed_spec.shots]
            plan.items.append(RebuildPlanItem(
                step_id=step_id,
                artifact_version_id=source.id,
                output_artifact_id=source.artifact_id,
                output_artifact_type=source.type,
                action="rebuild",
                capability=str(source.metadata.get("rebuild_capability") or "runtime.artifact.persist"),
                parameters=parameters,
                order=-1,
                reason="Commit edited definition",
            ))
        # Persist the new spec atomically without invalidating every downstream artifact.
        plan.items = [item for item in plan.items if persisted_spec_artifact is None or item.artifact_version_id != persisted_spec_artifact.id]
        plan.items.append(RebuildPlanItem(
            step_id="spec",
            artifact_version_id=persisted_spec_artifact.id if persisted_spec_artifact else "",
            output_artifact_id=spec_artifact.artifact_id,
            output_artifact_type="video_spec",
            action="rebuild" if persisted_spec_artifact else "create",
            capability="runtime.artifact.persist",
            parameters={"title": proposed_spec.title, "content": proposed_spec.model_dump(mode="json")},
            order=-1,
            reason="Commit edited VideoSpec",
        ))
        # Keep the executable plan self-describing. Artifact edges remain the
        # source of truth, while stable step ids let providers and the UI show
        # the same dependency order without rediscovering the graph.
        step_by_version = {
            item.artifact_version_id: item.step_id
            for item in plan.items
            if item.artifact_version_id and item.step_id
        }
        item_by_version = {
            item.artifact_version_id: item
            for item in plan.items
            if item.artifact_version_id
        }
        for edge in dependencies:
            target = item_by_version.get(edge.target_version_id)
            source_step = step_by_version.get(edge.source_version_id)
            if target is not None and source_step and source_step not in target.depends_on:
                target.depends_on.append(source_step)
        topological_steps(plan.items)
        plan.estimated_cost = round(sum(
            item.estimated_cost
            for item in plan.items
            if item.action in {"create", "rebuild"}
        ), 6)
        await self._resolve_plan_skills(plan)
        return await self.repo.save_change_and_plan(change, plan, idempotency_key)

    def plan_patch_capability_catalog(self) -> list[MediaCapabilityContract]:
        """Return installed Harness-wide PlanPatch operations declared by plugins."""
        contracts: dict[str, MediaCapabilityContract] = {}
        for loaded in self.plugins.loaded:
            provider = getattr(
                loaded.implementation, "plan_patch_capability_contracts", None,
            )
            if not callable(provider):
                continue
            for contract in provider():
                if contract.capability not in loaded.manifest.contributions.capabilities:
                    raise ValueError(
                        f"plugin {loaded.manifest.id} exposes an undeclared media capability: "
                        f"{contract.capability}"
                    )
                if (
                    contract.capability
                    not in loaded.manifest.contributions.plan_patch_capabilities
                ):
                    raise ValueError(
                        f"plugin {loaded.manifest.id} exposes a PlanPatch contract without "
                        f"allow-listing the capability: {contract.capability}"
                    )
                if contract.capability in contracts:
                    raise ValueError(
                        f"duplicate media capability contract: {contract.capability}"
                    )
                contracts[contract.capability] = contract
        return [contracts[key] for key in sorted(contracts)]

    def media_capability_catalog(self) -> list[MediaCapabilityContract]:
        """Compatibility alias for pre-PlanPatch callers."""
        return self.plan_patch_capability_catalog()

    async def preview_plan_patch(
        self,
        *,
        project_id: str,
        base_project_version_id: str,
        operations: list[MediaEditOperation],
        description: str = "",
        idempotency_key: str | None = None,
    ) -> RebuildPlan:
        """Compile Agent-proposed post-production steps without a generation Workflow.

        The installed Media Plugin contracts define accepted inputs and output
        behavior. Every input must be a selected project ArtifactVersion or an
        earlier operation, so callers cannot smuggle arbitrary external URLs into
        the Capability Execution Envelope.
        """
        project = await self.repo.get_project(project_id)
        if project.current_version_id != base_project_version_id:
            from .repository import ProjectVersionConflict
            raise ProjectVersionConflict(base_project_version_id, project.current_version_id)
        if not operations:
            raise ValueError("at least one media edit operation is required")
        if any(item.capability == "media.hyperframes_render" for item in operations):
            encoded_context = await self.repo.get_operation_result(
                project_id, "compat-run-context", "initial",
            )
            try:
                code_video_enabled = bool(
                    json.loads(encoded_context or "{}").get("code_video_mode", False)
                )
            except (json.JSONDecodeError, AttributeError):
                code_video_enabled = False
            if not code_video_enabled:
                raise ValueError(
                    "media.hyperframes_render requires Code-to-Video mode to be enabled"
                )
        operation_ids = [item.step_id for item in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("media edit operation step ids must be unique")

        contracts = {
            item.capability: item for item in self.plan_patch_capability_catalog()
        }
        current_artifacts = await self.repo.current_artifacts(project_id)
        current_by_version = {item.id: item for item in current_artifacts}
        output_types: dict[str, str] = {}
        reuse_step_by_version: dict[str, str] = {}
        plan_items: list[RebuildPlanItem] = []
        replacement_ids: set[str] = set()

        def reuse_step(artifact: MediaArtifactVersion) -> str:
            existing = reuse_step_by_version.get(artifact.id)
            if existing:
                return existing
            step_id = f"source-{len(reuse_step_by_version) + 1}"
            reuse_step_by_version[artifact.id] = step_id
            plan_items.append(RebuildPlanItem(
                step_id=step_id,
                artifact_version_id=artifact.id,
                output_artifact_id=artifact.artifact_id,
                output_artifact_type=artifact.type,
                action="reuse",
                order=-100 + len(reuse_step_by_version),
                reason="Selected project Artifact used by a post-production operation",
            ))
            return step_id

        for order, operation in enumerate(operations, start=1):
            operation = operation.model_copy(deep=True)
            contract = contracts.get(operation.capability)
            if contract is None:
                raise ValueError(
                    f"capability is not available for workflow-free media editing: "
                    f"{operation.capability}"
                )
            roles = {item.role for item in contract.inputs}
            for supplied in operation.inputs:
                if supplied.role not in roles:
                    aliases = [role for role in roles if role.rstrip("s") == supplied.role.rstrip("s")]
                    if len(aliases) == 1:
                        supplied.role = aliases[0]
            # Models often repeat the URI of an explicitly supplied artifact.
            # Resolve that redundant spelling to the authoritative input instead
            # of rejecting an otherwise executable edit.
            for expected in contract.inputs:
                supplied = [entry for entry in operation.inputs if entry.role == expected.role]
                if not supplied:
                    continue
                # Explicit artifact inputs are authoritative. Models sometimes
                # repeat local step aliases; replace them with resolved aliases below.
                operation.parameters.pop(expected.parameter, None)
                referenced = [current_by_version.get(entry.artifact_version_id) for entry in supplied]
                urls = [item.uri for item in referenced if item is not None and item.uri]
                for key in (f"{expected.role}_url", f"{expected.role.rstrip('s')}_urls"):
                    value = operation.parameters.get(key)
                    if value is not None and (value == urls or (len(urls) == 1 and value == urls[0])):
                        operation.parameters.pop(key)
            reserved = {
                key for key in operation.parameters
                if key in {"uri", "url", "remote_operation_id"}
                or key.endswith("_url")
                or key.endswith("_step")
                or key.endswith("_steps")
            }
            if reserved:
                raise ValueError(
                    "media edit parameters cannot contain direct resource references: "
                    + ", ".join(sorted(reserved))
                )
            role_contracts = {item.role: item for item in contract.inputs}
            grouped_inputs: dict[str, list] = {}
            for supplied in operation.inputs:
                if supplied.role not in role_contracts:
                    raise ValueError(
                        f"{operation.capability} does not accept input role {supplied.role}. "
                        f"Accepted input roles: {', '.join(sorted(role_contracts)) or '(none)'}. "
                        "Correct the input role and retry the preview; no operation has been submitted."
                    )
                grouped_inputs.setdefault(supplied.role, []).append(supplied)
            for role, expected in role_contracts.items():
                supplied_values = grouped_inputs.get(role, [])
                if expected.required and not supplied_values:
                    raise ValueError(
                        f"{operation.capability} requires input role {role}"
                    )
                if not expected.multiple and len(supplied_values) > 1:
                    raise ValueError(
                        f"{operation.capability} accepts only one {role} input"
                    )

            parameters = deepcopy(operation.parameters)
            dependencies: list[str] = []
            artifact_inputs_by_role: dict[str, list[MediaArtifactVersion]] = {}
            for role, supplied_values in grouped_inputs.items():
                expected = role_contracts[role]
                refs: list[str] = []
                for supplied in supplied_values:
                    if supplied.artifact_version_id:
                        artifact = current_by_version.get(supplied.artifact_version_id)
                        if artifact is None:
                            raise LookupError(
                                "media edit inputs must reference a currently selected project "
                                f"ArtifactVersion: {supplied.artifact_version_id}"
                            )
                        if not _artifact_matches_media_type(
                            artifact.type, expected.artifact_types,
                        ):
                            raise ValueError(
                                f"input {role} expects {expected.artifact_types}, got {artifact.type}"
                            )
                        ref = reuse_step(artifact)
                        artifact_inputs_by_role.setdefault(role, []).append(artifact)
                    else:
                        ref = str(supplied.operation_step_id)
                        if ref not in output_types:
                            raise ValueError(
                                f"media edit input references an unknown or later operation: {ref}"
                            )
                        if not _artifact_matches_media_type(
                            output_types[ref], expected.artifact_types,
                        ):
                            raise ValueError(
                                f"input {role} expects {expected.artifact_types}, "
                                f"but operation {ref} produces {output_types[ref]}"
                            )
                    refs.append(ref)
                    if ref not in dependencies:
                        dependencies.append(ref)
                parameters[expected.parameter] = refs if expected.multiple else refs[0]

            if contract.parameters_schema:
                validator = validator_for(contract.parameters_schema)(
                    contract.parameters_schema,
                )
                try:
                    validator.validate(parameters)
                except JsonSchemaValidationError as exc:
                    path = ".".join(str(item) for item in exc.absolute_path)
                    location = f" at {path}" if path else ""
                    raise ValueError(
                        f"PlanPatch operation {operation.step_id} has invalid parameters"
                        f"{location}: {exc.message}"
                    ) from exc

            replacement: MediaArtifactVersion | None = None
            if contract.replaces_input_role:
                candidates = artifact_inputs_by_role.get(
                    contract.replaces_input_role, [],
                )
                chained_inputs = grouped_inputs.get(contract.replaces_input_role, [])
                chained = len(chained_inputs) == 1 and bool(chained_inputs[0].operation_step_id)
                if len(candidates) != 1 and not chained:
                    raise ValueError(
                        f"{operation.capability} must replace one selected project "
                        f"{contract.replaces_input_role} ArtifactVersion"
                    )
                replacement = candidates[0] if candidates else None
                if replacement is not None:
                    # Multiple variants of one source can coexist as artifacts.
                    # Only the first transform replaces the selected source.
                    if replacement.id in replacement_ids:
                        replacement = None
                    else:
                        replacement_ids.add(replacement.id)

            output_type = replacement.type if replacement else contract.output_artifact_type
            plan_items.append(RebuildPlanItem(
                step_id=operation.step_id,
                artifact_version_id=replacement.id if replacement else "",
                output_artifact_id=(
                    replacement.artifact_id
                    if replacement
                    else f"{project_id}:post:{operation.step_id}"
                ),
                output_artifact_type=output_type,
                action="rebuild" if replacement else "create",
                capability=operation.capability,
                parameters={
                    **parameters,
                    **({"title": operation.title} if operation.title else {}),
                },
                depends_on=dependencies,
                estimated_cost=contract.estimated_cost,
                order=order,
                reason=description or contract.description,
                skill_ids=[contract.skill_id] if contract.skill_id else [],
            ))
            output_types[operation.step_id] = output_type

        change = ChangeRequest(
            project_id=project_id,
            base_project_version_id=base_project_version_id,
            description=description or "Dynamic post-production edit",
            target_artifact_version_ids=sorted(replacement_ids),
            edits=[item.model_dump(mode="json") for item in operations],
        )
        if self.staged_planning_enabled and self.continuous_plan_patch_enabled:
            return await self._plan_dynamic_edit(change, idempotency_key)
        plan = RebuildPlan(
            project_id=project_id,
            kind="incremental",
            change_request_id=change.id,
            base_project_version_id=base_project_version_id,
            workflow_id="",
            items=plan_items,
            estimated_cost=round(sum(
                item.estimated_cost
                for item in plan_items
                if item.action in {"create", "rebuild"}
            ), 6),
        )
        context = PluginContext(project_id=project_id, values={
            "change_request": change,
            "media_edit_operations": operations,
        })
        for loaded in self.plugins.loaded:
            plan = await loaded.implementation.after_plan(context, plan)
        topological_steps(plan.items)
        validate_video_generation_steps(plan.items)
        await self._resolve_plan_skills(plan)
        return await self.repo.save_change_and_plan(change, plan, idempotency_key)

    async def preview_media_edits(self, **kwargs: Any) -> RebuildPlan:
        """Compatibility alias; new callers use :meth:`preview_plan_patch`."""
        return await self.preview_plan_patch(**kwargs)

    async def apply_rebuild(
        self,
        *,
        project_id: str,
        plan_id: str,
        base_project_version_id: str,
        idempotency_key: str,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> Build:
        build = await self.repo.submit_build(
            project_id=project_id,
            plan_id=plan_id,
            base_version_id=base_project_version_id,
            idempotency_key=idempotency_key,
            session_id=session_id,
            user_id=user_id,
        )
        self._schedule_build(build)
        return build

    async def plan_project(
        self,
        *,
        project_id: str,
        base_project_version_id: str,
        video_spec: VideoSpec | None = None,
        project_intent: ProjectIntent | None = None,
        idempotency_key: str,
    ) -> RebuildPlan:
        if (video_spec is None) == (project_intent is None):
            raise ValueError("provide exactly one of video_spec or project_intent")
        project = await self.repo.get_project(project_id)
        if project.current_version_id != base_project_version_id:
            from .repository import ProjectVersionConflict
            raise ProjectVersionConflict(base_project_version_id, project.current_version_id)
        supplied: VideoSpec | ProjectIntent = video_spec or project_intent  # type: ignore[assignment]
        supplied = await self._apply_project_skill_locks(project_id, supplied)
        workflow = self.skills.workflows.get(supplied.workflow_id)
        if workflow is not None:
            from .workflow_plans import workflow_execution_kind

            kind = workflow_execution_kind(workflow)
            if kind == "agent_plan_patch" and not (
                self.staged_planning_enabled and self.continuous_plan_patch_enabled
            ):
                raise ValueError("Workflow requires continuous PlanPatch planning to be enabled")
        if isinstance(supplied, VideoSpec):
            video_spec = supplied
            project_intent = None
        else:
            project_intent = supplied
            video_spec = None
        current_artifacts = await self.repo.current_artifacts(project_id)
        source_by_logical_id = {item.artifact_id: item for item in current_artifacts}
        referenced_source_ids = set(supplied.source_asset_ids)
        if video_spec is not None:
            referenced_source_ids.update(
                asset_id for shot in video_spec.shots for asset_id in shot.reference_asset_ids
            )
        missing_source_ids = sorted(referenced_source_ids - set(source_by_logical_id))
        if missing_source_ids:
            raise LookupError(
                "project plan references source assets that do not exist: "
                + ", ".join(missing_source_ids)
            )
        context = PluginContext(project_id=project_id, values={
            "video_spec": video_spec,
            "project_intent": project_intent,
            "base_project_version_id": base_project_version_id,
            "source_artifacts": {
                key: value for key, value in source_by_logical_id.items()
                if key in referenced_source_ids
            },
            "continuous_plan_patch": self.continuous_plan_patch_enabled,
        })
        for loaded in self.plugins.loaded:
            await loaded.implementation.before_plan(context)
        if self.staged_planning_enabled:
            workflow_id = supplied.workflow_id
            plugin = None if self.continuous_plan_patch_enabled else self._workflow_plugin(workflow_id)
            planning_mode = (
                "agentic"
                if self.continuous_plan_patch_enabled
                else plugin.implementation.planning_mode(workflow_id)
            )
            if planning_mode not in {"full", "staged", "agentic"}:
                raise ValueError(f"unsupported workflow planning mode: {planning_mode}")
            if planning_mode == "full":
                if video_spec is None:
                    raise ValueError(
                        f"full-planning workflow {workflow_id} requires a complete VideoSpec"
                    )
                plan = await plugin.implementation.compile_build_plan(context, video_spec)
                plan.schema_version = 2
                plan.current_revision = 1
                plan.current_phase = "full"
                plan.next_checkpoint = None
            else:
                if project_intent is None:
                    assert video_spec is not None
                    project_intent = ProjectIntent(
                        title=video_spec.title,
                        brief=str(
                            video_spec.workflow_parameters.get("brief")
                            or "; ".join(shot.beat for shot in video_spec.shots)
                        ),
                        language=video_spec.language,
                        language_contract=video_spec.language_contract,
                        target_duration_seconds=video_spec.target_duration_seconds,
                        aspect_ratio=video_spec.aspect_ratio,
                        resolution=video_spec.resolution,
                        workflow_id=video_spec.workflow_id,
                        style_id=video_spec.style_id,
                        activated_skill_ids=list(video_spec.activated_skill_ids),
                        source_asset_ids=list(video_spec.source_asset_ids),
                        workflow_parameters=dict(video_spec.workflow_parameters),
                        providers=video_spec.providers,
                        automation=video_spec.automation,
                        constraints={"initial_video_spec": video_spec.model_dump(mode="json")},
                    )
                    context.values["project_intent"] = project_intent
                if self.continuous_plan_patch_enabled:
                    project_intent = project_intent.model_copy(update={
                        "constraints": {
                            **project_intent.constraints,
                            "continuous_plan_patch": True,
                        },
                    })
                    context.values["project_intent"] = project_intent
                if self.continuous_plan_patch_enabled:
                    from .staged_planning import compile_continuous_plan_initial

                    plan = compile_continuous_plan_initial(
                        workflow=self._workflow_policy_spec(project_intent.workflow_id),
                        context=context,
                        intent=project_intent,
                    )
                    # A follow-up goal starts with the selected work, including generated media.
                    selected = await self.repo.current_artifacts(project_id)
                    included = {item.artifact_version_id for item in plan.items}
                    for artifact in selected:
                        if artifact.id not in included:
                            plan.items.append(RebuildPlanItem(
                                step_id=f"existing-{artifact.id}", action="reuse",
                                artifact_version_id=artifact.id,
                                output_artifact_id=artifact.artifact_id,
                                output_artifact_type=artifact.type,
                                reason="Selected result retained for the next Agent goal",
                            ))
                else:
                    compile_initial = getattr(plugin.implementation, "compile_initial", None)
                    if not callable(compile_initial):
                        raise LookupError(
                            f"workflow plugin has no staged compiler: {project_intent.workflow_id}"
                        )
                    plan = await compile_initial(context, project_intent)
            if project_intent is None and video_spec is not None:
                # Full planning does not need a ProjectIntent, but preserving the
                # user's known constraints makes the plan self-describing.
                assert video_spec is not None
                project_intent = ProjectIntent(
                    title=video_spec.title,
                    brief=str(
                        video_spec.workflow_parameters.get("brief")
                        or "; ".join(shot.beat for shot in video_spec.shots)
                    ),
                    language=video_spec.language,
                    language_contract=video_spec.language_contract,
                    target_duration_seconds=video_spec.target_duration_seconds,
                    aspect_ratio=video_spec.aspect_ratio,
                    resolution=video_spec.resolution,
                    workflow_id=video_spec.workflow_id,
                    style_id=video_spec.style_id,
                    activated_skill_ids=list(video_spec.activated_skill_ids),
                    source_asset_ids=list(video_spec.source_asset_ids),
                    workflow_parameters=dict(video_spec.workflow_parameters),
                    providers=video_spec.providers,
                    automation=video_spec.automation,
                    constraints={"initial_video_spec": video_spec.model_dump(mode="json")},
                )
            source_versions = [source_by_logical_id[item].id for item in referenced_source_ids]
            revision_content = (
                video_spec.model_dump(mode="json")
                if video_spec is not None
                else project_intent.model_dump(mode="json")
            )
            existing_spec_revisions = await self.repo.list_video_spec_revisions(project_id)
            latest_spec_revision = (
                existing_spec_revisions[-1] if existing_spec_revisions else None
            )
            spec_revision = VideoSpecRevision(
                project_id=project_id,
                revision=(latest_spec_revision.revision + 1 if latest_spec_revision else 1),
                parent_revision_id=(latest_spec_revision.id if latest_spec_revision else None),
                content=revision_content,
                resolved_sections=(
                    ["title", "format", "workflow", "style", "providers", "automation"]
                    if video_spec is None
                    else [
                        "title", "format", "workflow", "style", "characters", "shots",
                        "audio", "providers", "automation", "timeline",
                    ]
                ),
                unresolved_sections=(
                    ["characters", "shots", "audio", "timeline"]
                    if video_spec is None else []
                ),
                source_artifact_version_ids=source_versions,
                created_by="agent",
                complete=video_spec is not None,
            )
            plan.video_spec = video_spec
            plan.video_spec_revision_id = spec_revision.id
            plan.project_intent = project_intent
            plan_revision = BuildPlanRevision(
                plan_id=plan.id,
                project_id=project_id,
                revision=1,
                base_revision=0,
                video_spec_revision_id=spec_revision.id,
                added_step_ids=[item.step_id for item in plan.items],
                reason=(
                    "Initial Cuti continuous PlanPatch state"
                    if self.continuous_plan_patch_enabled
                    else "Initial staged phase"
                ),
            )
        else:
            if video_spec is None:
                raise ValueError(
                    "ProjectIntent requires VIDEO_STAGED_PLANNING_ENABLED=true"
                )
            plan = await self._compile_workflow_plan(context, video_spec)
        for loaded in self.plugins.loaded:
            plan = await loaded.implementation.after_plan(context, plan)
        topological_steps(plan.items)
        await self._resolve_plan_skills(plan)
        if plan.schema_version == 2:
            saved = await self.repo.save_staged_plan(
                plan, spec_revision, plan_revision, idempotency_key,
            )
        else:
            saved = await self.repo.save_plan(plan, idempotency_key)
        if self.skills.catalog.has(saved.workflow_id):
            metadata = self.skills.catalog.load(saved.workflow_id).metadata
            if (
                (metadata.metadata or {}).get("kind") == "workflow"
            ):
                await self.set_project_skill_enabled(
                    project_id=project_id,
                    skill_id=saved.workflow_id,
                    enabled=True,
                )
        return saved

    def _workflow_policy_spec(self, workflow_id: str):
        """Return the original Cuti Workflow contract used to police PlanPatches."""
        return self.skills.workflows.get(workflow_id)

    @staticmethod
    def _is_continuous_plan(plan: RebuildPlan) -> bool:
        return bool(
            plan.project_intent
            and plan.project_intent.constraints.get("continuous_plan_patch")
        )

    def _workflow_plugin(self, workflow_id: str):
        from .skill_workflows import SKILL_WORKFLOW_PLUGIN_ID

        matches = [
            loaded for loaded in self.plugins.loaded
            if workflow_id in loaded.manifest.contributions.workflows
        ]
        if not matches:
            raise LookupError(f"workflow plugin is not installed: {workflow_id}")
        return next(
            (item for item in matches if item.manifest.id == SKILL_WORKFLOW_PLUGIN_ID),
            matches[0],
        )

    async def _compile_workflow_plan(
        self,
        context: PluginContext,
        video_spec: VideoSpec,
    ) -> RebuildPlan:
        return await self._workflow_plugin(video_spec.workflow_id).implementation.compile_build_plan(
            context, video_spec,
        )

    @staticmethod
    def _frozen_plan_skills(
        plan: RebuildPlan,
    ) -> dict[str, tuple[ResolvedSkillRef, str]]:
        """Return exact Skill instruction blocks already persisted on a plan."""
        frozen: dict[str, tuple[ResolvedSkillRef, str]] = {}
        separator = "\n\n---\n\n"
        for item in reversed(plan.items):
            context = item.skill_context
            if context is None or not context.applied_skills:
                continue
            blocks = context.instructions.split(separator)
            if len(blocks) != len(context.applied_skills):
                continue
            for reference, instructions in zip(
                context.applied_skills, blocks, strict=True,
            ):
                frozen.setdefault(reference.skill_id, (reference, instructions))
        return frozen

    async def _resolve_plan_skills(
        self,
        plan: RebuildPlan,
        *,
        frozen_plan: RebuildPlan | None = None,
    ) -> None:
        activated = list(plan.video_spec.activated_skill_ids) if plan.video_spec else []
        project_locks = await self.repo.list_project_skill_locks(plan.project_id)
        if not plan.workflow_id:
            project_locks = [
                lock for lock in project_locks
                if (
                    not self.skills.catalog.has(lock.skill_id)
                    or (self.skills.catalog.load(lock.skill_id).metadata.metadata or {}).get(
                        "kind"
                    ) != "workflow"
                )
            ]
        frozen_skills = (
            self._frozen_plan_skills(frozen_plan) if frozen_plan is not None else {}
        )
        for item in plan.items:
            try:
                capability = self.skills.capabilities.get(
                    item.capability,
                    require_enabled=False,
                )
                capability_skill_id = capability.skill_name
            except LookupError:
                capability_skill_id = None
            context = self.skills.resolver.resolve(
                SkillResolutionRequest(
                    workflow_skill_id=(
                        plan.workflow_id
                        if self.skills.workflows.get(plan.workflow_id) is not None
                        else None
                    ),
                    activated_skill_ids=activated,
                    project_skill_locks=project_locks,
                    declared_skill_ids=list(item.skill_ids),
                    capability_id=item.capability,
                    output_type=item.output_artifact_type,
                    capability_skill_id=capability_skill_id,
                    constraint_contract=item.constraint_contract,
                    require_constraint_contract=False,
                ),
                frozen_skills=frozen_skills,
            )
            language_source = plan.video_spec or plan.project_intent
            if language_source is not None:
                item.language_contract = language_source.language_contract
            if item.capability == "atomic.text.generate" and language_source is not None:
                from app.chat.v2.language import video_language_instruction

                language_values = language_source.language_contract.model_dump(mode="json")
                instruction = video_language_instruction(language_values)
                context = context or SkillContext()
                context = context.model_copy(update={
                    "instructions": "\n\n".join(filter(None, (
                        context.instructions.strip(), instruction,
                    ))),
                })
            item.skill_context = context
            item.resolved_skills = list(context.applied_skills) if context else []

    async def start_build(
        self,
        *,
        project_id: str,
        plan_id: str,
        base_project_version_id: str,
        idempotency_key: str,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> Build:
        build = await self.repo.submit_build(
            project_id=project_id,
            plan_id=plan_id,
            base_version_id=base_project_version_id,
            idempotency_key=idempotency_key,
            session_id=session_id,
            user_id=user_id,
        )
        self._schedule_build(build)
        return build

    async def inspect_checkpoint(
        self, *, project_id: str, build_id: str, checkpoint_id: str,
        session_id: str | None = None, user_id: str | None = None,
    ) -> PlanCheckpoint:
        if checkpoint_id == "live":
            build = await self.repo.get_build(project_id, build_id)
            if session_id != build.session_id or user_id != build.user_id:
                raise PermissionError("live PlanPatch requires the bound Session and user")
            plan = await self.repo.get_plan(build.plan_id)
            if not self._is_continuous_plan(plan) or plan.next_checkpoint is None or build.status in {"cancelled", "completed"}:
                raise ValueError("live PlanPatch requires an active continuous build")
            from .continuous_scheduler import _notify_agent
            states = {item.plan_step_id: item for item in await self.repo.list_build_steps(project_id, build_id)}
            completed = {
                item.plan_step_id: await self.repo.get_artifact(project_id, item.result_artifact_version_id)
                for item in states.values() if item.status == "completed" and item.result_artifact_version_id
            }
            checkpoint = await _notify_agent(self, build, plan, states, completed, force=True)
            if checkpoint is None:
                raise ValueError("plan changed while opening a live PlanPatch; inspect again")
            return checkpoint
        checkpoint = await self.repo.get_checkpoint(project_id, build_id, checkpoint_id)
        if session_id is not None and checkpoint.session_id != session_id:
            raise PermissionError("checkpoint does not belong to this DeepSeek Session")
        if user_id is not None and checkpoint.user_id != user_id:
            raise PermissionError("checkpoint does not belong to this user")
        if checkpoint.planning_mode == "agentic" and checkpoint.status != "resolved":
            from .checkpoint_coordinator import refresh_checkpoint
            checkpoint = await refresh_checkpoint(self, checkpoint)
        return checkpoint

    async def resolve_checkpoint(
        self,
        *,
        project_id: str,
        build_id: str,
        checkpoint_id: str,
        resolution: CheckpointResolution,
        session_id: str,
        user_id: str,
    ) -> RebuildPlan:
        if checkpoint_id == "live":
            raise ValueError("inspect live first and submit its concrete checkpoint id")
        checkpoint = await self.inspect_checkpoint(
            project_id=project_id,
            build_id=build_id,
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            user_id=user_id,
        )
        existing = await self.repo.get_operation_result(
            project_id, f"checkpoint:{checkpoint_id}", resolution.idempotency_key,
        )
        if existing is not None:
            return await self.repo.get_plan(existing)
        if checkpoint.base_plan_revision != resolution.base_plan_revision:
            from .repository import PlanRevisionConflict
            raise PlanRevisionConflict(
                resolution.base_plan_revision, checkpoint.base_plan_revision,
            )
        if checkpoint.base_spec_revision != resolution.base_spec_revision:
            from .repository import VideoSpecRevisionConflict
            raise VideoSpecRevisionConflict(
                resolution.base_spec_revision, checkpoint.base_spec_revision,
            )
        plan = await self.repo.get_plan(checkpoint.plan_id)
        if plan.schema_version != 2:
            raise ValueError("legacy build plans cannot resolve semantic checkpoints")
        current_spec_revision = await self.repo.get_video_spec_revision(
            plan.video_spec_revision_id,
        )
        if (checkpoint.planning_mode == "agentic" and not checkpoint.phase.startswith("repair:")
                and resolution.video_spec is None and not resolution.video_spec_patch
                and not resolution.proposed_steps and not resolution.cancel_step_ids
                and not resolution.replace_failed_step_ids and not resolution.phase_inputs
                and not resolution.goal_satisfied and not resolution.waiting_for_input):
            saved = await self.repo.resolve_checkpoint(
                checkpoint=checkpoint, updated_plan=plan, spec_revision=current_spec_revision,
                plan_revision=BuildPlanRevision(
                    plan_id=plan.id, project_id=project_id, revision=plan.current_revision,
                    base_revision=plan.current_revision, checkpoint_id=checkpoint.id,
                    video_spec_revision_id=current_spec_revision.id,
                ),
                idempotency_key=resolution.idempotency_key,
            )
            wake = self._continuous_wakes.get(build_id)
            if wake is not None:
                wake.set()
            self._schedule_build(await self.repo.get_build(project_id, build_id))
            return saved
        intent = plan.project_intent
        intent_base = ({
            "title": intent.title,
            "language": intent.language,
            "language_contract": (
                intent.language_contract.model_dump(mode="json")
                if intent.language_contract is not None else None
            ),
            "target_duration_seconds": intent.target_duration_seconds,
            "aspect_ratio": intent.aspect_ratio,
            "resolution": intent.resolution,
            "workflow_id": intent.workflow_id,
            "style_id": intent.style_id,
            "activated_skill_ids": list(intent.activated_skill_ids),
            "source_asset_ids": list(intent.source_asset_ids),
            "workflow_parameters": dict(intent.workflow_parameters),
            "providers": intent.providers.model_dump(mode="json"),
            "automation": intent.automation.model_dump(mode="json"),
        } if intent is not None else {})
        current_base = {
            key: value for key, value in current_spec_revision.content.items()
            if key in VideoSpec.model_fields
        }
        merged_content = (
            resolution.video_spec.model_dump(mode="json")
            if resolution.video_spec is not None
            else _merge_spec_patch(
                {**intent_base, **current_base},
                resolution.video_spec_patch or {},
            )
        )
        if str(merged_content.get("workflow_id") or "") != plan.workflow_id:
            raise ValueError("checkpoint resolution cannot switch workflows")
        if (
            plan.project_intent is not None
            and "providers" in merged_content
            and merged_content["providers"]
            != plan.project_intent.providers.model_dump(mode="json")
        ):
            raise ValueError("checkpoint resolution cannot switch providers")

        supplied_spec: VideoSpec | None
        try:
            candidate = VideoSpec.model_validate(merged_content)
        except ValueError:
            candidate = None
        if candidate is not None:
            locked = await self._apply_project_skill_locks(project_id, candidate)
            if not isinstance(locked, VideoSpec):
                raise TypeError("resolved VideoSpec has an invalid Skill lock projection")
            supplied_spec = locked
            merged_content = supplied_spec.model_dump(mode="json")
        else:
            supplied_spec = None
        if resolution.goal_satisfied and resolution.proposed_steps:
            raise ValueError("a completed goal cannot add more PlanPatch tasks")
        if resolution.waiting_for_input:
            raise ValueError(
                "automatic video builds cannot wait for user input inside a PlanPatch"
            )

        source_artifacts = {
            item.artifact_id: item
            for item in await self.repo.current_artifacts(project_id)
        }
        shots = merged_content.get("shots")
        referenced_source_ids = set(merged_content.get("source_asset_ids") or [])
        if isinstance(shots, list):
            for shot in shots:
                if isinstance(shot, dict):
                    referenced_source_ids.update(shot.get("reference_asset_ids") or [])
        missing = sorted(referenced_source_ids - set(source_artifacts))
        if missing:
            raise LookupError(
                "VideoSpec references project source assets that do not exist: "
                + ", ".join(missing)
            )
        spec_revision = VideoSpecRevision(
            project_id=project_id,
            revision=current_spec_revision.revision + 1,
            parent_revision_id=current_spec_revision.id,
            content=merged_content,
            resolved_sections=sorted(
                key for key in merged_content if key in VideoSpec.model_fields
            ),
            unresolved_sections=(
                [] if supplied_spec is not None else [
                    key for key in (
                        "characters", "shots", "audio", "timeline"
                    ) if not merged_content.get(key)
                ]
            ),
            source_artifact_version_ids=[
                source_artifacts[item].id for item in sorted(referenced_source_ids)
            ],
            checkpoint_id=checkpoint.id,
            created_by="agent",
            complete=supplied_spec is not None,
        )

        from .moderation_recovery import validate_moderation_patch
        validate_moderation_patch(plan, {
            item.plan_step_id: item for item in await self.repo.list_build_steps(project_id, build_id)
        }, resolution)
        if resolution.replace_failed_step_ids:
            if not self._is_continuous_plan(plan):
                raise ValueError("failed task replacement requires a continuous plan")
            from .plan_repair import expand_repair
            resolution = expand_repair(plan, {
                item.plan_step_id: item for item in await self.repo.list_build_steps(project_id, build_id)
            }, resolution)
        if checkpoint.phase.startswith("repair:") and not resolution.replace_failed_step_ids:
            raise ValueError("failed Build repair must replace failed tasks before resuming")
        cancelled_ids = list(dict.fromkeys(resolution.cancel_step_ids))
        if cancelled_ids:
            build_steps = {
                item.plan_step_id: item
                for item in await self.repo.list_build_steps(project_id, build_id)
            }
            unknown = sorted(set(cancelled_ids) - set(build_steps))
            if unknown:
                raise ValueError("PlanPatch cancels unknown tasks: " + ", ".join(unknown))
            not_pending = sorted(
                step_id for step_id in cancelled_ids
                if build_steps[step_id].status != "pending"
            )
            if not_pending:
                raise ValueError(
                    "PlanPatch can cancel only pending tasks: " + ", ".join(not_pending)
                )
            dependants = sorted(
                item.step_id for item in plan.items
                if item.step_id not in cancelled_ids
                and set(item.depends_on) & set(cancelled_ids)
            )
            if dependants:
                raise ValueError(
                    "cannot cancel tasks required by: " + ", ".join(dependants)
                )
        base_plan = plan.model_copy(deep=True)
        for item in base_plan.items:
            if item.step_id in resolution.replace_failed_step_ids:
                if item.superseded_by:
                    raise ValueError(f"task already replaced: {item.step_id}")
                item.superseded_by = resolution.replace_failed_step_ids[item.step_id]
        if cancelled_ids:
            base_plan.items = [
                item for item in base_plan.items if item.step_id not in cancelled_ids
            ]

        if self._is_continuous_plan(plan) and checkpoint.planning_mode == "agentic":
            from .staged_planning import append_continuous_plan_patch

            if resolution.goal_satisfied:
                build_step_states = await self.repo.list_build_steps(project_id, build_id)
                completed_ids = {
                    item.plan_step_id for item in build_step_states
                    if item.status == "completed"
                }
                completed_plan_items = [
                    item for item in base_plan.items
                    if item.step_id in completed_ids
                    and item.action == "create"
                    and not item.superseded_by
                ]
                has_completed_final_video = any(
                    item.output_artifact_type.lower() in _FINAL_VIDEO_ARTIFACT_TYPES
                    or canonical_capability_id(item.capability) in _FINAL_VIDEO_CAPABILITIES
                    for item in completed_plan_items
                )
                ordered_video_steps = [
                    item.step_id for item in completed_plan_items
                    if "video" in item.output_artifact_type.lower()
                    and item.output_artifact_type.lower() not in _FINAL_VIDEO_ARTIFACT_TYPES
                    and canonical_capability_id(item.capability) not in _FINAL_VIDEO_CAPABILITIES
                ]
                workflow_policy = self._workflow_policy_spec(base_plan.workflow_id)
                from .workflow_plans import workflow_execution_kind

                completion_types = None
                if workflow_policy is not None and workflow_execution_kind(workflow_policy) == "agent_plan_patch":
                    completion_types = workflow_policy.parameters.get("completion_artifact_types", ["video"])
                expects_video = completion_types is None or any(
                    "video" in str(item).lower() for item in completion_types
                )
                if expects_video and len(ordered_video_steps) >= 2 and not has_completed_final_video:
                    revision = base_plan.current_revision + 1
                    resolution = resolution.model_copy(update={
                        "goal_satisfied": False,
                        "proposed_steps": [RebuildPlanItem(
                            step_id=f"auto-final-video-r{revision}",
                            action="create",
                            capability="media.concat",
                            output_artifact_type="final_video",
                            parameters={
                                "video_steps": ordered_video_steps,
                                "normalize": True,
                            },
                            depends_on=ordered_video_steps,
                            objective="Assemble all completed video clips into the final video",
                            estimated_cost=0.02,
                            reason=(
                                "Runtime completion invariant: a multi-clip video goal "
                                "cannot finish without an assembled final video"
                            ),
                        )],
                        "reason": (
                            "Automatically assemble completed clips before accepting "
                            "goal_satisfied"
                        ),
                    })

            if resolution.goal_satisfied:
                active = [
                    item.plan_step_id
                    for item in await self.repo.list_build_steps(project_id, build_id)
                    if item.status in {"pending", "running", "waiting_external"}
                    and item.plan_step_id not in cancelled_ids
                ]
                if active:
                    raise ValueError("goal_satisfied cannot leave active tasks: " + ", ".join(active))
                completed_states = [
                    item for item in await self.repo.list_build_steps(project_id, build_id)
                    if item.status == "completed"
                ]
                completed_ids = {item.plan_step_id for item in completed_states}
                completion_types = None
                if workflow_policy is not None and workflow_execution_kind(workflow_policy) == "agent_plan_patch":
                    completion_types = workflow_policy.parameters.get("completion_artifact_types", ["video"])
                playable = any(
                    item.step_id in completed_ids
                    and (
                        item.action == "create" and item.output_artifact_type in completion_types
                        if completion_types is not None
                        else "video" in item.output_artifact_type.lower()
                    )
                    for item in base_plan.items
                )
                if base_plan.project_intent.constraints.get("edit_existing_project"):
                    # Reused media proves the previous goal, not this edit. Edits
                    # may also produce text/images/audio rather than another video.
                    playable = any(
                        item.step_id in completed_ids and item.action == "create"
                        and item.output_artifact_type not in {"project_intent", "validation_result"}
                        for item in base_plan.items
                    )
                if not playable:
                    raise ValueError(
                        f"goal_satisfied requires a completed {', '.join(completion_types or ['video'])} "
                        "Artifact; queued work is not completion"
                    )
                updated_plan = base_plan
                updated_plan.video_spec = supplied_spec
                updated_plan.video_spec_revision_id = spec_revision.id
                updated_plan.current_revision += 1
                updated_plan.current_phase = "goal_satisfied"
                updated_plan.next_checkpoint = None
                added_ids: list[str] = []
            else:
                build_step_states = await self.repo.list_build_steps(project_id, build_id)
                if not resolution.proposed_steps and not any(
                    item.status in {"pending", "running", "waiting_external"}
                    and item.plan_step_id not in cancelled_ids for item in build_step_states
                ):
                    raise ValueError("PlanPatch must add work or finish the goal when no active tasks remain")
                completed_ids = {
                    item.plan_step_id for item in build_step_states
                    if item.status == "completed"
                }
                artifact_step_ids = {
                    item.result_artifact_version_id: item.plan_step_id
                    for item in build_step_states
                    if item.status == "completed" and item.result_artifact_version_id
                }
                artifact_step_ids.update({
                    item.artifact_version_id: item.step_id
                    for item in base_plan.items
                    if item.action == "reuse" and item.artifact_version_id
                })
                normalized_steps: list[RebuildPlanItem] = []
                existing_step_ids = {item.plan_step_id for item in build_step_states}
                for proposed in resolution.proposed_steps:
                    if proposed.step_id in existing_step_ids:
                        raise ValueError(f"PlanPatch task id was already used: {proposed.step_id}")
                    proposed = proposed.model_copy(deep=True)
                    proposed.superseded_by = None
                    try:
                        capability = self.skills.capabilities.get(proposed.capability)
                    except LookupError as exc:
                        raise ValueError(
                            f"PlanPatch references unavailable capability {proposed.capability}"
                        ) from exc
                    proposed.output_artifact_type = (
                        proposed.output_artifact_type or capability.output_type
                    )
                    input_versions = proposed.input_artifact_version_ids
                    if not isinstance(input_versions, list):
                        raise ValueError("input_artifact_version_ids must be an array")
                    input_versions = list(dict.fromkeys([
                        *[str(value) for value in input_versions],
                        *_implicit_artifact_inputs(
                            proposed.parameters, set(artifact_step_ids),
                        ),
                    ]))
                    proposed.input_artifact_version_ids = input_versions
                    unknown_inputs = sorted(
                        str(value) for value in input_versions
                        if str(value) not in artifact_step_ids
                    )
                    if unknown_inputs:
                        raise ValueError(
                            "PlanPatch references unavailable input ArtifactVersions: "
                            + ", ".join(unknown_inputs)
                        )
                    proposed.depends_on = list(dict.fromkeys([
                        *proposed.depends_on,
                        *(artifact_step_ids[str(value)] for value in input_versions),
                    ]))
                    normalized_steps.append(proposed)
                workflow = self._workflow_policy_spec(plan.workflow_id)
                build_record = await self.repo.get_build(project_id, build_id)
                from app.chat.v2.workflows import (
                    capability_requires_workflow,
                    inject_workflow_parameters,
                )
                available_inputs: dict[str, MediaArtifactVersion] = {}
                for version_id in artifact_step_ids:
                    available_inputs[version_id] = await self.repo.get_artifact(
                        project_id, version_id,
                    )
                for proposed in normalized_steps:
                    capability = self.skills.capabilities.get(proposed.capability)
                    proposed.capability = capability.id
                    if capability.id == "media.concat" and not proposed.parameters.get("video_urls"):
                        proposed.parameters.pop("video_urls", None)
                        proposed.parameters.setdefault("video_steps", list(proposed.depends_on))
                    live_step_ids = {
                        item.step_id for item in [*base_plan.items, *normalized_steps]
                        if not item.superseded_by
                    }
                    proposed.depends_on = list(dict.fromkeys([
                        *proposed.depends_on,
                        *_parameter_step_references(proposed.parameters, live_step_ids),
                    ]))
                    if workflow is not None and capability_requires_workflow(capability.id):
                        proposed.parameters = inject_workflow_parameters(
                            proposed.parameters, workflow,
                        )
                    schema = capability.parameters_schema
                    if build_record.session_id and (
                        not schema
                        or schema.get("additionalProperties") is not False
                        or "thread_id" in schema.get("properties", {})
                        or "project_thread_id" in schema.get("properties", {})
                    ):
                        if "project_thread_id" in schema.get("properties", {}):
                            proposed.parameters.setdefault(
                                "project_thread_id", build_record.session_id,
                            )
                        else:
                            proposed.parameters.setdefault(
                                "thread_id", build_record.session_id,
                            )
                    # Workflow defaults (including continuity_mode) are resolved
                    # before reference binding. Otherwise an Agent-authored step
                    # can acquire shared_reference_images only after the binder
                    # has already let it degrade to text-to-video.
                    _bind_shared_video_references(
                        [*base_plan.items, *normalized_steps], [proposed],
                    )
                    uploaded_source_must_be_declared(proposed)
                    if schema:
                        validator = validator_for(schema)(schema)
                        try:
                            validator.validate(proposed.parameters)
                        except JsonSchemaValidationError as exc:
                            path = ".".join(str(item) for item in exc.absolute_path)
                            location = f" at {path}" if path else ""
                            raise ValueError(
                                f"PlanPatch task {proposed.step_id} has invalid parameters"
                                f"{location}: {exc.message}"
                            ) from exc
                    dependency_output_types = {
                        item.step_id: item.output_artifact_type
                        for item in [*base_plan.items, *normalized_steps]
                    }
                    input_types = {
                        available_inputs[version_id].type
                        for version_id in proposed.input_artifact_version_ids
                    }
                    requirement_types = input_types | {
                        dependency_output_types[step_id]
                        for step_id in proposed.depends_on
                        if dependency_output_types.get(step_id)
                    }
                    missing_input_types = [
                        expected for expected in capability.inputs.required
                        if not any(
                            _artifact_matches_media_type(actual, [expected])
                            for actual in requirement_types
                        )
                    ]
                    if missing_input_types:
                        raise ValueError(
                            f"PlanPatch task {proposed.step_id} is missing inputs: "
                            + ", ".join(missing_input_types)
                        )
                    accepted_types = [
                        *capability.inputs.required,
                        *capability.inputs.soft,
                        *capability.inputs.optional,
                    ]
                    unsupported_types = sorted(
                        actual for actual in input_types
                        if accepted_types and not _artifact_matches_media_type(
                            actual, accepted_types,
                        )
                    )
                    if unsupported_types:
                        raise ValueError(
                            f"PlanPatch task {proposed.step_id} has unsupported inputs: "
                            + ", ".join(unsupported_types)
                        )
                allowed = workflow.allowed_capabilities if workflow is not None else None
                # Plugins opt capabilities into PlanPatch separately from
                # execution registration. Those ids are unioned into every Workflow
                # allow-list so add_tasks can schedule them; generation capabilities
                # stay constrained by the Workflow itself.
                dynamic_capabilities = frozenset(
                    item.capability for item in self.plan_patch_capability_catalog()
                )
                if allowed is not None:
                    allowed = frozenset({*allowed, *dynamic_capabilities})
                updated_plan, added_ids = append_continuous_plan_patch(
                    existing_plan=base_plan,
                    proposed_steps=normalized_steps,
                    allowed_capabilities=allowed,
                    completed_step_ids=completed_ids,
                    spec=supplied_spec,
                    spec_revision_id=spec_revision.id,
                )
        else:
            if supplied_spec is None:
                raise ValueError("staged Workflow checkpoint requires a complete VideoSpec")
            resolution = resolution.model_copy(update={"video_spec": supplied_spec})
            context = PluginContext(project_id=project_id, build_id=build_id, values={
                "video_spec": supplied_spec,
                "base_project_version_id": plan.base_project_version_id,
                "source_artifacts": {
                    key: value for key, value in source_artifacts.items()
                    if key in referenced_source_ids
                },
                "checkpoint": checkpoint,
                "phase_inputs": dict(resolution.phase_inputs),
                "video_spec_revision_id": spec_revision.id,
            })
            plugin = self._workflow_plugin(plan.workflow_id)
            compile_phase = getattr(plugin.implementation, "compile_phase", None)
            if not callable(compile_phase):
                raise LookupError(
                    f"workflow plugin has no staged phase compiler: {plan.workflow_id}"
                )
            updated_plan = await compile_phase(context, checkpoint, resolution, base_plan)
            if updated_plan.workflow_id != plan.workflow_id:
                raise ValueError("workflow compiler changed the locked workflow")
            previous_ids = {item.step_id for item in plan.items}
            added_ids = [
                item.step_id for item in updated_plan.items
                if item.step_id not in previous_ids
            ]
            if not added_ids:
                raise ValueError("checkpoint resolution did not add a build phase")
        await self._resolve_plan_skills(updated_plan, frozen_plan=plan)
        topological_steps(updated_plan.items)
        validate_video_generation_steps(updated_plan.items)
        spec_revision.content["execution_tasks"] = [
            {
                "step_id": item.step_id, "artifact_id": item.output_artifact_id,
                "artifact_type": item.output_artifact_type,
                "capability": item.capability, "parameters": deepcopy(item.parameters),
                "depends_on": list(item.depends_on),
                "input_artifact_version_ids": list(item.input_artifact_version_ids),
                "superseded_by": item.superseded_by,
            }
            for item in updated_plan.items
        ]
        plan_revision = BuildPlanRevision(
            plan_id=plan.id,
            project_id=project_id,
            revision=updated_plan.current_revision,
            base_revision=plan.current_revision,
            checkpoint_id=checkpoint.id,
            video_spec_revision_id=spec_revision.id,
            added_step_ids=added_ids,
            cancelled_step_ids=cancelled_ids,
            reason=resolution.reason or f"Resolved checkpoint {checkpoint.id}",
        )
        saved = await self.repo.resolve_checkpoint(
            checkpoint=checkpoint,
            updated_plan=updated_plan,
            spec_revision=spec_revision,
            plan_revision=plan_revision,
            idempotency_key=resolution.idempotency_key,
        )
        build = await self.repo.get_build(project_id, build_id)
        wake = self._continuous_wakes.get(build_id)
        if wake is not None:
            wake.set()
        self._schedule_build(build)
        return saved

    async def retry_checkpoint(
        self, *, project_id: str, build_id: str, checkpoint_id: str,
    ) -> PlanCheckpoint:
        return await self.repo.retry_checkpoint(project_id, build_id, checkpoint_id)

    def configure_plugin_execution(self, signer: CapabilityGrantSigner) -> int:
        """Register loaded plugin handlers and make them the default Build executor."""
        self._grant_signer = signer
        capabilities = RuntimeCapabilityRegistry(
            CapabilityExecutionGateway(signer, self.plugins),
        )
        count = 0
        for loaded in self.plugins.loaded:
            provider = getattr(loaded.implementation, "capability_handlers", None)
            if provider is None:
                continue
            handlers = provider()
            for capability, operation in handlers.items():
                capabilities.register(
                    plugin_id=loaded.manifest.id,
                    capability=capability,
                    operation=operation,
                )
                count += 1
        if count:
            self._default_executor = PluginBuildStepExecutor(capabilities, signer)
        return count

    def refresh_plugin_execution(self) -> int:
        if self._grant_signer is None:
            return 0
        return self.configure_plugin_execution(self._grant_signer)

    async def recover_active_builds(self) -> int:
        builds = [
            build
            for project in await self._all_projects_for_recovery()
            for build in await self.repo.active_builds(project.id)
            if build.status != "waiting_agent"
            or self._is_continuous_plan(await self.repo.get_plan(build.plan_id))
        ]
        for build in builds:
            self._schedule_build(build)
        return len(builds)

    async def _all_projects_for_recovery(self):
        list_all = getattr(self.repo, "list_all_projects", None)
        if list_all is not None:
            return await list_all()
        projects = getattr(self.repo, "projects", {})
        return list(projects.values())

    def _schedule_build(self, build: Build) -> None:
        if self._default_executor is None or build.status not in {
            "queued", "running", "waiting_external", "waiting_agent",
        } or build.id in self._build_tasks:
            return
        task = asyncio.create_task(self.execute_build(
            project_id=build.project_id,
            build_id=build.id,
            executor=self._default_executor,
        ))
        self._build_tasks[build.id] = task
        task.add_done_callback(
            lambda finished, scheduled=build: self._settle_build_task(scheduled, finished),
        )

    def _settle_build_task(self, scheduled: Build, task: asyncio.Task) -> None:
        build_id = scheduled.id
        self._build_tasks.pop(build_id, None)
        if not task.cancelled():
            task.exception()
            wake = self._continuous_wakes.get(build_id)
            if wake is not None and wake.is_set():
                # A patch may commit after the worker's last read but before
                # this callback releases ownership. Do not lose that wake-up.
                self._schedule_build(scheduled)

    async def cancel_build(self, *, project_id: str, build_id: str) -> Build:
        build = await self.repo.cancel_build(project_id, build_id)
        task = self._build_tasks.get(build_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return build

    async def resume_cancelled_build(self, *, project_id: str, build_id: str) -> Build:
        """Continue only after user confirmation; reuse drafts and reconcile remote jobs."""
        build = await self.repo.resume_cancelled_build(project_id, build_id)
        self._schedule_build(build)
        return build

    async def retry_failed_build(self, *, project_id: str, build_id: str) -> Build:
        from .moderation_recovery import is_moderation
        current = await self.repo.get_build(project_id, build_id)
        plan = await self.repo.get_plan(current.plan_id)
        superseded = {item.step_id for item in plan.items if item.superseded_by}
        if any(is_moderation(item.error) and item.plan_step_id not in superseded
               for item in await self.repo.list_build_steps(project_id, build_id)):
            raise ValueError("Content moderation: unchanged build retry is disabled; inspect the checkpoint for a bounded repair.")
        build = await self.repo.requeue_failed_build(project_id, build_id)
        self._schedule_build(build)
        return build

    async def close(self) -> None:
        tasks = list(self._build_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def complete_build(
        self,
        *,
        build_id: str,
        replacements: dict[str, MediaArtifactVersion],
        validation_results: list[ValidationResult],
        created_artifacts: dict[str, MediaArtifactVersion] | None = None,
    ) -> tuple[Build, ProjectVersion]:
        build, version = await self.repo.commit_build(
            build_id=build_id,
            replacements=replacements,
            validation_results=validation_results,
            created_artifacts=created_artifacts,
        )
        context = PluginContext(project_id=build.project_id, build_id=build.id)
        for artifact in [*replacements.values(), *(created_artifacts or {}).values()]:
            for loaded in self.plugins.loaded:
                await loaded.implementation.on_artifact_committed(context, artifact)
        return build, version

    async def execute_build(
        self, *, project_id: str, build_id: str, executor: BuildStepExecutor,
    ) -> tuple[Build, ProjectVersion | None]:
        # One owner schedules a Build in this Runtime, including manual/API
        # execution racing an automatic checkpoint continuation.
        async with self._execution_locks.setdefault(build_id, asyncio.Lock()):
            return await self._execute_build_owned(
                project_id=project_id, build_id=build_id, executor=executor,
            )

    async def _execute_build_owned(
        self,
        *,
        project_id: str,
        build_id: str,
        executor: BuildStepExecutor,
    ) -> tuple[Build, ProjectVersion | None]:
        """Execute one persisted plan and publish only its atomic version commit."""
        build = await self.repo.get_build(project_id, build_id)
        if build.status == "completed" and build.project_version_id:
            return build, await self.repo.get_project_version(build.project_version_id)
        if build.status in {"failed", "cancelled"}:
            raise ValueError(f"cannot execute {build.status} build")
        try:
            plan = await self.repo.get_plan(build.plan_id)
            if plan.kind == "initial":
                execute_plan_step = getattr(executor, "execute_plan_step", None)
                if execute_plan_step is None:
                    raise TypeError("initial builds require a plan step executor")
                if self._is_continuous_plan(plan):
                    from .continuous_scheduler import execute_continuous_build
                    return await execute_continuous_build(self, build, executor)
                return await self._execute_initial_build(build=build, plan=plan, executor=executor)
            source_by_id = {
                item.id: item for item in await self.repo.current_artifacts(project_id)
            }
            persisted_steps = {
                item.plan_step_id: item
                for item in await self.repo.list_build_steps(project_id, build_id)
            }
            build.status = "running"
            build.message = "Executing rebuild plan"
            await self.repo.update_build(build)
            replacements: dict[str, MediaArtifactVersion] = {}
            created_artifacts: dict[str, MediaArtifactVersion] = {}
            ordered = topological_steps(plan.items)
            executable_items = [
                item for item in ordered if item.action in {"create", "rebuild"}
            ]
            completed_by_step = {
                str(item.metadata.get("plan_step_id") or item.id): item
                for item in source_by_id.values()
            }
            for item in executable_items:
                state = persisted_steps[item.step_id]
                if state.status == "completed" and state.result_artifact_version_id:
                    artifact = await self.repo.get_artifact(
                        project_id, state.result_artifact_version_id,
                    )
                    completed_by_step[item.step_id] = artifact
                    if item.action == "create":
                        created_artifacts[item.step_id] = artifact
                    else:
                        replacements[item.artifact_version_id] = artifact
            for item in plan.items:
                if item.action == "reuse":
                    state = persisted_steps[item.step_id]
                    source = source_by_id.get(item.artifact_version_id)
                    if source is None:
                        raise LookupError(
                            f"planned reuse ArtifactVersion not found: {item.artifact_version_id}"
                        )
                    # Dynamic media plans give selected Artifacts local aliases
                    # (source-1, source-2, ...). Make those aliases available to
                    # downstream plugin steps just like normal plan outputs.
                    completed_by_step[item.step_id] = source
                    if state.status != "completed":
                        state.status = "completed"
                        state.completed_at = now()
                        await self.repo.update_build_step(state)
            for index, item in enumerate(executable_items):
                current = await self.repo.get_build(project_id, build_id)
                if current.status == "cancelled":
                    raise ValueError("build was cancelled")
                source = source_by_id.get(item.artifact_version_id)
                if item.action == "rebuild" and source is None:
                    raise LookupError(
                        f"planned artifact version not found: {item.artifact_version_id}",
                    )
                state = persisted_steps[item.step_id]
                if state.status == "completed" and (
                    item.step_id in created_artifacts
                    or item.artifact_version_id in replacements
                ):
                    continue
                state.status = "running"
                state.attempt += 1
                state.started_at = state.started_at or now()
                state.error = None
                await self.repo.update_build_step(state)
                completed_for_provider: dict[str, MediaArtifactVersion] = dict(source_by_id)
                for existing in source_by_id.values():
                    completed_for_provider[str(existing.metadata.get("plan_step_id") or existing.id)] = existing
                for old_id, rebuilt in replacements.items():
                    completed_for_provider[old_id] = rebuilt
                    old = source_by_id.get(old_id)
                    if old is not None:
                        completed_for_provider[str(old.metadata.get("plan_step_id") or old_id)] = rebuilt
                completed_for_provider.update(completed_by_step)
                try:
                    if item.action == "create":
                        execute_plan_step = getattr(executor, "execute_plan_step", None)
                        if execute_plan_step is None:
                            raise TypeError("incremental create steps require a plan step executor")

                        async def report_remote(operation_id: str, provider: str) -> None:
                            state.remote_operation_id = operation_id
                            state.remote_provider = provider
                            state.status = "waiting_external"
                            await self.repo.update_build_step(state)
                            build.status = "waiting_external"
                            build.message = f"Waiting for {provider} operation for {item.step_id}"
                            await self.repo.update_build(build)

                        effective_step = item
                        if state.remote_operation_id:
                            effective_step = item.model_copy(deep=True)
                            effective_step.parameters["remote_operation_id"] = state.remote_operation_id
                        replacement = await execute_plan_step(
                            build=build,
                            step=effective_step,
                            completed_artifacts={
                                dependency: completed_by_step[dependency]
                                for dependency in item.depends_on
                                if dependency in completed_by_step
                            },
                            idempotency_key=(
                                item.idempotency_key
                                or f"{build.idempotency_key}:{item.step_id}"
                            ),
                            report_remote_operation=report_remote,
                        )
                        build.status = "running"
                    else:
                        assert source is not None
                        effective_source = source.model_copy(deep=True)
                        effective_source.metadata["rebuild_parameters"] = dict(item.parameters)
                        if item.capability:
                            effective_source.metadata["rebuild_capability"] = item.capability
                        effective_source.metadata["resolved_skills"] = [
                            value.model_dump(mode="json") for value in item.resolved_skills
                        ]
                        effective_source.metadata["skill_context"] = (
                            item.skill_context.model_dump(mode="json")
                            if item.skill_context is not None
                            else None
                        )
                        replacement = await executor.rebuild_artifact(
                            build=build,
                            source=effective_source,
                            completed_replacements=completed_for_provider,
                            idempotency_key=f"{build.idempotency_key}:{source.id}",
                        )
                except BaseException as exc:
                    state.status = "failed"
                    state.error = str(exc)
                    await self.repo.update_build_step(state)
                    raise
                replacement.project_id = project_id
                replacement.artifact_id = (
                    item.output_artifact_id
                    if item.action == "create"
                    else source.artifact_id  # type: ignore[union-attr]
                )
                replacement.type = (
                    item.output_artifact_type
                    or (source.type if source is not None else replacement.type)
                )
                replacement.status = "draft"
                replacement.metadata = {
                    **replacement.metadata,
                    "build_id": build.id,
                    "plan_step_id": item.step_id,
                    "capability": item.capability,
                    "rebuild_capability": item.capability,
                    "generation_parameters": dict(item.parameters),
                    "estimated_cost": item.estimated_cost,
                    "resolved_skills": [
                        value.model_dump(mode="json") for value in item.resolved_skills
                    ],
                    "skill_context": (
                        item.skill_context.model_dump(mode="json")
                        if item.skill_context is not None
                        else None
                    ),
                }
                if replacement.type == "video_spec" and isinstance(
                    item.parameters.get("content"), dict,
                ):
                    replacement.metadata["content"] = deepcopy(item.parameters["content"])
                replacement = await self.repo.stage_artifact(replacement)
                completed_by_step[item.step_id] = replacement
                if item.action == "create":
                    created_artifacts[item.step_id] = replacement
                else:
                    assert source is not None
                    replacements[source.id] = replacement
                state.status = "completed"
                state.result_artifact_version_id = replacement.id
                state.completed_at = now()
                await self.repo.update_build_step(state)
                build.actual_cost = round(sum(
                    candidate.estimated_cost
                    for candidate in executable_items
                    if persisted_steps[candidate.step_id].status == "completed"
                ), 6)
                build.progress = (index + 1) / max(1, len(executable_items) + 1)
                build.message = f"Completed {index + 1} of {len(executable_items)} media steps"
                await self.repo.update_build(build)

            validations: list[ValidationResult] = []
            validation_targets = [
                source_by_id[item.artifact_version_id]
                for item in plan.items
                if item.action == "validate" and item.artifact_version_id in source_by_id
            ]
            validation_targets.extend([*replacements.values(), *created_artifacts.values()])
            for artifact in validation_targets:
                results = await self.validate_artifact(build_id=build.id, artifact=artifact)
                if artifact.id in plan.ids_for("validate") and not results:
                    raise ValueError(
                        f"artifact requires validation but no validator handled it: {artifact.id}",
                    )
                if any(not result.passed for result in results):
                    raise ValueError(f"artifact validation failed: {artifact.id}")
                validations.extend(results)
            for item in plan.items:
                if item.action == "validate":
                    state = persisted_steps[item.step_id]
                    state.status = "completed"
                    state.completed_at = now()
                    await self.repo.update_build_step(state)
            return await self.complete_build(
                build_id=build.id,
                replacements=replacements,
                validation_results=validations,
                created_artifacts=created_artifacts,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            current = await self.repo.get_build(project_id, build_id)
            if current.status != "cancelled":
                current.status = "failed"
                current.message = "Build failed; the previous project version remains active"
                current.error = str(exc)
                await self.repo.update_build(current)
            raise

    async def _execute_initial_create_step(
        self,
        *,
        build: Build,
        planned: RebuildPlanItem,
        state: BuildStep,
        completed: dict[str, MediaArtifactVersion],
        executor: BuildStepExecutor,
        retry_limit: int,
    ) -> MediaArtifactVersion:
        """Execute and durably stage one create step.

        The method is deliberately unaware of scheduling.  The initial-build
        scheduler can therefore run a declared independent group concurrently
        while retaining the same retry, remote-job resume and idempotency
        behavior used by a sequential step.
        """
        last_error: BaseException | None = None
        # Reconciliation is not a new paid generation attempt. Even when the
        # local attempt counter reached its retry limit before a process crash,
        # a durable remote operation must still be polled and collected.
        resume_existing_remote = bool(state.remote_operation_id)
        attempts = (
            range(1)
            if resume_existing_remote
            else range(state.attempt, retry_limit + 1)
        )
        for attempt_index, _attempt in enumerate(attempts):
            state.status = "running"
            if not resume_existing_remote:
                state.attempt += 1
            state.started_at = state.started_at or now()
            state.error = None
            await self.repo.update_build_step(state)
            try:
                async def report_remote(operation_id: str, provider: str) -> None:
                    state.remote_operation_id = operation_id
                    state.remote_provider = provider
                    state.status = "waiting_external"
                    await self.repo.update_build_step(state)
                    current_plan = await self.repo.get_plan(build.plan_id)
                    if not self._is_continuous_plan(current_plan):
                        build.status = "waiting_external"
                        build.message = f"Waiting for {provider} operation for {planned.step_id}"
                        await self.repo.update_build(build)

                effective_step = planned
                if state.remote_operation_id:
                    # A provider submission survived a Runtime restart. Feed the
                    # durable operation id back into the provider bridge so it
                    # reconciles/polls the existing job instead of charging for a
                    # duplicate submission.
                    effective_step = planned.model_copy(deep=True)
                    effective_step.parameters["remote_operation_id"] = (
                        state.remote_operation_id
                    )

                artifact = await executor.execute_plan_step(
                    build=build,
                    step=effective_step,
                    completed_artifacts={
                        dependency: completed[dependency]
                        for dependency in planned.depends_on
                        if dependency in completed
                    },
                    idempotency_key=(
                        planned.idempotency_key
                        or f"{build.idempotency_key}:{planned.step_id}"
                    ),
                    report_remote_operation=report_remote,
                )
                artifact.project_id = build.project_id
                artifact.artifact_id = planned.output_artifact_id or artifact.artifact_id
                artifact.type = planned.output_artifact_type or artifact.type
                artifact.status = "draft"
                artifact.metadata = {
                    **artifact.metadata,
                    "build_id": build.id,
                    "plan_step_id": planned.step_id,
                    "capability": planned.capability,
                    "rebuild_capability": planned.capability,
                    "generation_parameters": dict(planned.parameters),
                    "objective": planned.objective,
                    "input_artifact_version_ids": list(
                        planned.input_artifact_version_ids
                    ),
                    "estimated_cost": planned.estimated_cost,
                    "resolved_skills": [
                        value.model_dump(mode="json")
                        for value in planned.resolved_skills
                    ],
                    "skill_context": (
                        planned.skill_context.model_dump(mode="json")
                        if planned.skill_context is not None
                        else None
                    ),
                }
                plan = await self.repo.get_plan(build.plan_id)
                language_source = plan.video_spec or plan.project_intent
                if language_source is not None:
                    language_values = language_source.language_contract.model_dump(mode="json")
                    artifact.metadata.update({
                        "language": language_values["content_language"],
                        "language_contract": language_values,
                        "audience": "user",
                        "content_role": artifact.type,
                    })
                    if artifact.type in {
                        "text", "story", "script", "outline", "character",
                        "scene", "shot", "storyboard", "scenario_product_script",
                    }:
                        body = str(
                            artifact.metadata.get("text")
                            or artifact.metadata.get("content")
                            or artifact.summary
                            or ""
                        )
                        cjk_count = sum(
                            "\u3400" <= character <= "\u9fff" for character in body
                        )
                        latin_count = sum(character.isascii() and character.isalpha() for character in body)
                        expected = language_values["content_language"]
                        passed = not (
                            (expected == "zh-CN" and latin_count >= 400 and cjk_count == 0)
                            or (expected == "en-US" and cjk_count >= 50 and latin_count < cjk_count // 2)
                        )
                        artifact.metadata["language_validation"] = {
                            "expected": expected,
                            "passed": passed,
                            "cjk_characters": cjk_count,
                            "latin_characters": latin_count,
                        }
                        if not passed:
                            raise ValueError(
                                f"user-visible artifact language does not match {expected}"
                            )
                if artifact.type == "video_spec" and isinstance(
                    planned.parameters.get("content"), dict,
                ):
                    artifact.metadata["content"] = deepcopy(
                        planned.parameters["content"],
                    )
                artifact = await self.repo.stage_artifact(artifact)
                completed[planned.step_id] = artifact
                state.status = "completed"
                state.result_artifact_version_id = artifact.id
                state.remote_operation_id = str(
                    artifact.provenance.get("remote_operation_id") or ""
                ) or None
                state.completed_at = now()
                await self.repo.update_build_step(state)
                return artifact
            except asyncio.CancelledError:
                # Keep the durable remote operation (and its attempt) available
                # for reconciliation after shutdown; cancellation is not failure.
                raise
            except Exception as exc:
                last_error = exc
                from .moderation_recovery import is_moderation
                if is_moderation(str(exc)):
                    state.status = "failed"
                    state.error = str(exc)
                    state.completed_at = now()
                    await self.repo.update_build_step(state)
                    raise
                state.status = "failed" if attempt_index + 1 == len(attempts) else "running"
                state.error = str(exc) or repr(exc)
                await self.repo.update_build_step(state)
        if last_error is None:
            raise RuntimeError(
                f"retry limit exhausted for build step {planned.step_id}"
            )
        raise last_error

    async def _execute_initial_build(
        self,
        *,
        build: Build,
        plan: RebuildPlan,
        executor: BuildStepExecutor,
    ) -> tuple[Build, ProjectVersion | None]:
        ordered = topological_steps(plan.items)
        persisted_steps = {
            item.plan_step_id: item
            for item in await self.repo.list_build_steps(build.project_id, build.id)
        }
        completed: dict[str, MediaArtifactVersion] = {}
        for item in persisted_steps.values():
            if item.status == "completed" and item.result_artifact_version_id:
                completed[item.plan_step_id] = await self.repo.get_artifact(
                    build.project_id, item.result_artifact_version_id,
                )
        for planned in ordered:
            if planned.action == "reuse" and planned.artifact_version_id:
                completed[planned.step_id] = await self.repo.get_artifact(
                    build.project_id, planned.artifact_version_id,
                )

        build.status = "running"
        build.message = "Executing initial video build"
        await self.repo.update_build(build)
        validations: list[ValidationResult] = [
            ValidationResult.model_validate(result)
            for artifact in completed.values() if artifact.type == "validation_result"
            for result in artifact.metadata.get("validation_results", [])
        ]
        retry_limit = plan.video_spec.automation.max_artifact_retries if plan.video_spec else 1
        processed_parallel_groups: set[str] = set()
        for index, planned in enumerate(ordered):
            current = await self.repo.get_build(build.project_id, build.id)
            if current.status == "cancelled":
                raise ValueError("build was cancelled")
            state = persisted_steps[planned.step_id]
            if state.status == "completed":
                continue
            if planned.action == "validate":
                state.status = "running"
                state.started_at = state.started_at or now()
                await self.repo.update_build_step(state)
                targets = [completed[item] for item in planned.depends_on if item in completed]
                step_results: list[ValidationResult] = []
                for artifact in targets:
                    step_results.extend(await self.validate_artifact(
                        build_id=build.id, artifact=artifact,
                    ))
                validations.extend(step_results)
                if not step_results:
                    state.status = "failed"
                    state.error = "No validator handled the required artifacts"
                    await self.repo.update_build_step(state)
                    raise ValueError("initial build requires at least one validator result")
                failed_results = [item for item in step_results if not item.passed]
                if failed_results:
                    semantic_failure = any(
                        any(token in item.validator_id.lower() for token in (
                            "continuity", "semantic", "identity", "product",
                        ))
                        for item in failed_results
                    )
                    prior_checkpoints = await self.repo.list_build_checkpoints(
                        build.project_id, build.id,
                    )
                    repaired_before = any(
                        item.phase == "semantic_validation" for item in prior_checkpoints
                    )
                    if plan.schema_version != 2 or not semantic_failure or repaired_before:
                        state.status = "failed"
                        state.error = "; ".join(
                            issue
                            for result in failed_results
                            for issue in result.issues
                        ) or "Artifact validation failed"
                        await self.repo.update_build_step(state)
                        raise ValueError("initial build validation failed")
                    if not plan.video_spec_revision_id:
                        raise ValueError("staged build plan has no VideoSpec revision")
                    spec_revision = await self.repo.get_video_spec_revision(
                        plan.video_spec_revision_id,
                    )
                    session_id, user_id = build.session_id, build.user_id
                    if not session_id or not user_id:
                        project = await self.repo.get_project(build.project_id)
                        binding = await self.repo.latest_session_binding(
                            build.project_id, project.user_id,
                        )
                        session_id, user_id = binding.session_id, binding.user_id
                    state.status = "completed"
                    state.completed_at = now()
                    state.error = "Semantic validation requested one repair pass"
                    await self.repo.update_build_step(state)
                    issues_by_artifact: dict[str, list[str]] = {}
                    for result in failed_results:
                        issues_by_artifact.setdefault(
                            result.artifact_version_id, [],
                        ).extend(result.issues)
                    repair = PlanCheckpoint(
                        project_id=build.project_id,
                        build_id=build.id,
                        plan_id=plan.id,
                        workflow_id=plan.workflow_id,
                        session_id=session_id,
                        user_id=user_id,
                        phase="semantic_validation",
                        next_phase="semantic_repair",
                        required_artifact_types=[item.type for item in targets],
                        artifact_version_ids=[item.id for item in targets],
                        artifact_summaries=[_checkpoint_artifact_summary(
                            item,
                            issues=issues_by_artifact.get(item.id, []),
                        ) for item in targets],
                        resolved_sections=list(spec_revision.resolved_sections),
                        unresolved_sections=["semantic_repair"],
                        planner_instruction=(
                            "Revise only prompts or creative fields implicated by the validation "
                            "issues. This is the single allowed semantic repair pass."
                        ),
                        planning_mode="staged",
                        base_plan_revision=plan.current_revision,
                        base_spec_revision=spec_revision.revision,
                        semantic_repair_attempts=1,
                    )
                    await self.repo.create_checkpoint(repair)
                    return await self.repo.get_build(build.project_id, build.id), None
                state.status = "completed"
                state.completed_at = now()
                await self.repo.update_build_step(state)
            elif planned.action == "reuse":
                if planned.artifact_version_id:
                    completed[planned.step_id] = await self.repo.get_artifact(
                        build.project_id, planned.artifact_version_id,
                    )
                state.status = "completed"
                state.completed_at = now()
                await self.repo.update_build_step(state)
            else:
                group_name = planned.execution_group
                if group_name and group_name not in processed_parallel_groups:
                    grouped = [
                        candidate for candidate in ordered
                        if candidate.execution_group == group_name
                    ]
                    group_ids = {candidate.step_id for candidate in grouped}
                    invalid_dependencies = sorted({
                        dependency
                        for candidate in grouped
                        for dependency in candidate.depends_on
                        if dependency in group_ids
                    })
                    if invalid_dependencies:
                        raise ValueError(
                            f"parallel execution group {group_name!r} contains internal "
                            "dependencies: " + ", ".join(invalid_dependencies)
                        )
                    missing_dependencies = sorted({
                        dependency
                        for candidate in grouped
                        for dependency in candidate.depends_on
                        if (
                            dependency not in persisted_steps
                            or persisted_steps[dependency].status != "completed"
                        )
                    })
                    if missing_dependencies:
                        raise ValueError(
                            f"parallel execution group {group_name!r} started before its "
                            "dependencies completed: " + ", ".join(missing_dependencies)
                        )
                    limits = {
                        candidate.max_parallelism
                        for candidate in grouped
                        if candidate.max_parallelism is not None
                    }
                    if len(limits) > 1:
                        raise ValueError(
                            f"parallel execution group {group_name!r} has inconsistent limits"
                        )
                    limit = min(
                        next(iter(limits), len(grouped)),
                        self.max_parallel_generation_tasks,
                    )
                    semaphore = asyncio.Semaphore(max(1, limit))

                    async def run_group_step(
                        candidate: RebuildPlanItem,
                    ) -> MediaArtifactVersion | None:
                        candidate_state = persisted_steps[candidate.step_id]
                        if candidate_state.status == "completed":
                            return completed.get(candidate.step_id)
                        async with semaphore:
                            return await self._execute_initial_create_step(
                                build=build,
                                planned=candidate,
                                state=candidate_state,
                                completed=completed,
                                executor=executor,
                                retry_limit=retry_limit,
                            )

                    results = await asyncio.gather(
                        *(run_group_step(candidate) for candidate in grouped),
                        return_exceptions=True,
                    )
                    processed_parallel_groups.add(group_name)
                    failures = [result for result in results if isinstance(result, BaseException)]
                    if failures:
                        raise failures[0]
                elif not group_name:
                    await self._execute_initial_create_step(
                        build=build,
                        planned=planned,
                        state=state,
                        completed=completed,
                        executor=executor,
                        retry_limit=retry_limit,
                    )
                build.status = "running"
                build.actual_cost = round(
                    sum(
                        candidate.estimated_cost
                        for candidate in ordered
                        if persisted_steps[candidate.step_id].status == "completed"
                    ),
                    6,
                )

            build.progress = (index + 1) / max(1, len(ordered) + 1)
            build.message = f"Completed {index + 1} of {len(ordered)} build steps"
            await self.repo.update_build(build)

        if plan.schema_version == 2 and plan.next_checkpoint is not None:
            if not plan.video_spec_revision_id:
                raise ValueError("staged build plan has no VideoSpec revision")
            spec_revision = await self.repo.get_video_spec_revision(
                plan.video_spec_revision_id,
            )
            session_id = build.session_id
            user_id = build.user_id
            if not session_id or not user_id:
                project = await self.repo.get_project(build.project_id)
                binding = await self.repo.latest_session_binding(
                    build.project_id, project.user_id,
                )
                session_id = binding.session_id
                user_id = binding.user_id
            definition = plan.next_checkpoint
            required = set(definition.required_artifact_types)
            aliases = {
                "source_image": {"source_image", "image", "character_reference"},
                "source_audio": {"source_audio", "audio", "audio_bgm", "audio_cut"},
            }
            relevant = [
                artifact for artifact in completed.values()
                if not required
                or artifact.type in required
                or any(
                    expected in required and artifact.type in accepted
                    for expected, accepted in aliases.items()
                )
            ]
            missing_types = [
                artifact_type for artifact_type in required
                if not any(
                    artifact.type == artifact_type
                    or artifact.type in aliases.get(artifact_type, set())
                    for artifact in completed.values()
                )
            ]
            if missing_types:
                raise ValueError(
                    "checkpoint required artifacts are missing: " + ", ".join(missing_types)
                )
            checkpoint = PlanCheckpoint(
                project_id=build.project_id,
                build_id=build.id,
                plan_id=plan.id,
                workflow_id=plan.workflow_id,
                session_id=session_id,
                user_id=user_id,
                phase=definition.phase,
                next_phase=definition.next_phase,
                required_artifact_types=list(definition.required_artifact_types),
                artifact_version_ids=[artifact.id for artifact in relevant],
                artifact_summaries=[
                    _checkpoint_artifact_summary(artifact) for artifact in relevant
                ],
                resolved_sections=list(spec_revision.resolved_sections),
                unresolved_sections=list(dict.fromkeys([
                    *spec_revision.unresolved_sections,
                    *definition.resolves,
                ])),
                planner_instruction=definition.planner_instruction,
                planning_mode=definition.planning_mode,
                base_plan_revision=plan.current_revision,
                base_spec_revision=spec_revision.revision,
                max_delivery_attempts=definition.max_planning_attempts,
            )
            await self.repo.create_checkpoint(checkpoint)
            waiting = await self.repo.get_build(build.project_id, build.id)
            return waiting, None

        dependencies: list[ArtifactDependency] = []
        for planned in ordered:
            target = completed.get(planned.step_id)
            if target is None:
                continue
            for dependency_step in planned.depends_on:
                source = completed.get(dependency_step)
                if source is not None:
                    dependencies.append(ArtifactDependency(
                        project_id=build.project_id,
                        source_version_id=source.id,
                        target_version_id=target.id,
                        relation="build_step_dependency",
                    ))
        if (
            plan.schema_version == 2
            and plan.video_spec is None
            and not self._is_continuous_plan(plan)
        ):
            raise ValueError("final staged build requires a complete VideoSpec")
        result = await self.repo.commit_initial_build(
            build_id=build.id,
            artifacts=list(completed.values()),
            dependencies=dependencies,
            validation_results=validations,
        )
        context = PluginContext(project_id=build.project_id, build_id=build.id)
        for artifact in completed.values():
            for loaded in self.plugins.loaded:
                await loaded.implementation.on_artifact_committed(context, artifact)
        return result

    async def add_artifact(
        self, artifact: MediaArtifactVersion, dependencies: list[ArtifactDependency] | None = None,
    ) -> MediaArtifactVersion:
        stored = await self.repo.add_artifact(artifact, dependencies)
        context = PluginContext(project_id=stored.project_id)
        for loaded in self.plugins.loaded:
            await loaded.implementation.on_artifact_committed(context, stored)
        return stored

    async def validate_artifact(
        self, *, build_id: str, artifact: MediaArtifactVersion,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        context = PluginContext(project_id=artifact.project_id, build_id=build_id)
        for loaded in self.plugins.loaded:
            if loaded.manifest.contributions.validators:
                results.extend(await loaded.implementation.validate_artifact(context, artifact))
        return results

    async def select_artifact(
        self, *, project_id: str, version_id: str, base_project_version_id: str, idempotency_key: str,
    ) -> tuple[MediaArtifactVersion, ProjectVersion]:
        return await self.repo.select_artifact(
            project_id=project_id,
            version_id=version_id,
            base_version_id=base_project_version_id,
            idempotency_key=idempotency_key,
        )

    async def export_project(
        self, *, project_id: str, base_project_version_id: str, idempotency_key: str, format: str,
    ) -> ExportRecord:
        return await self.repo.create_export(
            project_id=project_id,
            base_version_id=base_project_version_id,
            idempotency_key=idempotency_key,
            format=format,
        )

    async def restore_project_version(
        self, *, project_id: str, restore_version_id: str,
        base_project_version_id: str, idempotency_key: str,
    ) -> ProjectVersion:
        return await self.repo.restore_project_version(
            project_id=project_id,
            restore_version_id=restore_version_id,
            base_version_id=base_project_version_id,
            idempotency_key=idempotency_key,
        )
