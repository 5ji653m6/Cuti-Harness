"""Adapt Cuti workflow SKILL.md declarations into Video Runtime workflow plugins."""

from __future__ import annotations

from typing import Any

from app.orchestration.workflow_compiler.registry import (
    WorkflowSpec,
)

from .plan_utils import BuildPlanValidationError
from .models import CheckpointResolution, PlanCheckpoint, ProjectIntent, RebuildPlan, VideoSpec
from .plugins import BaseVideoPlugin, PluginContext, VideoPluginRegistry
from .plugins.models import (
    PluginContributions,
    PluginPermissions,
    VideoPluginManifest,
)
from .skills import VideoSkillRuntime
from .workflow_plans import (
    UNAVAILABLE_WORKFLOW_CAPABILITIES,
    UNAVAILABLE_WORKFLOW_MODES,
    WORKFLOW_ID_COMPILERS,
    compile_skill_workflow,
    validate_agentic_workflow_plan,
    validate_original_cuti_workflow_contract,
    workflow_execution_kind,
)
from .staged_planning import (
    append_phase,
    compile_initial_phase,
    copy_plan_with_appended_phase,
    effective_planning_mode,
    failed_checkpoint_step_ids,
)


SKILL_WORKFLOW_PLUGIN_ID = "cuti.skill-workflows"


class SkillWorkflowPlugin(BaseVideoPlugin):
    """Compile installed Workflow Skills through the deterministic build graph."""

    def __init__(self, workflows: dict[str, WorkflowSpec]) -> None:
        self._workflows = dict(workflows)

    def planning_mode(self, workflow_id: str) -> str:
        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            raise LookupError(f"workflow Skill is not installed: {workflow_id}")
        workflow_execution_kind(workflow)
        return effective_planning_mode(workflow, workflow_id)

    def describe_workflows(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for spec in self._workflows.values():
            contract = WORKFLOW_ID_COMPILERS.get(spec.skill_name)
            execution_kind = "unavailable"
            contract_error: str | None = None
            try:
                execution_kind = workflow_execution_kind(spec)
            except BuildPlanValidationError as exc:
                contract_error = str(exc)
            compiler = (
                contract[1]
                if (
                    contract is not None
                    and contract[0] == spec.mode
                    and contract_error is None
                )
                else None
            )
            available = execution_kind != "unavailable"
            result.append({
                "id": spec.skill_name,
                "title": spec.title,
                "mode": spec.mode,
                "parameters": dict(spec.parameters),
                "pipeline": list(spec.pipeline),
                "requiresKeyframe": spec.requires_keyframe,
                "entrypoints": list(spec.entrypoints),
                "skillDependencies": list(spec.skill_dependencies),
                "source": "skill",
                "pluginId": SKILL_WORKFLOW_PLUGIN_ID,
                "available": available,
                "unavailableReason": UNAVAILABLE_WORKFLOW_MODES.get(spec.mode) or contract_error or (
                    None if available
                    else (
                        f"No dedicated compiler for workflow {spec.skill_name} "
                        f"with mode {spec.mode}"
                    )
                ),
                "requiredCapabilities": list(spec.pipeline),
                "missingCapabilities": list(
                    UNAVAILABLE_WORKFLOW_CAPABILITIES.get(spec.mode, [])
                ),
                "userSelectable": available,
                "executionKind": execution_kind,
                "compiler": compiler.__name__ if compiler is not None else None,
                "planning": {
                    "mode": spec.planning.mode,
                    "checkpoints": [
                        {
                            "id": item.id,
                            "afterPhase": item.after_phase,
                            "nextPhase": item.next_phase,
                            "requiredArtifacts": list(item.required_artifacts),
                            "resolves": list(item.resolves),
                        }
                        for item in spec.planning.checkpoints
                    ],
                },
            })
        return result

    async def compile_build_plan(
        self,
        context: PluginContext,
        video_spec: VideoSpec,
    ) -> RebuildPlan:
        workflow = self._workflows.get(video_spec.workflow_id)
        if workflow is None:
            raise LookupError(f"workflow Skill is not installed: {video_spec.workflow_id}")
        if not context.project_id:
            raise ValueError("workflow Skill requires a project")
        return compile_skill_workflow(workflow, context, video_spec)

    async def compile_initial(
        self, context: PluginContext, intent: ProjectIntent,
    ) -> RebuildPlan:
        workflow = self._workflows.get(intent.workflow_id)
        if workflow is None:
            raise LookupError(f"workflow Skill is not installed: {intent.workflow_id}")
        validate_original_cuti_workflow_contract(workflow)
        return compile_initial_phase(workflow=workflow, context=context, intent=intent)

    async def compile_phase(
        self,
        context: PluginContext,
        checkpoint: PlanCheckpoint,
        resolution: CheckpointResolution,
        plan: RebuildPlan,
    ) -> RebuildPlan:
        workflow = self._workflows.get(plan.workflow_id)
        if workflow is None:
            raise LookupError(f"workflow Skill is not installed: {plan.workflow_id}")
        validate_original_cuti_workflow_contract(workflow)
        full_plan = compile_skill_workflow(workflow, context, resolution.video_spec)
        added, next_checkpoint = append_phase(
            existing_plan=plan,
            full_plan=full_plan,
            workflow=workflow,
            checkpoint_id=checkpoint.phase,
            proposed_steps=resolution.proposed_steps,
            repair_step_ids=failed_checkpoint_step_ids(checkpoint),
        )
        updated = copy_plan_with_appended_phase(
            plan,
            spec=resolution.video_spec,
            added_items=added,
            spec_revision_id=str(context.values["video_spec_revision_id"]),
            next_checkpoint=next_checkpoint,
        )
        if effective_planning_mode(workflow, plan.workflow_id) == "agentic":
            validate_agentic_workflow_plan(workflow, updated)
        return updated

async def load_workflow_skills(
    plugins: VideoPluginRegistry,
    skills: VideoSkillRuntime,
) -> int:
    """Register the workflows already validated by the process-owned Skill Runtime."""
    workflows = skills.workflows.items()
    if not workflows:
        return 0
    manifest = VideoPluginManifest(
        id=SKILL_WORKFLOW_PLUGIN_ID,
        version="1.0.0",
        runtime_entrypoint=(
            "app.video_runtime.skill_workflows:SkillWorkflowPlugin"
        ),
        trusted=True,
        contributions=PluginContributions(workflows=sorted(workflows)),
        skills=sorted(workflows),
        permissions=PluginPermissions(sandbox=False),
    )
    await plugins.register(
        manifest,
        SkillWorkflowPlugin(workflows),
        source_path=skills.roots[0],
    )
    return len(workflows)


async def reload_workflow_skills(
    plugins: VideoPluginRegistry,
    skills: VideoSkillRuntime,
) -> int:
    """Reload the unified catalog and replace its generated workflow plugin."""
    skills.reload()
    try:
        plugins.get(SKILL_WORKFLOW_PLUGIN_ID)
    except LookupError:
        pass
    else:
        await plugins.unload(SKILL_WORKFLOW_PLUGIN_ID)
    return await load_workflow_skills(plugins, skills)
