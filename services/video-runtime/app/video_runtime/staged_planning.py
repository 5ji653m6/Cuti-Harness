"""Phase selection for semantic-checkpoint video builds."""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from app.orchestration.workflow_compiler.registry import WorkflowSpec

from .plan_utils import BuildPlanValidationError, topological_steps
from .models import (
    PlanCheckpoint,
    PlanCheckpointDefinition,
    ProjectIntent,
    RebuildPlan,
    RebuildPlanItem,
    VideoSpec,
)
from .plugins import PluginContext


_VIDEO_GENERATION_CAPABILITIES = frozenset({
    "atomic.video.generate",
    "api.provider.generate",
    "api.ark_protocol.generate",
})


def _is_video_generation_item(item: RebuildPlanItem) -> bool:
    if item.capability == "atomic.video.generate":
        return True
    return (
        item.capability in _VIDEO_GENERATION_CAPABILITIES
        and "video" in (item.output_artifact_type or "").lower()
    )


def _prompt_information_length(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len("".join(value.split()))


def _video_duration(parameters: dict) -> float | None:
    for key in ("duration_seconds", "duration", "segment_duration_seconds"):
        value = parameters.get(key)
        try:
            if value is not None and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _validate_video_prompt_detail(
    existing: Iterable[RebuildPlanItem], proposed: Iterable[RebuildPlanItem],
) -> None:
    """Reject accidental synopsis-only prompts after a detailed comparable clip.

    This is a harness-level regression guard, not a Workflow recipe.  Concise prompts
    remain valid when there is no richer baseline or the Agent explicitly records that
    brevity is intentional.
    """
    history: list[tuple[int, float | None]] = []
    candidates = [(item, False) for item in existing]
    candidates.extend((item, True) for item in proposed)
    for item, is_proposed in candidates:
        if not _is_video_generation_item(item):
            continue
        parameters = item.parameters if isinstance(item.parameters, dict) else {}
        length = _prompt_information_length(parameters.get("prompt"))
        duration = _video_duration(parameters)
        comparable = [
            prior_length for prior_length, prior_duration in history
            if duration is None or prior_duration is None
            or 0.5 <= duration / prior_duration <= 2.0
        ]
        if is_proposed and comparable and not parameters.get("allow_concise_prompt"):
            baseline = max(comparable)
            minimum = max(100, int(baseline * 0.45))
            if baseline >= 180 and length < minimum:
                raise BuildPlanValidationError(
                    f"PlanPatch video prompt for {item.step_id} is materially less detailed "
                    f"than a comparable earlier clip ({length} < {minimum} information "
                    "characters). Submit a corrected duration-aware final provider prompt. "
                    "Set allow_concise_prompt=true only when concise wording is an explicit "
                    "creative decision."
                )
        if length:
            history.append((length, duration))


# Staged planning is bound to the authoritative Workflow identity, just like
# the final DAG compiler.  A mode is a compatibility/contract label, not a
# generic implementation selector: a copied or misspelled Workflow must never
# inherit Cuti's source-analysis phase merely by declaring ``mode: mv`` (or any
# other known mode).
WORKFLOW_PLANNING_CONTRACTS: dict[str, tuple[str, str]] = {
    "cinematic": ("seedance2", "direct"),
    "seedance2": ("seedance2", "direct"),
    "mv": ("mv", "music_suno"),
    "short-drama-workflow": ("short_drama_workflow", "story"),
    "cuti-product-workflow": ("cuti_product_workflow", "product_cuti"),
    "cuti-scenario-product-workflow": (
        "cuti_scenario_product_workflow", "product_scenario",
    ),
}


def _planning_family(workflow: WorkflowSpec | None, workflow_id: str) -> str:
    contract = WORKFLOW_PLANNING_CONTRACTS.get(workflow_id)
    if contract is None:
        raise BuildPlanValidationError(
            f"workflow {workflow_id} has no dedicated staged-planning contract"
        )
    expected_mode, family = contract
    if workflow is not None:
        if workflow.skill_name != workflow_id:
            raise BuildPlanValidationError(
                f"staged-planning workflow identity mismatch: {workflow.skill_name} != {workflow_id}"
            )
        if workflow.mode != expected_mode:
            raise BuildPlanValidationError(
                f"workflow {workflow_id} declares mode {workflow.mode}, but its dedicated "
                f"staged-planning contract requires {expected_mode}"
            )
    return family


def _remap_step_references(value, remap: dict[str, str]):
    if isinstance(value, str):
        return remap.get(value, value)
    if isinstance(value, list):
        return [_remap_step_references(item, remap) for item in value]
    if isinstance(value, dict):
        return {
            key: _remap_step_references(item, remap)
            for key, item in value.items()
        }
    return value


def effective_planning_mode(workflow: WorkflowSpec | None, workflow_id: str) -> str:
    """Return explicit Skill policy, with staged defaults for built-in workflows."""
    if workflow is not None and workflow.planning.mode != "full":
        return workflow.planning.mode
    return workflow.planning.mode if workflow is not None else "full"


def initial_checkpoint(workflow: WorkflowSpec | None, workflow_id: str) -> PlanCheckpointDefinition:
    family = _planning_family(workflow, workflow_id)
    planning_mode = effective_planning_mode(workflow, workflow_id)
    if workflow is not None and workflow.planning.checkpoints:
        declared = workflow.planning.checkpoints[0]
        return PlanCheckpointDefinition(
            id=declared.id,
            phase=declared.after_phase,
            next_phase=declared.next_phase,
            required_artifact_types=list(declared.required_artifacts),
            resolves=list(declared.resolves),
            planner_instruction=declared.instruction,
            planning_mode="agentic" if planning_mode == "agentic" else "staged",
        )
    if family == "music_suno":
        return PlanCheckpointDefinition(
            id="music_ready", phase="music_analysis", next_phase="visual_production",
            required_artifact_types=["audiomap", "audio_cut"],
            resolves=["shots", "captions", "timeline"],
            planner_instruction=(
                "Use the real music duration, beat map, lyrics, and cut window to write the "
                "complete VideoSpec. Do not invent timing that conflicts with the artifacts."
            ),
        )
    if family.startswith("product_"):
        if family == "product_scenario":
            instruction = (
                "Use the real product images and analysis to write one causal product story. "
                "Return complete 15-second shots and set workflow_parameters.primary_selling_point "
                "plus workflow_parameters.segment_proofs (one exact proof objective per shot). "
                "Each shot prompt must cover 0-15s densely in Chinese; use native synchronized "
                "dialogue/audio and do not add TTS, BGM, subtitles, keyframes, or Director Skills."
            )
        elif family == "product_cuti":
            instruction = (
                "Use the real product analysis and apply the loaded helper Skills in this exact "
                "order: product-feature-demo-script, product-component-exploded-view when "
                "applicable, then product-voiceover-narration. Return complete independent "
                "15-second segments. Each Seedance prompt must be Chinese and explicitly cover "
                "0-15 seconds. Include native narration, or record the user's explicit "
                "workflow_parameters.narration_mode=music_only decision. Do not add TTS, "
                "keyframes, tail-frame chaining, or a second Director."
            )
        else:
            instruction = (
                "Inspect the actual product source artifacts and create shots that preserve "
                "product identity and verified features."
            )
        return PlanCheckpointDefinition(
            id="product_ready", phase="source_analysis", next_phase="visual_production",
            required_artifact_types=["product_analysis", "source_image"],
            resolves=["characters", "shots", "product_constraints"],
            planner_instruction=instruction,
        )
    if family == "story":
        return PlanCheckpointDefinition(
            id="story_ready", phase="story_intent", next_phase="reference_production",
            required_artifact_types=["story_draft"],
            resolves=["characters", "scenes", "shots", "audio"],
            planner_instruction=(
                "Turn the intent into a complete story VideoSpec. Lock character identity, "
                "scene continuity, shot order, and durations before reference generation. "
                "Put every recurring location in workflow_parameters.scenes with a stable id, "
                "name, and visual description so the Runtime never invents a generic setting."
            ),
        )
    return PlanCheckpointDefinition(
        id="creative_ready", phase="creative_intent", next_phase="visual_production",
        required_artifact_types=["project_intent"],
        resolves=["shots", "references"],
        planner_instruction=(
            "Choose the concrete video actions allowed by this Workflow and produce a complete "
            "VideoSpec. Keep Seedance native audio and do not add unrelated production stages."
        ),
        planning_mode="agentic" if planning_mode == "agentic" else "staged",
    )


def compile_initial_phase(
    *,
    workflow: WorkflowSpec | None,
    context: PluginContext,
    intent: ProjectIntent,
) -> RebuildPlan:
    """Compile only work that can run before later creative facts exist."""
    if not context.project_id:
        raise BuildPlanValidationError("staged workflow requires a project")
    project_id = context.project_id
    sources = dict(context.values.get("source_artifacts") or {})
    items: list[RebuildPlanItem] = []

    def add(
        step_id: str,
        artifact_type: str,
        capability: str,
        *,
        parameters: dict | None = None,
        depends_on: list[str] | None = None,
        action: str = "create",
        artifact_version_id: str = "",
        cost: float = 0,
    ) -> str:
        merged_parameters = dict(parameters or {})
        if capability and workflow is not None:
            for key, value in workflow.parameters.items():
                merged_parameters.setdefault(key, value)
            merged_parameters.setdefault("activated_workflow", workflow.skill_name)
        items.append(RebuildPlanItem(
            step_id=step_id,
            artifact_version_id=artifact_version_id,
            output_artifact_id=f"{project_id}:{step_id}",
            output_artifact_type=artifact_type,
            action=action,
            capability=capability,
            parameters=merged_parameters,
            depends_on=depends_on or [],
            estimated_cost=cost,
            order=len(items) + 1,
            reason="Staged Workflow initial phase",
        ))
        return step_id

    intent_step = add(
        "intent", "project_intent", "runtime.artifact.persist",
        parameters={"title": intent.title, "content": intent.model_dump(mode="json")},
    )
    source_steps: dict[str, str] = {}
    for index, logical_id in enumerate(intent.source_asset_ids, start=1):
        artifact = sources.get(logical_id)
        if artifact is None:
            raise BuildPlanValidationError(f"source artifact is unavailable: {logical_id}")
        source_steps[logical_id] = add(
            f"source-{index}", artifact.type, "", action="reuse",
            artifact_version_id=artifact.id,
        )

    checkpoint = initial_checkpoint(workflow, intent.workflow_id)
    family = _planning_family(workflow, intent.workflow_id)
    if family == "music_suno":
        audio_sources = [
            source_steps[logical_id]
            for logical_id in intent.source_asset_ids
            if sources[logical_id].type in {"source_audio", "audio", "audio_bgm"}
        ]
        if audio_sources:
            music = audio_sources[0]
        else:
            prompt = str(
                intent.workflow_parameters.get("music_prompt")
                or intent.workflow_parameters.get("bgm_prompt")
                or intent.brief
            ).strip()
            music = add(
                "music", "audio_bgm", "suno.generate",
                parameters={
                    "prompt": prompt,
                    "title": intent.title,
                    **{
                        key: value for key, value in intent.workflow_parameters.items()
                        if key in {"tags", "lyrics", "custom_mode", "instrumental", "vocal_gender"}
                    },
                },
                depends_on=[intent_step], cost=0.10,
            )
        analysis = add(
            "music-analysis", "audiomap", "media.audio_analyze",
            parameters={
                "audio_step": music,
                "target_duration_sec": intent.target_duration_seconds,
            },
            depends_on=[music],
        )
        add(
            "music-cut", "audio_cut", "media.audio_cut",
            parameters={
                "audio_step": music,
                "analysis_step": analysis,
                "duration": intent.target_duration_seconds,
            },
            depends_on=[music, analysis],
        )
    elif family.startswith("product_"):
        image_sources = [
            source_steps[logical_id]
            for logical_id in intent.source_asset_ids
            if sources[logical_id].type in {"source_image", "image", "character_reference"}
        ]
        if not image_sources:
            raise BuildPlanValidationError("product workflows require a source image")
        if family == "product_scenario":
            product_instruction = (
                "From the user's brief, product category, visible design, likely audience, and "
                "credible use scenarios, generate candidate consumer benefits. Choose one benefit "
                "with strong dramatic potential and describe a visible cause-and-effect proof. "
                "Do not invent precise specifications, measurements, prices, certifications, "
                "awards, or competitor comparisons."
            )
        else:
            product_instruction = (
                "Extract only visually supported product identity, features, branding, "
                "materials, and constraints. Mark unknown claims as unknown."
            )
        add(
            "product-analysis", "product_analysis", "atomic.text.generate",
            parameters={
                "objective": intent.brief,
                "source_artifact_ids": list(intent.source_asset_ids),
                "instruction": product_instruction,
            },
            depends_on=[intent_step, *image_sources],
        )
    elif family == "story":
        add(
            "story-draft", "story_draft", "atomic.text.generate",
            parameters={
                "objective": intent.brief,
                "target_duration_seconds": intent.target_duration_seconds,
                "language": intent.language,
                "instruction": (
                    "Produce a concise story/script draft only. Do not invent provider "
                    "operations or execute later production phases."
                ),
            },
            depends_on=[intent_step],
        )

    topological_steps(items)
    return RebuildPlan(
        project_id=project_id,
        kind="initial",
        base_project_version_id=str(context.values.get("base_project_version_id") or ""),
        workflow_id=intent.workflow_id,
        project_intent=intent,
        items=items,
        schema_version=2,
        current_revision=1,
        current_phase=checkpoint.phase,
        next_checkpoint=checkpoint,
        estimated_cost=round(sum(item.estimated_cost for item in items), 6),
    )


def compile_continuous_plan_initial(
    *,
    workflow: WorkflowSpec | None,
    context: PluginContext,
    intent: ProjectIntent,
) -> RebuildPlan:
    """Persist only known inputs, then hand planning back to the DeepSeek loop.

    This mirrors Cuti V2's DynamicHarness: the Workflow is a policy boundary,
    not a precompiled production DAG.  The Agent sees the resulting snapshot
    and submits the first executable frontier as a PlanPatch.
    """
    # Do not invoke a production compiler here, even to discard its output.
    # Workflow-specific input acquisition and creative steps belong to the
    # Agent's PlanPatch; the Runtime only registers facts already supplied.
    if not context.project_id:
        raise BuildPlanValidationError("continuous planning requires a project")
    project_id = context.project_id
    sources = dict(context.values.get("source_artifacts") or {})
    items = [RebuildPlanItem(
        step_id="intent",
        output_artifact_id=f"{project_id}:intent",
        output_artifact_type="project_intent",
        action="create",
        capability="runtime.artifact.persist",
        parameters={"title": intent.title, "content": intent.model_dump(mode="json")},
        order=1,
        reason="Register the user's goal before Agent planning",
    )]
    for index, logical_id in enumerate(intent.source_asset_ids, start=1):
        artifact = sources.get(logical_id)
        if artifact is None or artifact.project_id != project_id:
            raise BuildPlanValidationError(f"source artifact is unavailable: {logical_id}")
        items.append(RebuildPlanItem(
            step_id=f"source-{index}",
            artifact_version_id=artifact.id,
            output_artifact_id=f"{project_id}:source-{index}",
            output_artifact_type=artifact.type,
            action="reuse",
            order=len(items) + 1,
            reason="Reuse an existing project source without generation",
        ))
    checkpoint = PlanCheckpointDefinition(
        id="agent-plan-ready",
        phase="goal_received",
        next_phase="agent_execution",
        required_artifact_types=["project_intent"],
        resolves=["next_plan_patch"],
        planner_instruction=(
            "Inspect the current project snapshot and the loaded Workflow contract. "
            "Submit the next tasks and their dependencies. Each task completion or "
            "failure can trigger another planning turn while other work continues. "
            "The loaded Workflow supplies creative choices the user left open. "
            "Bind shot timing and media references to artifacts that already exist."
        ),
        planning_mode="agentic",
    )
    return RebuildPlan(
        project_id=project_id,
        kind="initial",
        base_project_version_id=str(context.values.get("base_project_version_id") or ""),
        workflow_id=intent.workflow_id,
        project_intent=intent,
        items=items,
        schema_version=2,
        current_revision=1,
        current_phase="goal_received",
        next_checkpoint=checkpoint,
        estimated_cost=0,
    )


def append_continuous_plan_patch(
    *,
    existing_plan: RebuildPlan,
    proposed_steps: Iterable[RebuildPlanItem],
    allowed_capabilities: frozenset[str] | None,
    completed_step_ids: set[str],
    spec: VideoSpec | None,
    spec_revision_id: str,
) -> tuple[RebuildPlan, list[str]]:
    """Append Agent tasks; the scheduler admits only dependencies that are ready."""
    proposed = [item.model_copy(deep=True) for item in proposed_steps]
    if len(proposed) > 8:
        raise BuildPlanValidationError("PlanPatch may add at most eight ready tasks")
    existing_ids = {item.step_id for item in existing_plan.items}
    proposed_ids = {item.step_id for item in proposed}
    if len(proposed_ids) != len(proposed):
        raise BuildPlanValidationError("PlanPatch contains duplicate task ids")
    overlap = sorted(existing_ids & proposed_ids)
    if overlap:
        raise BuildPlanValidationError("plan step already exists: " + ", ".join(overlap))
    _validate_video_prompt_detail(existing_plan.items, proposed)
    for item in proposed:
        if item.action not in {"create", "validate"}:
            raise BuildPlanValidationError(
                "PlanPatch tasks may only create or validate artifacts"
            )
        if not item.capability:
            raise BuildPlanValidationError(f"PlanPatch task {item.step_id} has no capability")
        if not item.output_artifact_type:
            raise BuildPlanValidationError(
                f"PlanPatch task {item.step_id} has no output_artifact_type"
            )
        if allowed_capabilities is not None and item.capability not in allowed_capabilities:
            raise BuildPlanValidationError(
                f"workflow does not allow capability {item.capability}"
            )
        missing = sorted(set(item.depends_on) - (existing_ids | proposed_ids))
        if missing:
            raise BuildPlanValidationError(
                f"PlanPatch task {item.step_id} depends on unknown tasks: {missing}"
            )
        item.output_artifact_id = (
            item.output_artifact_id
            or f"{existing_plan.project_id}:{item.step_id}"
        )
        item.order = len(existing_plan.items) + proposed.index(item) + 1
        item.reason = item.reason or "Agent-authored continuous PlanPatch"

    updated = deepcopy(existing_plan)
    updated.items.extend(proposed)
    updated.video_spec = spec
    updated.video_spec_revision_id = spec_revision_id
    updated.current_revision += 1
    updated.current_phase = "agent_execution"
    updated.next_checkpoint = PlanCheckpointDefinition(
        id=f"agent-plan-ready-{updated.current_revision}",
        phase="task_completed_or_failed",
        next_phase="agent_execution",
        required_artifact_types=[],
        resolves=["next_plan_patch"],
        planner_instruction=(
            "Inspect newly completed Artifacts and failed tasks, then append tasks or "
            "cancel pending work. Set goal_satisfied only after the Workflow's declared "
            "deliverable exists (a playable video by default, or completion_artifact_types "
            "from its parameters) and no active work remains."
        ),
        planning_mode="agentic",
    )
    updated.estimated_cost = round(
        sum(item.estimated_cost for item in updated.items), 6,
    )
    topological_steps(updated.items)
    return updated, [item.step_id for item in proposed]


def next_checkpoint_for(
    workflow: WorkflowSpec | None,
    workflow_id: str,
    checkpoint_id: str,
) -> PlanCheckpointDefinition | None:
    if workflow is not None and workflow.planning.checkpoints:
        declared = list(workflow.planning.checkpoints)
        current = next((
            index for index, item in enumerate(declared)
            if item.id == checkpoint_id or item.after_phase == checkpoint_id
        ), -1)
        if current >= 0 and current + 1 < len(declared):
            value = declared[current + 1]
            return PlanCheckpointDefinition(
                id=value.id,
                phase=value.after_phase,
                next_phase=value.next_phase,
                required_artifact_types=list(value.required_artifacts),
                resolves=list(value.resolves),
                planner_instruction=value.instruction,
                planning_mode=(
                    "agentic" if effective_planning_mode(workflow, workflow_id) == "agentic"
                    else "staged"
                ),
            )
    return None


def append_phase(
    *,
    existing_plan: RebuildPlan,
    full_plan: RebuildPlan,
    workflow: WorkflowSpec | None,
    checkpoint_id: str,
    proposed_steps: Iterable[RebuildPlanItem] = (),
    repair_step_ids: Iterable[str] = (),
) -> tuple[list[RebuildPlanItem], PlanCheckpointDefinition | None]:
    """Select the next safe phase from a complete compiler result."""
    existing_ids = {item.step_id for item in existing_plan.items}
    if checkpoint_id == "semantic_validation":
        requested = {value for value in repair_step_ids if value}
        if requested:
            full_ids = {item.step_id for item in full_plan.items}
            unknown = sorted(requested - full_ids)
            if unknown:
                raise BuildPlanValidationError(
                    "semantic repair references unknown steps: " + ", ".join(unknown)
                )
            affected = set(requested)
            changed = True
            while changed:
                changed = False
                for item in full_plan.items:
                    if item.step_id not in affected and set(item.depends_on) & affected:
                        affected.add(item.step_id)
                        changed = True
            candidates = [
                item.model_copy(deep=True) for item in full_plan.items
                if item.step_id in affected and item.action in {"create", "validate"}
            ]
        else:
            # Compatibility fallback for old checkpoints that predate
            # per-artifact issue attribution.
            immutable_types = {
                "project_intent", "video_spec", "script", "characters", "storyboard",
                "outline", "scenes", "shots", "source_image", "source_audio",
                "source_video", "audiomap", "audio_cut",
            }
            candidates = [
                item.model_copy(deep=True) for item in full_plan.items
                if (
                    item.action == "validate"
                    or (item.action == "create" and item.output_artifact_type not in immutable_types)
                )
            ]
        remap = {item.step_id: f"{item.step_id}-repair-1" for item in candidates}
        for item in candidates:
            original_id = item.step_id
            item.step_id = remap[original_id]
            item.depends_on = [remap.get(value, value) for value in item.depends_on]
            item.parameters = _remap_step_references(item.parameters, remap)
            item.idempotency_key = ""
            item.reason = f"One-time semantic repair of {original_id}"
        known = existing_ids | {item.step_id for item in candidates}
        for item in candidates:
            missing = sorted(set(item.depends_on) - known)
            if missing:
                raise BuildPlanValidationError(
                    f"repair step {item.step_id} has unknown dependencies: {missing}"
                )
        topological_steps([*existing_plan.items, *candidates])
        return candidates, None
    proposed = [item.model_copy(deep=True) for item in proposed_steps]
    if proposed:
        if effective_planning_mode(workflow, existing_plan.workflow_id) != "agentic":
            raise BuildPlanValidationError("only agentic workflows accept proposed_steps")
        allowed = workflow.allowed_capabilities if workflow is not None else None
        for item in proposed:
            if item.step_id in existing_ids:
                raise BuildPlanValidationError(f"plan step already exists: {item.step_id}")
            if allowed is not None and item.capability not in allowed:
                raise BuildPlanValidationError(
                    f"workflow does not allow capability {item.capability}"
                )
            if item.action not in {"create", "validate"}:
                raise BuildPlanValidationError("agentic phases may only create or validate artifacts")
        known = existing_ids | {item.step_id for item in proposed}
        for item in proposed:
            missing = sorted(set(item.depends_on) - known)
            if missing:
                raise BuildPlanValidationError(
                    f"agentic step {item.step_id} has unknown dependencies: {missing}"
                )
        topological_steps([*existing_plan.items, *proposed])
        return proposed, next_checkpoint_for(workflow, existing_plan.workflow_id, checkpoint_id)

    remaining = [
        item.model_copy(deep=True) for item in full_plan.items
        if item.step_id not in existing_ids
    ]
    next_checkpoint = next_checkpoint_for(workflow, existing_plan.workflow_id, checkpoint_id)
    if next_checkpoint is not None:
        future_phase = next_checkpoint.phase
        if future_phase == "reference_production":
            selected = [
                item for item in remaining
                if item.step_id in {"spec", "script", "characters", "storyboard", "outline", "scenes", "shots", "narration", "bgm"}
                or (item.step_id.startswith("character-") and item.step_id.endswith("-reference"))
                or (item.step_id.startswith("scene-") and item.step_id.endswith("-reference"))
            ]
        elif future_phase == "keyframe_production":
            # Cuti's keyframe workflow completes the full keyframe stage before
            # inspecting those real images and planning video motion.
            selected = [
                item for item in remaining if item.output_artifact_type == "keyframe"
            ]
        else:
            selected = remaining
    else:
        selected = remaining
    selected_ids = existing_ids | {item.step_id for item in selected}
    for item in selected:
        missing = sorted(set(item.depends_on) - selected_ids)
        if missing:
            raise BuildPlanValidationError(
                f"phase step {item.step_id} depends on a later phase: {missing}"
            )
    topological_steps([*existing_plan.items, *selected])
    return selected, next_checkpoint


def failed_checkpoint_step_ids(checkpoint: PlanCheckpoint) -> list[str]:
    """Return only plan steps whose artifacts carry validation issues."""
    return list(dict.fromkeys(
        str(metadata.get("plan_step_id"))
        for summary in checkpoint.artifact_summaries
        if summary.get("issues")
        for metadata in [summary.get("metadata") or {}]
        if metadata.get("plan_step_id")
    ))


def completed_spec_revision_sections(spec: VideoSpec) -> list[str]:
    return [
        "title", "format", "workflow", "style", "characters", "shots", "audio",
        "providers", "automation", "timeline",
    ]


def copy_plan_with_appended_phase(
    plan: RebuildPlan,
    *,
    spec: VideoSpec,
    added_items: list[RebuildPlanItem],
    spec_revision_id: str,
    next_checkpoint: PlanCheckpointDefinition | None,
) -> RebuildPlan:
    updated = deepcopy(plan)
    updated.items.extend(added_items)
    updated.video_spec = spec
    updated.video_spec_revision_id = spec_revision_id
    updated.current_revision += 1
    updated.current_phase = (
        next_checkpoint.phase if next_checkpoint is not None else "final_production"
    )
    updated.next_checkpoint = next_checkpoint
    updated.estimated_cost = round(
        sum(item.estimated_cost for item in updated.items), 6,
    )
    topological_steps(updated.items)
    return updated
