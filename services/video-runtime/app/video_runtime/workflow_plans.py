"""Deterministic compilers for the distinct Cuti Workflow Skill families."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.orchestration.workflow_compiler.registry import WorkflowSpec

from .plan_utils import BuildPlanValidationError, topological_steps
from .models import MediaArtifactVersion, RebuildPlan, RebuildPlanItem, VideoSpec
from .plugins import PluginContext


UNAVAILABLE_WORKFLOW_MODES: dict[str, str] = {}

UNAVAILABLE_WORKFLOW_CAPABILITIES: dict[str, list[str]] = {}

SUPPORTED_WORKFLOW_MODES = {
    "seedance2", "mv", "short_drama_workflow",
    "cuti_product_workflow", "cuti_scenario_product_workflow",
}


# Immutable execution declarations copied from the original Cuti Workflow
# frontmatter.  ``planning`` is intentionally absent: staged planning is a
# Harness extension, while these fields are the Cuti workflow's source
# contract and must not drift during migration.
ORIGINAL_CUTI_WORKFLOW_CONTRACTS: dict[str, dict[str, Any]] = {
    "seedance2": {
        "mode": "seedance2",
        "pipeline": (
            "atomic.text.generate", "atomic.image.generate",
            "api.provider.generate", "api.ark_protocol.generate", "media.concat",
        ),
        "requires_keyframe": False,
        "parameters": {"shot_workflow_mode": "seedance2_script"},
    },
    "short-drama-workflow": {
        "mode": "short_drama_workflow",
        "pipeline": (
            "atomic.text.generate", "atomic.image.generate", "atomic.video.generate",
            "media.concat", "media.transcribe", "subtitle.compose",
            "media.subtitle_burn",
        ),
        "requires_keyframe": False,
        "parameters": {
            "shot_workflow_mode": "seedance2_short_drama",
            "content_category": "short_drama",
            "segment_duration_seconds": 15,
            "segment_execution_mode": "parallel",
            "video_generation_mode": "t2v",
            "continuity_mode": "shared_reference_images",
        },
    },
    "cuti-product-workflow": {
        "mode": "cuti_product_workflow",
        "pipeline": (
            "atomic.text.generate", "atomic.image.generate", "api.provider.generate",
            "api.ark_protocol.generate", "media.concat",
        ),
        "requires_keyframe": False,
        "parameters": {
            "workflow_mode": "cuti_product_workflow",
            "shot_workflow_mode": "seedance2_product_ad",
            "content_category": "product_ad",
            "concept_image_model": "gpt-image-2",
            "segment_duration_seconds": 15,
        },
    },
    "cuti-scenario-product-workflow": {
        "mode": "cuti_scenario_product_workflow",
        "pipeline": (
            "atomic.text.generate", "atomic.image.generate", "api.provider.generate",
            "api.ark_protocol.generate", "media.concat",
        ),
        "requires_keyframe": False,
        "parameters": {
            "workflow_mode": "cuti_scenario_product_workflow",
            "shot_workflow_mode": "seedance2_scenario_product_ad",
            "content_category": "scenario_product_ad",
            "segment_duration_seconds": 15,
        },
    },
    # $mv was installed in Cuti's runtime Skill store rather than the checked-in
    # source tree.  Its migrated SKILL.md is nevertheless locked here for the
    # same fail-closed behavior as the checked-in workflows.
    "mv": {
        "mode": "mv",
        "pipeline": (
            "suno.generate", "media.audio_analyze",
            "media.audio_cut", "atomic.image.generate", "api.provider.generate",
            "media.concat", "media.mix_audio", "media.transcribe",
            "media.hyperframes_caption",
        ),
        "requires_keyframe": False,
        "parameters": {"workflow_mode": "mv"},
    },
}


def validate_original_cuti_workflow_contract(workflow: WorkflowSpec) -> None:
    """Reject migrated Workflow metadata that no longer matches Cuti's source."""
    expected = ORIGINAL_CUTI_WORKFLOW_CONTRACTS.get(workflow.skill_name)
    if workflow.skill_name == "cinematic":
        # A new derivative, not a claimed original Cuti workflow.
        expected = {
            **ORIGINAL_CUTI_WORKFLOW_CONTRACTS["seedance2"],
            "parameters": {"shot_workflow_mode": "seedance2_script", "reference_mode": "multi_reference"},
        }
    if expected is None:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} has no locked original Cuti contract"
        )
    if workflow.mode != expected["mode"]:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} declares mode {workflow.mode}, but the original "
            f"Cuti contract requires {expected['mode']}"
        )
    if tuple(workflow.pipeline) != expected["pipeline"]:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} pipeline differs from the original Cuti contract"
        )
    if workflow.requires_keyframe is not expected["requires_keyframe"]:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} requires_keyframe differs from the original "
            "Cuti contract"
        )
    mismatches = {
        key: (workflow.parameters.get(key), value)
        for key, value in expected["parameters"].items()
        if workflow.parameters.get(key) != value
    }
    if mismatches:
        details = ", ".join(
            f"{key}={actual!r} (expected {wanted!r})"
            for key, (actual, wanted) in sorted(mismatches.items())
        )
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} parameters differ from the original Cuti "
            f"contract: {details}"
        )


def workflow_execution_kind(workflow: WorkflowSpec) -> str:
    """Admit named Cuti compilers or explicitly agent-planned installed Skills.

    A Skill's allowlist restricts execution; it never grants provider, network,
    or sandbox permissions. New Skills cannot inherit a named production DAG.
    """
    if workflow.mode in UNAVAILABLE_WORKFLOW_MODES:
        raise BuildPlanValidationError(UNAVAILABLE_WORKFLOW_MODES[workflow.mode])
    if workflow.skill_name in WORKFLOW_ID_COMPILERS:
        validate_original_cuti_workflow_contract(workflow)
        return "dedicated_compiler"
    if workflow.planning.mode != "agentic":
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} requires planning.mode=agentic "
            "or an explicitly installed dedicated compiler"
        )
    if not workflow.allowed_capabilities:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} requires non-empty allowed_capabilities"
        )
    outputs = workflow.parameters.get("completion_artifact_types", ["video"])
    if not isinstance(outputs, list) or not outputs or any(
        not isinstance(item, str) or not item.strip()
        or item in {"project_intent", "validation", "validation_result"}
        or item.startswith("source_") for item in outputs
    ):
        raise BuildPlanValidationError("completion_artifact_types must list generated deliverable types")
    return "agent_plan_patch"


class WorkflowPlanBuilder:
    def __init__(self, workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec) -> None:
        if not context.project_id:
            raise BuildPlanValidationError("workflow requires a project")
        self.workflow = workflow
        self.project_id = context.project_id
        self.base_version_id = str(context.values.get("base_project_version_id") or "")
        self.spec = spec
        self.items: list[RebuildPlanItem] = []
        self.sources: dict[str, MediaArtifactVersion] = dict(
            context.values.get("source_artifacts") or {},
        )
        self.source_steps: dict[str, str] = {}

    def add(
        self,
        step_id: str,
        artifact_type: str,
        capability: str,
        *,
        parameters: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        cost: float = 0.0,
        skills: list[str] | None = None,
        action: str = "create",
        artifact_version_id: str = "",
        execution_group: str | None = None,
        max_parallelism: int | None = None,
    ) -> str:
        merged = dict(parameters or {})
        if self.spec.workflow_parameters:
            merged.setdefault("workflow_parameters", dict(self.spec.workflow_parameters))
        if capability:
            # Original Cuti stage Workflows carry their engine/workflow mode on
            # every task, not only provider leaves.  Keeping it on Runtime,
            # media and validation steps makes recovery/audit deterministic and
            # prevents a later executor from guessing a generic workflow.
            for key, value in self.workflow.parameters.items():
                merged.setdefault(key, value)
            merged.setdefault("activated_workflow", self.workflow.skill_name)
        self.items.append(RebuildPlanItem(
            step_id=step_id,
            artifact_version_id=artifact_version_id,
            output_artifact_id=f"{self.project_id}:{step_id}",
            output_artifact_type=artifact_type,
            action=action,
            capability=capability,
            parameters=merged,
            depends_on=list(dict.fromkeys(depends_on or [])),
            estimated_cost=cost,
            order=len(self.items) + 1,
            execution_group=execution_group,
            max_parallelism=max_parallelism,
            reason=f"Workflow Skill: {self.workflow.title}",
            skill_ids=skills or [],
        ))
        return step_id

    def add_sources(self) -> dict[str, str]:
        logical_ids = list(self.spec.source_asset_ids)
        for shot in self.spec.shots:
            logical_ids.extend(shot.reference_asset_ids)
        for index, logical_id in enumerate(dict.fromkeys(logical_ids), start=1):
            artifact = self.sources.get(logical_id)
            if artifact is None:
                raise BuildPlanValidationError(f"source artifact is unavailable: {logical_id}")
            step_id = self.add(
                f"source-{index}", artifact.type, "",
                action="reuse", artifact_version_id=artifact.id,
            )
            self.source_steps[logical_id] = step_id
        return self.source_steps

    def character_references(
        self,
        manifest_step: str,
        *,
        skills: list[str] | None = None,
        reference_from_steps: list[str] | None = None,
    ) -> dict[str, str]:
        # Stage guidance is resolved centrally from the Workflow, selected
        # Skills and capability contract.  A compiler must not silently inject
        # the legacy per-agent Director chain.
        if skills is None:
            skills = []
        identity_refs = list(dict.fromkeys(reference_from_steps or []))
        result: dict[str, str] = {}
        for character in self.spec.characters:
            parameters: dict[str, Any] = {
                "prompt": (
                    f"Reusable character identity sheet for {character.name}. "
                    f"Appearance: {character.appearance}; clothing: {character.clothing}; "
                    f"personality: {character.personality}"
                ),
                "model": self.spec.providers.image,
                "aspect_ratio": self.spec.aspect_ratio,
                "character_id": character.id,
                "artifact_role": "character_reference",
            }
            if identity_refs:
                parameters["reference_from_steps"] = identity_refs
            result[character.id] = self.add(
                f"character-{character.id}-reference", "character_reference",
                "atomic.image.generate",
                parameters=parameters,
                depends_on=[manifest_step, *identity_refs], cost=0.08,
                skills=skills,
            )
        return result

    def scene_references(
        self,
        manifest_step: str,
        *,
        reference_from_steps: list[str] | None = None,
    ) -> list[str]:
        """Create reusable empty-location references declared by the VideoSpec.

        Original Cuti stage workflows create scene references separately from
        character references.  Keeping the roles separate prevents the image
        provider from accidentally producing a combined cast/product/location
        board and gives later video steps auditable reference purposes.
        """
        raw_scenes = self.spec.workflow_parameters.get("scenes") or []
        if not isinstance(raw_scenes, list) or not raw_scenes:
            # In original Cuti these workflows have a real scene-generation
            # stage. In the staged Harness that creative decision belongs to
            # DeepSeek and must be persisted before reference production.
            # Inventing a generic location here would silently collapse the
            # distinct stage workflows back into one default implementation.
            raise BuildPlanValidationError(
                f"{self.workflow.skill_name} requires workflow_parameters.scenes "
                "from the completed scene-planning stage"
            )
        identity_refs = list(dict.fromkeys(reference_from_steps or []))
        result: list[str] = []
        for index, scene in enumerate(raw_scenes, start=1):
            value = scene if isinstance(scene, dict) else {"description": str(scene)}
            scene_id = str(value.get("id") or value.get("name") or index)
            safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", scene_id).strip("-") or str(index)
            description = str(
                value.get("description") or value.get("setting") or value.get("name") or ""
            ).strip()
            parameters: dict[str, Any] = {
                "prompt": (
                    "Create exactly one unoccupied environment-only recurring-location reference. "
                    f"Location: {description or 'derive the approved recurring location from the script'}. "
                    "Use a single coherent wide or three-quarter architectural view. Preserve spatial "
                    "layout, surfaces, palette, time of day, lighting, weather, and stable environmental "
                    "details. Keep foreground and midground clear and unused. One frame only, without "
                    "signage, readable text, panels, contact-sheet layout, or decorative borders."
                ),
                "model": self.spec.providers.image,
                "aspect_ratio": self.spec.aspect_ratio,
                "scene_id": scene_id,
                "artifact_role": "scene_reference",
            }
            if identity_refs:
                parameters["reference_from_steps"] = identity_refs
            result.append(self.add(
                f"scene-{safe_id}-reference", "scene_reference", "atomic.image.generate",
                parameters=parameters,
                depends_on=[manifest_step, *identity_refs],
                cost=0.08,
                skills=[],
            ))
        return result

    def image_refs_for_shot(self, shot) -> list[str]:
        ids = shot.reference_asset_ids or self.spec.source_asset_ids
        return [
            self.source_steps[item]
            for item in ids
            if (
                item in self.source_steps
                and item in self.sources
                and self.sources[item].type in {
                    "source_image", "image", "product_reference",
                    "character_reference", "scene_reference", "keyframe",
                }
            )
        ]

    def finish(
        self, clips: list[str], *, transition: float, require_audio: bool,
        audio_step: str = "", captions: bool = False,
    ) -> RebuildPlan:
        timeline = self.add(
            "timeline", "timeline", "media.timeline.compose",
            parameters={
                "shots": [shot.model_dump(mode="json") for shot in self.spec.shots],
                "video_steps": clips,
            }, depends_on=clips,
        )
        if audio_step:
            assembled = self.add(
                "assembled-video", "video_assembled", "media.concat",
                parameters={
                    "video_steps": clips, "normalize": True,
                    "transition_duration": transition,
                }, depends_on=clips, cost=0.02,
            )
            mix_id = "mixed-video" if captions else "final-video"
            mixed = self.add(
                mix_id, "video_mixed" if captions else "final_video", "media.mix_audio",
                parameters={
                    "video_step": assembled, "audio_step": audio_step, "mode": "replace",
                    "audio_volume": 1.0, "final_output": not captions,
                    "require_audio": require_audio,
                    "target_duration_seconds": self.spec.target_duration_seconds,
                }, depends_on=[assembled, audio_step], cost=0.01,
            )
            final_video = mixed
            if captions:
                transcription = self.add(
                    "transcription", "transcription", "media.transcribe",
                    parameters={"video_step": mixed, "language": self.spec.language},
                    depends_on=[mixed],
                )
                caption = {
                    "video_step": mixed, "transcription_step": transcription,
                    "final_output": True, "require_audio": True,
                    "require_subtitles": True,
                    "target_duration_seconds": self.spec.target_duration_seconds,
                }
                wp = self.spec.workflow_parameters or {}
                if wp.get("caption_html"):
                    caption["caption_html"] = wp["caption_html"]
                if wp.get("composition_html"):
                    caption["composition_html"] = wp["composition_html"]
                final_video = self.add(
                    "final-video", "final_video", "media.hyperframes_caption",
                    parameters=caption, depends_on=[mixed, transcription], cost=0.02,
                )
        else:
            final_video = self.add(
                "final-video", "final_video", "media.concat",
                parameters={
                    "video_steps": clips, "normalize": True,
                    "transition_duration": transition, "final_output": True,
                    "require_audio": require_audio, "require_subtitles": False,
                    "target_duration_seconds": self.spec.target_duration_seconds,
                }, depends_on=clips, cost=0.02,
            )
        self.add(
            "validate-final", "validation", "cuti.continuity.validate",
            action="validate", parameters={"timeline_step": timeline, "video_step": final_video},
            depends_on=[*clips, timeline, final_video],
        )
        topological_steps(self.items)
        return RebuildPlan(
            project_id=self.project_id,
            kind="initial",
            base_project_version_id=self.base_version_id,
            workflow_id=self.workflow.skill_name,
            video_spec=self.spec,
            items=self.items,
            estimated_cost=round(sum(item.estimated_cost for item in self.items), 6),
        )


def _finish_plan(builder: WorkflowPlanBuilder) -> RebuildPlan:
    topological_steps(builder.items)
    return RebuildPlan(
        project_id=builder.project_id,
        kind="initial",
        base_project_version_id=builder.base_version_id,
        workflow_id=builder.workflow.skill_name,
        video_spec=builder.spec,
        items=builder.items,
        estimated_cost=round(sum(item.estimated_cost for item in builder.items), 6),
    )


def _by_id(plan: RebuildPlan) -> dict[str, RebuildPlanItem]:
    return {item.step_id: item for item in plan.items}


def _capabilities(plan: RebuildPlan) -> set[str]:
    return {item.capability for item in plan.items if item.capability}


def _video_clips(plan: RebuildPlan) -> list[RebuildPlanItem]:
    return [item for item in plan.items if item.output_artifact_type == "video_clip"]


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _prompt_covers_interval(value: str, duration: int) -> bool:
    """Recognize the compact time-range notation required by Cuti ad Skills."""
    units = r"(?:s|sec(?:onds?)?|秒)?"
    separator = r"(?:-|–|—|~|～|至|到)"
    ranges = [
        (float(start), float(end))
        for start, end in re.findall(
            rf"(?<!\d)(\d+(?:\.\d+)?)\s*{units}\s*{separator}\s*"
            rf"(\d+(?:\.\d+)?)\s*{units}",
            value,
            flags=re.IGNORECASE,
        )
    ]
    if not ranges:
        return False
    return abs(min(start for start, _end in ranges)) <= 0.01 and abs(
        max(end for _start, end in ranges) - duration
    ) <= 0.01


def _reject_capabilities(plan: RebuildPlan, workflow_id: str, forbidden: set[str]) -> None:
    present = sorted(forbidden & _capabilities(plan))
    if present:
        raise BuildPlanValidationError(
            f"{workflow_id} contains forbidden capabilities: {', '.join(present)}"
        )






def _validate_seedance2_plan(plan: RebuildPlan) -> None:
    _reject_capabilities(plan, plan.workflow_id, {
        "media.tts", "atomic.music.generate", "suno.generate",
        "media.subtitle.compose", "subtitle.compose", "media.subtitle.burn",
    })
    if any(item.output_artifact_type in {"keyframe", "character_reference", "scene_reference"} for item in plan.items):
        raise BuildPlanValidationError("seedance2 must not inject keyframe or setting-image stages")
    clips = _video_clips(plan)
    if not clips:
        raise BuildPlanValidationError("seedance2 must produce at least one video clip")
    for clip in clips:
        if clip.capability not in {
            "atomic.video.generate", "api.provider.generate",
            "api.ark_protocol.generate",
        }:
            raise BuildPlanValidationError(
                "seedance2 video clips must use a declared Seedance provider capability"
            )
        if clip.parameters.get("model") != "doubao-seedance-2-0-260128":
            raise BuildPlanValidationError(
                "seedance2 must use the Seedance 2.0 provider model with the "
                "original Cuti id doubao-seedance-2-0-260128"
            )
        if clip.parameters.get("generate_audio") is not True:
            raise BuildPlanValidationError("seedance2 requires native synchronized audio")
        referenced = {
            *clip.parameters.get("reference_from_steps", []),
            *clip.parameters.get("video_reference_from_steps", []),
            *clip.parameters.get("audio_reference_from_steps", []),
        }
        if referenced and clip.parameters.get("generation_mode") not in {
            "reference_to_video", "i2v",
        }:
            raise BuildPlanValidationError(
                "seedance2 multimodal references require a reference-aware generation mode"
            )
        if clip.skill_ids:
            raise BuildPlanValidationError("seedance2 must not inject legacy Director Skills")
        if not _contains_cjk(str(clip.parameters.get("prompt") or "")):
            raise BuildPlanValidationError("seedance2 provider prompts must be written in Chinese")


def validate_agentic_workflow_plan(
    workflow: WorkflowSpec, plan: RebuildPlan,
) -> None:
    """Apply deterministic invariants after DeepSeek proposes an agentic phase.

    Agentic means the DeepSeek loop may choose the shape of the phase; it does
    not mean it may bypass the selected Workflow's provider and media contract.
    """
    if workflow.mode == "seedance2":
        _validate_seedance2_plan(plan)


def _validate_external_short_drama_plan(plan: RebuildPlan) -> None:
    _reject_capabilities(plan, plan.workflow_id, {
        "media.tts", "atomic.music.generate", "suno.generate",
    })
    if any(item.output_artifact_type == "keyframe" for item in plan.items):
        raise BuildPlanValidationError("short-drama-workflow must skip keyframes")
    if not any(item.output_artifact_type == "scene_reference" for item in plan.items):
        raise BuildPlanValidationError("short-drama-workflow requires location references")
    for clip in _video_clips(plan):
        if float(clip.parameters.get("duration") or 0) != 15:
            raise BuildPlanValidationError("short-drama-workflow segments must be 15 seconds")
        if clip.parameters.get("generation_mode") != "t2v":
            raise BuildPlanValidationError("short-drama-workflow must use reference T2V")
        if clip.execution_group != "short-drama-segments" or not clip.max_parallelism:
            raise BuildPlanValidationError(
                "short-drama-workflow must declare independent parallel segments"
            )
        if "start_image_from_step" in clip.parameters:
            raise BuildPlanValidationError("short-drama-workflow must not tail-chain parallel shots")
        if clip.skill_ids:
            raise BuildPlanValidationError("short-drama-workflow must not inject Director Skills")








def compile_seedance2(workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec) -> RebuildPlan:
    multi_reference = workflow.parameters.get("reference_mode") == "multi_reference"
    b = WorkflowPlanBuilder(workflow, context, spec)
    b.add_sources()
    spec_step = b.add("spec", "video_spec", "runtime.artifact.persist", parameters={
        "title": spec.title, "content": spec.model_dump(mode="json"),
    })
    prompts = b.add("seedance-prompts", "script", "runtime.artifact.persist", parameters={
        "title": f"{spec.title} Seedance prompts",
        "content": [{
            "shotId": shot.id, "prompt": shot.visual_prompt,
            "durationSeconds": shot.duration_seconds, "transition": shot.transition,
        } for shot in spec.shots],
    }, depends_on=[spec_step])
    clips: list[str] = []
    previous_clip = ""
    for index, shot in enumerate(spec.shots):
        logical_ids = shot.reference_asset_ids or spec.source_asset_ids
        image_refs = b.image_refs_for_shot(shot)
        video_refs = [
            b.source_steps[item]
            for item in logical_ids
            if (
                item in b.source_steps
                and item in b.sources
                and b.sources[item].type in {
                    "source_video", "video", "video_clip", "video_reference",
                }
            )
        ]
        audio_refs = [
            b.source_steps[item]
            for item in logical_ids
            if (
                item in b.source_steps
                and item in b.sources
                and b.sources[item].type in {
                    "source_audio", "audio", "audio_bgm", "audio_reference",
                }
            )
        ]
        if len(image_refs) > 9 or len(video_refs) > 3 or len(audio_refs) > 3:
            raise BuildPlanValidationError(
                "seedance2 references exceed the original Cuti limits "
                "(9 images, 3 videos, 3 audios)"
            )
        if len(image_refs) + len(video_refs) + len(audio_refs) > 12:
            raise BuildPlanValidationError(
                "seedance2 accepts at most 12 mixed reference files"
            )
        dependencies = list(dict.fromkeys([
            prompts, *image_refs, *video_refs, *audio_refs,
        ]))
        parameters: dict[str, Any] = {
            "prompt": shot.visual_prompt, "duration": shot.duration_seconds,
            "provider": "wavespeed", "model": "doubao-seedance-2-0-260128",
            "resolution": spec.resolution,
            "aspect_ratio": spec.aspect_ratio, "generate_audio": True,
            "reference_from_steps": image_refs,
            "video_reference_from_steps": video_refs,
            "audio_reference_from_steps": audio_refs,
            "shot_id": shot.id,
            "generation_mode": (
                "reference_to_video"
                if image_refs or video_refs or audio_refs else "t2v"
            ),
        }
        transition = shot.transition.strip().casefold()
        if previous_clip and transition in {
            "continuous", "continuous_shot", "continuation", "seamless",
        }:
            if not multi_reference and (video_refs or audio_refs):
                raise BuildPlanValidationError(
                    "seedance2 WaveSpeed continuation cannot combine a strict decoded "
                    "start frame with video/audio references; assign those references to "
                    "a non-continuation shot"
                )
            previous_tail = b.add(
                f"shot-{spec.shots[index - 1].id}-tail-for-{shot.id}",
                "continuity_frame", "media.extract_frame",
                parameters={"position": "last", "format": "png", "source_video_step": previous_clip},
                depends_on=[previous_clip],
            )
            dependencies.append(previous_tail)
            if multi_reference:
                parameters["reference_from_steps"] = [*image_refs, previous_tail]
                parameters["generation_mode"] = "reference_to_video"
            else:
                parameters.update({"generation_mode": "i2v", "start_image_from_step": previous_tail})
        if multi_reference:
            parameters["reference_mode"] = "multi_reference"
        clip = b.add(
            f"shot-{shot.id}-video", "video_clip", "atomic.video.generate",
            parameters=parameters, depends_on=dependencies, cost=0.65, skills=[],
        )
        clips.append(clip)
        previous_clip = clip
    plan = b.finish(clips, transition=0.0, require_audio=True)
    _validate_seedance2_plan(plan)
    return plan


def compile_short_drama_workflow(
    workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec,
) -> RebuildPlan:
    """External Cuti short drama: exact 15s units, shared refs, parallel T2V."""
    if any(abs(shot.duration_seconds - 15.0) > 0.01 for shot in spec.shots):
        raise BuildPlanValidationError(
            "short-drama-workflow requires complete 15-second Seedance segments"
        )
    b = WorkflowPlanBuilder(workflow, context, spec)
    b.add_sources()
    spec_step = b.add("spec", "video_spec", "runtime.artifact.persist", parameters={
        "title": spec.title, "content": spec.model_dump(mode="json"),
    })
    blueprint = b.add("production-blueprint", "storyboard", "runtime.artifact.persist", parameters={
        "title": f"{spec.title} production blueprint",
        "content": {
            "segments": [shot.model_dump(mode="json") for shot in spec.shots],
            "executionMode": "parallel_multi_reference_t2v",
            "segmentDurationSeconds": 15,
            "nativeDialogue": True,
        },
    }, depends_on=[spec_step])
    characters = b.add("characters", "characters", "runtime.artifact.persist", parameters={
        "title": "Recurring cast", "content": [item.model_dump(mode="json") for item in spec.characters],
    }, depends_on=[blueprint])
    scenes = b.add("scenes", "scenes", "runtime.artifact.persist", parameters={
        "title": "Recurring locations", "content": spec.workflow_parameters.get("scenes", []),
    }, depends_on=[blueprint])
    refs_by_character = b.character_references(characters, skills=[])
    scene_refs = b.scene_references(scenes)
    clips: list[str] = []
    for shot in spec.shots:
        refs = [refs_by_character[item] for item in shot.character_ids if item in refs_by_character]
        refs = list(dict.fromkeys([*refs, *scene_refs, *b.image_refs_for_shot(shot)]))
        selected_model = spec.providers.video or "seedance-2.5"
        if selected_model == "seedance-2.0":
            selected_model = "seedance-2.5"
        clips.append(b.add(
            f"shot-{shot.id}-video", "video_clip", "atomic.video.generate",
            parameters={
                "prompt": shot.visual_prompt, "duration": shot.duration_seconds,
                "duration_seconds": shot.duration_seconds, "provider": "wavespeed",
                "model": selected_model, "resolution": spec.resolution,
                "aspect_ratio": spec.aspect_ratio, "generate_audio": True,
                "generation_mode": "t2v", "reference_from_steps": refs,
                "character_reference_from_steps": [
                    refs_by_character[item] for item in shot.character_ids if item in refs_by_character
                ],
                "scene_reference_from_steps": scene_refs, "native_dialogue": True,
            },
            depends_on=[blueprint, *refs], cost=0.65, skills=[],
            execution_group="short-drama-segments",
            max_parallelism=max(1, len(spec.shots)),
        ))
    if not spec.audio.subtitles:
        plan = b.finish(clips, transition=0.0, require_audio=True)
        _validate_external_short_drama_plan(plan)
        return plan
    timeline = b.add(
        "timeline", "timeline", "media.timeline.compose",
        parameters={"shots": [s.model_dump(mode="json") for s in spec.shots], "video_steps": clips},
        depends_on=clips,
    )
    assembled = b.add(
        "assembled-video", "video_assembled", "media.concat",
        parameters={"video_steps": clips, "normalize": True, "transition_duration": 0.0},
        depends_on=clips, cost=0.02,
    )
    transcription = b.add(
        "transcription", "transcription", "media.transcribe",
        parameters={"video_step": assembled, "language": spec.language}, depends_on=[assembled],
    )
    subtitles = b.add(
        "subtitles", "subtitle", "media.subtitle.compose",
        parameters={"transcription_step": transcription, "format": "srt"}, depends_on=[transcription],
    )
    final = b.add(
        "final-video", "final_video", "media.subtitle_burn",
        parameters={
            "video_step": assembled, "subtitle_step": subtitles, "final_output": True,
            "require_audio": True, "require_subtitles": True,
            "target_duration_seconds": spec.target_duration_seconds,
        }, depends_on=[assembled, subtitles], cost=0.02,
    )
    b.add(
        "validate-final", "validation", "cuti.continuity.validate", action="validate",
        parameters={"timeline_step": timeline, "video_step": final},
        depends_on=[*clips, timeline, final],
    )
    plan = _finish_plan(b)
    _validate_external_short_drama_plan(plan)
    return plan




def compile_cuti_product(
    workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec,
) -> RebuildPlan:
    """Original narrated Cuti product commercial with one 360 identity sheet."""
    if any(abs(shot.duration_seconds - 15.0) > 0.01 for shot in spec.shots):
        raise BuildPlanValidationError(
            "cuti-product-workflow requires complete 15-second Seedance segments"
        )
    b = WorkflowPlanBuilder(workflow, context, spec)
    b.add_sources()
    product_refs = _product_image_source_steps(b)
    wp = spec.workflow_parameters or {}
    spec_step = b.add("spec", "video_spec", "runtime.artifact.persist", parameters={
        "title": spec.title, "content": spec.model_dump(mode="json"),
    })
    product_truth = b.add(
        "product-analysis", "product_analysis", "atomic.text.generate",
        parameters={
            "objective": "Extract verifiable product truth from the supplied product images",
            "instruction": (
                "Record only visible identity, geometry, materials, controls, branding, packaging, "
                "and credible functions. Mark unknown claims unknown; invent no specifications."
            ),
            "reference_from_steps": product_refs,
        }, depends_on=[spec_step, *product_refs],
    )
    strategy = b.add(
        "commercial-strategy", "script", "runtime.artifact.persist",
        parameters={
            "title": f"{spec.title} commercial strategy",
            "content": {
                "strategy": wp.get("commercial_strategy", {}),
                "segments": [shot.model_dump(mode="json") for shot in spec.shots],
                "subordinateSkills": [
                    "product-feature-demo-script",
                    "product-component-exploded-view",
                    "product-voiceover-narration",
                ],
                "skillExecutionOrder": [
                    "product-feature-demo-script",
                    "product-component-exploded-view",
                    "product-voiceover-narration",
                ],
            },
        }, depends_on=[product_truth],
    )
    setting = b.add(
        "product-360-reference", "image", "atomic.image.generate",
        parameters={
            "prompt": str(wp.get("product_360_prompt") or (
                "Create one clean 360-degree product identity reference sheet from the uploaded "
                "product truth. Preserve exact silhouette, proportions, color, material, controls, "
                "openings, components, packaging, and real brand placement. Show coordinated front, "
                "rear, left/right side, front/rear three-quarter views, and one restrained detail "
                "inset for the primary selling point in one clean 16:9 sheet. Neutral background; "
                "no people, usage scene, invented accessories, captions, or storyboard frames."
            )),
            "model": "gpt-image-2", "aspect_ratio": "16:9",
            "artifact_role": "product_360_reference",
            "artifact_title": (
                "360度产品设定图" if spec.language.casefold().startswith("zh")
                else "360-degree product setting image"
            ),
            "reference_from_steps": product_refs,
        }, depends_on=[strategy, *product_refs], cost=0.08,
    )
    voice_profile = wp.get("voice_profile") or {
        "language": spec.language,
        "voice": spec.audio.narration_voice,
        "delivery": "native synchronized commercial voiceover",
    }
    voice_profile_hash = hashlib.sha256(json.dumps(
        voice_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    clips: list[str] = []
    for shot in spec.shots:
        refs = list(dict.fromkeys([*product_refs, setting, *_shot_image_source_steps(b, shot)]))
        narration = shot.narration.strip()
        beat: dict[str, Any] = {
            "beat_id": f"{shot.id}:beat:1",
            "start_seconds": 0,
            "end_seconds": 15,
            "visual": {
                "action": shot.beat,
                "prompt": shot.visual_prompt,
            },
            "selling_point_status": str(wp.get("selling_point_status") or "conceptual"),
            "narration": (
                {
                    "text": narration,
                    "start_seconds": 0.5,
                    "end_seconds": 14.5,
                }
                if narration else None
            ),
        }
        requested_narration_mode = str(wp.get("narration_mode") or "").strip().casefold()
        if not narration and requested_narration_mode != "music_only":
            raise BuildPlanValidationError(
                "cuti-product-workflow requires native narration, or an explicit "
                "workflow_parameters.narration_mode=music_only decision"
            )
        workflow_contract = {
            "segment_script": {
                "segment_id": shot.id,
                "duration_seconds": 15,
                "beats": [beat],
            },
            "narration_mode": "native_voiceover" if narration else "music_only",
            "voice_profile": voice_profile,
            "voice_profile_hash": voice_profile_hash,
        }
        clip = b.add(
            f"shot-{shot.id}-video", "video_clip", "api.provider.generate",
            parameters={
                "prompt": shot.visual_prompt, "duration": 15,
                "provider": "wavespeed", "model": "seedance-2.5",
                "resolution": spec.resolution, "aspect_ratio": spec.aspect_ratio,
                "generate_audio": True, "generation_mode": "t2v",
                "reference_from_steps": refs,
                "product_identity_reference_steps": [*product_refs, setting],
                "artifact_role": "product_commercial_segment",
                "_workflow_contract": workflow_contract,
                "native_voiceover": bool(narration),
            }, depends_on=[strategy, setting, *refs], cost=0.65,
            skills=[],
            execution_group="cuti-product-segments",
            max_parallelism=2,
        )
        clips.append(clip)
    plan = b.finish(clips, transition=0.0, require_audio=True)
    _validate_cuti_product_plan(plan, product_refs, setting)
    return plan


def _product_image_source_steps(b: WorkflowPlanBuilder) -> list[str]:
    """Return only uploaded image artifacts that can be product truth references."""
    refs = [
        b.source_steps[logical_id]
        for logical_id in b.spec.source_asset_ids
        if (
            logical_id in b.source_steps
            and logical_id in b.sources
            and b.sources[logical_id].type in {
                "source_image", "image", "product_reference", "character_reference",
            }
        )
    ]
    if not refs:
        raise BuildPlanValidationError(
            f"{b.workflow.skill_name} requires an uploaded product image"
        )
    return refs


def _source_audio_step(b: WorkflowPlanBuilder) -> str:
    for logical_id in b.spec.source_asset_ids:
        artifact = b.sources.get(logical_id)
        if artifact is not None and artifact.type in {"source_audio", "audio", "audio_bgm"}:
            return b.source_steps[logical_id]
    return ""


def _shot_image_source_steps(b: WorkflowPlanBuilder, shot) -> list[str]:
    logical_ids = shot.reference_asset_ids or b.spec.source_asset_ids
    return [
        b.source_steps[logical_id]
        for logical_id in logical_ids
        if (
            logical_id in b.source_steps
            and logical_id in b.sources
            and b.sources[logical_id].type in {
                "source_image", "image", "product_reference", "character_reference",
            }
        )
    ]


def _segment_proof(spec: VideoSpec, index: int, shot_id: str) -> str:
    wp = spec.workflow_parameters or {}
    proofs = wp.get("segment_proofs")
    if isinstance(proofs, dict):
        value = proofs.get(shot_id) or proofs.get(str(index + 1))
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(proofs, list) and index < len(proofs):
        value = proofs[index]
        if isinstance(value, str) and value.strip():
            return value.strip()
    if len(spec.shots) == 1:
        value = wp.get("segment_proof")
        if isinstance(value, str) and value.strip():
            return value.strip()
    # The original Cuti workflow requires the exact proof in the compact
    # Seedance prompt header.  Accept that canonical representation as input
    # and copy it into the executable task contract instead of rejecting a
    # semantically complete plan merely because the LLM omitted the duplicate
    # workflow_parameters field.
    shot = spec.shots[index]
    match = re.search(r"(?m)^本片段卖点证明[：:]\s*(.+?)\s*$", shot.visual_prompt)
    if match and match.group(1).strip():
        return match.group(1).strip()
    raise BuildPlanValidationError(
        "cuti-scenario-product-workflow requires workflow_parameters.segment_proofs "
        f"for shot {shot_id}"
    )


def _scenario_provider_prompt(
    *, visual_prompt: str, primary_selling_point: str, segment_proof: str,
) -> str:
    # DeepSeek may already have copied the workflow's canonical four-line
    # execution header into Shot.visual_prompt. A semantic repair can receive a
    # prompt produced by an older plan that already contains the header twice.
    # The Runtime owns this header because it must exactly match the structured
    # task contract, so remove *all* leading copies before writing one canonical
    # block. Accept both Chinese and ASCII colons, but only strip a complete
    # three-line contract so ordinary prompt prose is never discarded.
    lines = visual_prompt.strip().splitlines()
    required_header_patterns = (
        re.compile(r"^\s*任务类型\s*[：:]"),
        re.compile(r"^\s*核心产品卖点\s*[：:]"),
        re.compile(r"^\s*本片段卖点证明\s*[：:]"),
    )
    creative_requirement = re.compile(r"^\s*镜头创作要求\s*[：:]")
    while True:
        while lines and not lines[0].strip():
            lines.pop(0)
        if len(lines) < len(required_header_patterns) or not all(
            pattern.match(lines[index])
            for index, pattern in enumerate(required_header_patterns)
        ):
            break
        del lines[:len(required_header_patterns)]
        if lines and creative_requirement.match(lines[0]):
            del lines[0]
    visual_prompt = "\n".join(lines).lstrip()
    return (
        "任务类型：产品宣传片\n"
        f"核心产品卖点：{primary_selling_point}\n"
        f"本片段卖点证明：{segment_proof}\n"
        "镜头创作要求：剧情、表演、声音和摄影必须共同强化上述卖点；"
        "不得把产品降级为无关道具或把片段拍成与产品无关的普通剧情。\n"
        f"{visual_prompt.strip()}"
    )


def _scenario_character_setting_prompt(spec: VideoSpec) -> str:
    details = "; ".join(
        " | ".join(value for value in (
            character.name,
            character.appearance,
            character.clothing,
            character.personality,
        ) if value)
        for character in spec.characters
    ).strip()
    return (
        "Create ONLY one clean recurring-character identity reference sheet, not a storyboard "
        "and not a combined production reference board. "
        f"Characters from the approved script: {details or 'use the approved character definitions'}. "
        "Show consistent front or three-quarter views and useful full-body proportions on a neutral, "
        "uncluttered background. Do not include the advertised product, environment panels, readable "
        "text, labels, captions, logos, watermarks, storyboard borders, or shot frames."
    )


def _scenario_character_reference_prompt(spec: VideoSpec) -> str:
    workflow_parameters = spec.workflow_parameters or {}
    custom = str(
        workflow_parameters.get("character_setting_prompt")
        or workflow_parameters.get("character_setting_reference_prompt")
        or ""
    ).strip()
    base = _scenario_character_setting_prompt(spec)
    return f"{base} Additional workflow constraints: {custom}" if custom else base


def _scenario_product_reference_prompt(spec: VideoSpec) -> str:
    workflow_parameters = spec.workflow_parameters or {}
    custom = str(
        workflow_parameters.get("product_setting_prompt")
        or workflow_parameters.get("product_setting_reference_prompt")
        or ""
    ).strip()
    base = (
        "Create a clean product identity sheet from the uploaded product truth reference, with "
        "front, rear, side, and three-quarter views where supported. Preserve exact shape, "
        "proportions, color, material, controls, openings, components, and real brand placement. "
        "Neutral background; no invented accessories, labels, captions, people, or usage scene."
    )
    return f"{base} Additional workflow constraints: {custom}" if custom else base


def _scenario_scene_setting_prompt(spec: VideoSpec) -> str:
    workflow_parameters = spec.workflow_parameters or {}
    custom = str(
        workflow_parameters.get("scene_setting_prompt")
        or workflow_parameters.get("scene_setting_reference_prompt")
        or ""
    ).strip()
    scenario = workflow_parameters.get("scenario")
    setting = ""
    if isinstance(scenario, dict):
        setting = str(scenario.get("setting") or "").strip()
    scenes = workflow_parameters.get("scenes")
    if not setting and isinstance(scenes, list) and scenes:
        first = scenes[0]
        if isinstance(first, dict):
            setting = str(
                first.get("description") or first.get("setting") or first.get("name") or ""
            ).strip()
        else:
            setting = str(first).strip()
    continuity = workflow_parameters.get("continuity_record")
    if not setting and isinstance(continuity, dict):
        setting = str(continuity.get("location") or "").strip()

    # A free-form scene prompt is a legacy escape hatch.  Never prefer it over
    # the structured location because planners sometimes copied the whole
    # character/product bible into this field.  If it is the only location
    # input, reject known contamination rather than issuing contradictory
    # positive and negative instructions to the image model.
    if not setting and custom:
        contamination_candidates = [
            *(value for character in spec.characters for value in (
                character.name, character.appearance, character.clothing,
            )),
            str(workflow_parameters.get("product_name") or ""),
            str(workflow_parameters.get("primary_selling_point") or ""),
        ]
        folded = custom.casefold()
        contaminant = next((
            value.strip() for value in contamination_candidates
            if len(value.strip()) >= 3 and value.strip().casefold() in folded
        ), "")
        if contaminant:
            raise BuildPlanValidationError(
                "scene_setting_prompt must describe the empty environment only; "
                f"it contains character or product material: {contaminant!r}"
            )
        setting = custom

    subject = (
        "Derive the recurring location from the approved script"
        + (f": {setting}" if setting else "")
        + ". Preserve its spatial layout, architecture, surfaces, palette, time of day, "
        "lighting direction, weather, and stable environmental props."
    )
    return (
        "Create exactly one unoccupied environment-only setting reference. "
        f"{subject} Use a single coherent wide or three-quarter architectural establishing view. "
        "Keep foreground and midground clear and unused so the spatial layout remains easy to reuse. "
        "One frame only, without signage, readable text, captions, watermarks, panels, contact-sheet "
        "layout, or decorative borders."
    )


def compile_scenario_product(
    workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec,
) -> RebuildPlan:
    """Compile Cuti's story-driven, multi-reference Seedance product workflow."""
    if not spec.source_asset_ids:
        raise BuildPlanValidationError(
            "cuti-scenario-product-workflow requires an uploaded product image"
        )
    if any(abs(shot.duration_seconds - 15.0) > 0.01 for shot in spec.shots):
        raise BuildPlanValidationError(
            "cuti-scenario-product-workflow requires complete 15-second Seedance segments"
        )
    wp = spec.workflow_parameters or {}
    primary = str(wp.get("primary_selling_point") or "").strip()
    if not primary:
        raise BuildPlanValidationError(
            "cuti-scenario-product-workflow requires workflow_parameters.primary_selling_point"
        )

    b = WorkflowPlanBuilder(workflow, context, spec)
    b.add_sources()
    product_sources = _product_image_source_steps(b)
    spec_step = b.add(
        "spec", "video_spec", "runtime.artifact.persist",
        parameters={"title": spec.title, "content": spec.model_dump(mode="json")},
    )
    product_analysis = b.add(
        "product-analysis", "product_analysis", "atomic.text.generate",
        parameters={
            "objective": "Develop credible audience benefits and visible proof from the product source",
            "instruction": (
                "Generate candidate selling points, choose one dramatic proposition, and explain "
                "what visible cause-and-effect action can prove it. Do not invent specifications, "
                "measurements, prices, certifications, awards, or competitor comparisons."
            ),
            "reference_from_steps": product_sources,
        },
        depends_on=[spec_step, *product_sources],
    )
    scenario_script = b.add(
        "scenario-script", "script", "runtime.artifact.persist",
        parameters={
            "title": f"{spec.title} scenario and segment plan",
            "content": {
                "sellingPoints": wp.get("selling_points", []),
                "primarySellingPoint": primary,
                "dramaticProposition": wp.get("dramatic_proposition", ""),
                "storyStructureChoice": wp.get("story_structure_choice", {}),
                "scenario": wp.get("scenario", ""),
                "segments": [shot.model_dump(mode="json") for shot in spec.shots],
            },
        },
        depends_on=[spec_step, product_analysis],
    )
    characters = b.add(
        "characters", "characters", "runtime.artifact.persist",
        parameters={
            "title": "Scenario characters",
            "content": [item.model_dump(mode="json") for item in spec.characters],
        },
        depends_on=[scenario_script],
    )
    storyboard = b.add(
        "storyboard", "storyboard", "runtime.artifact.persist",
        parameters={
            "title": "15-second segment plan",
            "content": [shot.model_dump(mode="json") for shot in spec.shots],
        },
        depends_on=[scenario_script, characters],
    )

    character_ref = b.add(
        "character-setting-reference", "image", "atomic.image.generate",
        parameters={
            "title": "Character setting reference",
            "prompt": _scenario_character_reference_prompt(spec),
            "model": "gpt-image-2",
            "aspect_ratio": spec.aspect_ratio,
            "artifact_role": "character_setting_reference",
        },
        depends_on=[scenario_script],
        cost=0.08,
        execution_group="scenario-setting-references",
        max_parallelism=3,
    )
    scene_ref = b.add(
        "scene-setting-reference", "image", "atomic.image.generate",
        parameters={
            "title": "Scene setting reference",
            "prompt": _scenario_scene_setting_prompt(spec),
            "model": "gpt-image-2",
            "aspect_ratio": spec.aspect_ratio,
            "artifact_role": "scene_setting_reference",
        },
        depends_on=[scenario_script],
        cost=0.08,
        execution_group="scenario-setting-references",
        max_parallelism=3,
    )
    product_ref = b.add(
        "product-setting-reference", "image", "atomic.image.generate",
        parameters={
            "title": "Product setting reference",
            "prompt": _scenario_product_reference_prompt(spec),
            "model": "gpt-image-2",
            "aspect_ratio": spec.aspect_ratio,
            "artifact_role": "product_setting_reference",
            "reference_from_steps": product_sources,
        },
        depends_on=[scenario_script, *product_sources],
        cost=0.08,
        execution_group="scenario-setting-references",
        max_parallelism=3,
    )
    setting_refs = [character_ref, scene_ref, product_ref]
    setting_validation = b.add(
        "validate-setting-references", "setting_reference_validation",
        "cuti.continuity.validate", action="validate",
        parameters={
            "validation_kind": "scenario_setting_reference_isolation",
            "required": True,
        },
        depends_on=setting_refs,
    )

    clips: list[str] = []
    previous_clip = ""
    for index, shot in enumerate(spec.shots):
        proof = _segment_proof(spec, index, shot.id)
        prompt = _scenario_provider_prompt(
            visual_prompt=shot.visual_prompt,
            primary_selling_point=primary,
            segment_proof=proof,
        )
        refs = list(dict.fromkeys([
            *product_sources, *setting_refs, *_shot_image_source_steps(b, shot),
        ]))
        dependencies = [storyboard, *refs, setting_validation]
        parameters: dict[str, Any] = {
            "prompt": prompt,
            "duration": 15,
            "model": spec.providers.video,
            "resolution": spec.resolution,
            "aspect_ratio": spec.aspect_ratio,
            "generate_audio": True,
            "generation_mode": "t2v",
            "reference_from_steps": refs,
            "product_identity_reference_steps": [*product_sources, product_ref],
            "ad_format": "product_commercial",
            "primary_selling_point": primary,
            "segment_proof": proof,
            "native_dialogue": True,
            "reference_purposes": {
                **{step: "product identity" for step in product_sources},
                character_ref: "character identity",
                scene_ref: "setting",
                product_ref: "product identity",
            },
        }
        transition = shot.transition.strip().casefold()
        if previous_clip and transition in {
            "continuous", "continuous_shot", "continuation", "seamless",
        }:
            previous_tail = b.add(
                f"shot-{spec.shots[index - 1].id}-tail-for-{shot.id}",
                "continuity_frame", "media.extract_frame",
                parameters={
                    "position": "last", "format": "png",
                    "source_video_step": previous_clip,
                },
                depends_on=[previous_clip],
            )
            dependencies.append(previous_tail)
            parameters["start_image_from_step"] = previous_tail
            parameters["generation_mode"] = "i2v"
        clip = b.add(
            f"shot-{shot.id}-video", "video_clip", "api.provider.generate",
            parameters=parameters,
            depends_on=dependencies,
            cost=0.65,
            skills=list(workflow.skill_dependencies),
            execution_group=(
                None if parameters["generation_mode"] == "i2v"
                else "scenario-product-segments"
            ),
            max_parallelism=(
                None if parameters["generation_mode"] == "i2v" else 2
            ),
        )
        clips.append(clip)
        previous_clip = clip
    plan = b.finish(clips, transition=0.0, require_audio=True)
    _validate_scenario_product_plan(plan, product_sources, setting_refs, primary)
    return plan


def _validate_cuti_product_plan(
    plan: RebuildPlan, product_refs: list[str], product_setting: str,
) -> None:
    by_id = _by_id(plan)
    setting = by_id.get(product_setting)
    if setting is None or setting.capability != "atomic.image.generate":
        raise BuildPlanValidationError("cuti-product-workflow requires its 360 product reference")
    if setting.parameters.get("model") != "gpt-image-2":
        raise BuildPlanValidationError("cuti-product 360 reference must use gpt-image-2")
    if setting.parameters.get("artifact_role") != "product_360_reference":
        raise BuildPlanValidationError("cuti-product 360 reference lost its artifact role")
    if setting.parameters.get("aspect_ratio") != "16:9":
        raise BuildPlanValidationError("cuti-product 360 reference must be a 16:9 setting sheet")
    if not setting.parameters.get("artifact_title"):
        raise BuildPlanValidationError("cuti-product 360 reference must have a user-visible title")
    _reject_capabilities(plan, plan.workflow_id, {
        "media.tts", "atomic.music.generate", "suno.generate",
        "media.subtitle.compose", "subtitle.compose", "media.subtitle.burn",
    })
    voice_profile_hashes: set[str] = set()
    for clip in _video_clips(plan):
        if clip.capability not in {"api.provider.generate", "api.ark_protocol.generate"}:
            raise BuildPlanValidationError("cuti-product segments must use a provider capability")
        if float(clip.parameters.get("duration") or 0) != 15:
            raise BuildPlanValidationError("cuti-product segments must be exactly 15 seconds")
        if clip.parameters.get("model") != "seedance-2.5":
            raise BuildPlanValidationError("cuti-product segments must use Seedance 2.5")
        if clip.parameters.get("generation_mode") != "t2v":
            raise BuildPlanValidationError("cuti-product must use references, not forced first-frame I2V")
        if "start_image_from_step" in clip.parameters:
            raise BuildPlanValidationError("cuti-product must not force a generated first frame")
        if clip.parameters.get("generate_audio") is not True:
            raise BuildPlanValidationError("cuti-product requires native synchronized voiceover")
        refs = set(clip.parameters.get("product_identity_reference_steps") or [])
        if not set([*product_refs, product_setting]) <= refs:
            raise BuildPlanValidationError("cuti-product segment dropped product identity references")
        contract = clip.parameters.get("_workflow_contract") or {}
        segment = contract.get("segment_script") or {}
        beats = segment.get("beats") or []
        if segment.get("duration_seconds") != 15 or not beats:
            raise BuildPlanValidationError("cuti-product segment lost its timed 15-second script")
        if beats[0].get("start_seconds") != 0 or beats[-1].get("end_seconds") != 15:
            raise BuildPlanValidationError("cuti-product visual beats must cover 0-15 seconds")
        previous_end = 0.0
        for beat in beats:
            start = float(beat.get("start_seconds", -1))
            end = float(beat.get("end_seconds", -1))
            if abs(start - previous_end) > 0.01 or end <= start or end > 15.0:
                raise BuildPlanValidationError(
                    "cuti-product visual beats must continuously cover 0-15 seconds"
                )
            narration = beat.get("narration")
            if narration:
                narration_start = float(narration.get("start_seconds", -1))
                narration_end = float(narration.get("end_seconds", -1))
                if (
                    narration_start < start
                    or narration_end > end
                    or narration_end <= narration_start
                    or beat.get("selling_point_status") == "unknown"
                ):
                    raise BuildPlanValidationError(
                        "cuti-product narration must stay inside a verified or conceptual visual beat"
                    )
            previous_end = end
        narration_mode = contract.get("narration_mode")
        if narration_mode not in {"native_voiceover", "music_only"}:
            raise BuildPlanValidationError("cuti-product segment lost its narration mode")
        profile = contract.get("voice_profile")
        expected_hash = hashlib.sha256(json.dumps(
            profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if contract.get("voice_profile_hash") != expected_hash:
            raise BuildPlanValidationError("cuti-product voice profile hash is invalid")
        voice_profile_hashes.add(str(contract.get("voice_profile_hash") or ""))
        prompt = str(clip.parameters.get("prompt") or "")
        if not _contains_cjk(prompt) or not _prompt_covers_interval(prompt, 15):
            raise BuildPlanValidationError(
                "cuti-product requires one Chinese prompt covering the complete 0-15s timeline"
            )
        if "video-director" in clip.skill_ids:
            raise BuildPlanValidationError("cuti-product must not inject the old video-director")
        if (
            clip.execution_group != "cuti-product-segments"
            or clip.max_parallelism != 2
        ):
            raise BuildPlanValidationError(
                "cuti-product segments must declare at-most-two concurrency"
            )
    if len(voice_profile_hashes) != 1:
        raise BuildPlanValidationError(
            "cuti-product must preserve one voice profile across all segments"
        )


def _validate_scenario_product_plan(
    plan: RebuildPlan,
    product_sources: list[str],
    setting_refs: list[str],
    primary_selling_point: str,
) -> None:
    by_id = {item.step_id: item for item in plan.items}
    required_roles = {
        "character-setting-reference": "character_setting_reference",
        "scene-setting-reference": "scene_setting_reference",
        "product-setting-reference": "product_setting_reference",
    }
    for step_id, role in required_roles.items():
        step = by_id.get(step_id)
        if step is None or step.capability != "atomic.image.generate":
            raise BuildPlanValidationError(f"cuti-scenario-product-workflow is missing {role}")
        if str(step.parameters.get("model") or "").replace("_", "-").lower() != "gpt-image-2":
            raise BuildPlanValidationError(f"{role} must use gpt-image-2")
        if step.parameters.get("artifact_role") != role:
            raise BuildPlanValidationError(f"{step_id} has an invalid artifact_role")
        if "scenario-script" not in step.depends_on:
            raise BuildPlanValidationError(f"{role} must depend on the completed script")
        if (
            step.execution_group != "scenario-setting-references"
            or step.max_parallelism != 3
        ):
            raise BuildPlanValidationError(
                "scenario setting references must be declared as one parallel group"
            )

    reference_validation = by_id.get("validate-setting-references")
    if (
        reference_validation is None
        or reference_validation.action != "validate"
        or reference_validation.capability != "cuti.continuity.validate"
        or set(reference_validation.depends_on) != set(setting_refs)
    ):
        raise BuildPlanValidationError(
            "scenario setting references must pass isolation validation before video generation"
        )

    clips = [item for item in plan.items if item.output_artifact_type == "video_clip"]
    forbidden = {
        "media.tts", "atomic.music.generate", "suno.generate",
        "media.subtitle.compose", "media.subtitle.burn",
    }
    if forbidden & {item.capability for item in plan.items}:
        raise BuildPlanValidationError(
            "cuti-scenario-product-workflow must use Seedance native synchronized audio"
        )
    for clip in clips:
        if clip.capability not in {"api.provider.generate", "api.ark_protocol.generate"}:
            raise BuildPlanValidationError("scenario product segments must use a provider capability")
        if float(clip.parameters.get("duration") or 0) != 15:
            raise BuildPlanValidationError("scenario product segments must be 15 seconds")
        if clip.parameters.get("generate_audio") is not True:
            raise BuildPlanValidationError("scenario product segments require native audio")
        refs = set(clip.parameters.get("reference_from_steps") or [])
        missing = set([*product_sources, *setting_refs]) - refs
        if missing:
            raise BuildPlanValidationError(
                "scenario product segment is missing durable references: "
                + ", ".join(sorted(missing))
            )
        if "validate-setting-references" not in clip.depends_on:
            raise BuildPlanValidationError(
                "scenario product segment starts before setting-reference validation"
            )
        prompt = str(clip.parameters.get("prompt") or "")
        proof = str(clip.parameters.get("segment_proof") or "").strip()
        if clip.parameters.get("ad_format") != "product_commercial":
            raise BuildPlanValidationError("scenario product segment lost ad_format")
        if clip.parameters.get("primary_selling_point") != primary_selling_point:
            raise BuildPlanValidationError("scenario product segment changed the selling point")
        if (
            not proof
            or primary_selling_point.casefold() not in prompt.casefold()
            or proof.casefold() not in prompt.casefold()
        ):
            raise BuildPlanValidationError(
                "scenario product provider prompt lost its selling point or segment proof"
            )
        if not any(term in prompt.casefold() for term in (
            "产品宣传片", "产品广告", "product commercial", "product advertisement",
        )):
            raise BuildPlanValidationError(
                "scenario product provider prompt must identify itself as a product advertisement"
            )
        if not _contains_cjk(prompt) or not _prompt_covers_interval(prompt, 15):
            raise BuildPlanValidationError(
                "scenario product requires one Chinese prompt covering the complete 0-15s timeline"
            )
        if clip.parameters.get("generation_mode") == "i2v":
            if clip.execution_group is not None:
                raise BuildPlanValidationError(
                    "tail-chained scenario segments must remain serial"
                )
        elif (
            clip.execution_group != "scenario-product-segments"
            or clip.max_parallelism != 2
        ):
            raise BuildPlanValidationError(
                "independent scenario segments must declare at-most-two concurrency"
            )


def compile_mv_compat(workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec) -> RebuildPlan:
    """Dest $mv boxes. Spec fields on the step; no second director."""
    b = WorkflowPlanBuilder(workflow, context, spec)
    b.add_sources()
    spec_step = b.add("spec", "video_spec", "runtime.artifact.persist", parameters={
        "title": spec.title, "content": spec.model_dump(mode="json"),
    })
    identity_images = [
        b.source_steps[item] for item in spec.source_asset_ids
        if item in b.sources and b.sources[item].type in {
            "source_image", "image", "character_reference",
        }
    ]
    wp = spec.workflow_parameters or {}
    uploaded = [
        b.source_steps[item] for item in spec.source_asset_ids
        if b.sources[item].type in {"source_audio", "audio", "audio_bgm"}
    ]
    if uploaded:
        music = uploaded[0]
    elif spec.audio.bgm_prompt:
        music_parameters: dict[str, Any] = {"prompt": spec.audio.bgm_prompt}
        for key in (
            "title", "tags", "custom_mode", "make_instrumental", "instrumental",
            "vocal_gender", "mv", "lyrics", "duration",
        ):
            if key in wp:
                music_parameters[key] = wp[key]
        music_parameters.setdefault("title", spec.title)
        music = b.add(
            "music", "audio_bgm", "suno.generate",
            parameters=music_parameters, depends_on=[spec_step], cost=0.10,
        )
    else:
        raise BuildPlanValidationError(
            "music video workflow requires uploaded audio or audio.bgm_prompt"
        )
    analysis = b.add(
        "music-analysis", "audiomap", "media.audio_analyze",
        parameters={"audio_step": music, "target_duration_sec": spec.target_duration_seconds},
        depends_on=[music],
    )
    cut_parameters: dict[str, Any] = {"audio_step": music, "analysis_step": analysis}
    for key in ("start_sec", "segments"):
        if key in wp:
            cut_parameters[key] = wp[key]
    cut_parameters.setdefault("duration", spec.target_duration_seconds)
    # Cuti's $mv contract gives H3 one matching <=15s audio reference per
    # visual segment.  When the planner did not provide the cut table, derive
    # it deterministically from the already-approved shot durations instead
    # of handing every shot the full master window.
    if "segments" not in cut_parameters and len(spec.shots) > 1:
        cursor = 0.0
        cut_parameters["segments"] = []
        for shot in spec.shots:
            cut_parameters["segments"].append({
                "start_sec": cursor,
                "duration": shot.duration_seconds,
            })
            cursor += shot.duration_seconds
    cut = b.add(
        "music-cut", "audio_cut", "media.audio_cut",
        parameters=cut_parameters, depends_on=[music, analysis],
    )
    # Original Cuti $mv is music-first.  It has no generic script/storyboard
    # production chain: once the real music window is known, it locks the cast
    # and persists the music-timed shot plan prepared by DeepSeek.
    characters = b.add(
        "characters", "characters", "runtime.artifact.persist",
        parameters={
            "title": "MV cast lock",
            "content": [item.model_dump(mode="json") for item in spec.characters],
        },
        depends_on=[spec_step, analysis, cut],
    )
    shot_plan = b.add(
        "mv-shot-plan", "shot_plan", "runtime.artifact.persist",
        parameters={
            "title": f"{spec.title} music-timed shot plan",
            "content": [item.model_dump(mode="json") for item in spec.shots],
        },
        depends_on=[characters, analysis, cut],
    )
    # Original Cuti $mv has a distinct "look-lock" stage even when the user supplied
    # an identity image: the upload anchors identity and the generated sheet
    # locks clothing/look for every later shot.
    refs_by_character = (
        b.character_references(
            characters,
            skills=[],
            reference_from_steps=identity_images,
        )
        if spec.characters else {}
    )
    raw_model = str(spec.providers.video or "minimax-h3").strip().casefold()
    if raw_model in {"h3", "minimax_h3", "minimax-h3-r2v"} or (
        "minimax" in raw_model and "h3" in raw_model
    ):
        model = "minimax-h3"
        model_family = "h3"
    elif any(token in raw_model for token in (
        "seedance-2", "seedance_2", "seedance2", "doubao-seedance-2",
    )):
        model = "doubao-seedance-2-0"
        model_family = "seedance2"
    else:
        raise BuildPlanValidationError(
            "mv supports only minimax-h3 or doubao-seedance-2-0"
        )
    clips: list[str] = []
    segments = cut_parameters.get("segments")
    for index, shot in enumerate(spec.shots):
        if shot.character_ids:
            look = [
                refs_by_character[item]
                for item in shot.character_ids if item in refs_by_character
            ]
        else:
            look = list(refs_by_character.values())
        refs = list(dict.fromkeys([*look, *b.image_refs_for_shot(shot)]))
        parameters: dict[str, Any] = {
            "prompt": shot.visual_prompt, "duration": shot.duration_seconds,
            "model": model, "resolution": spec.resolution,
            "aspect_ratio": spec.aspect_ratio, "generate_audio": False,
            "reference_from_steps": refs,
            "generation_mode": "reference_to_video" if refs else "t2v",
        }
        # Original Cuti $mv: H3 consumes the segment audio; Seedance consumes
        # images only and receives no audios/@audio reference at all.
        if model_family == "h3":
            parameters["audio_reference_from_step"] = cut
            if isinstance(segments, list) and index < len(segments):
                parameters["audio_segment_index"] = index
        clips.append(b.add(
            f"shot-{shot.id}-video", "video_clip", "api.provider.generate",
            parameters=parameters, depends_on=[shot_plan, cut, *refs], cost=0.65,
        ))
    plan = b.finish(
        clips, transition=0.0, require_audio=True, audio_step=cut,
        captions=bool(spec.audio.subtitles),
    )
    _validate_mv_compat_plan(plan)
    return plan


def _validate_mv_compat_plan(plan: RebuildPlan) -> None:
    """Fail closed on the model-specific contracts documented by Cuti $mv."""
    by_id = _by_id(plan)
    if by_id.get("music-analysis") is None or by_id["music-analysis"].capability != "media.audio_analyze":
        raise BuildPlanValidationError("mv requires music analysis before visual planning")
    if by_id.get("music-cut") is None or by_id["music-cut"].capability != "media.audio_cut":
        raise BuildPlanValidationError("mv requires one approved master music window")
    clips = _video_clips(plan)
    if not clips:
        raise BuildPlanValidationError("mv produced no video clips")
    for clip in clips:
        model = clip.parameters.get("model")
        refs = clip.parameters.get("reference_from_steps") or []
        if model == "minimax-h3":
            if not refs:
                raise BuildPlanValidationError(
                    "mv MiniMax H3 shots require at least one image reference"
                )
            if clip.parameters.get("audio_reference_from_step") != "music-cut":
                raise BuildPlanValidationError(
                    "mv MiniMax H3 shots require their cut audio reference"
                )
        elif model == "doubao-seedance-2-0":
            if any(key in clip.parameters for key in (
                "audio_reference_from_step", "audio_segment_index", "audios", "audio_url",
            )):
                raise BuildPlanValidationError(
                    "mv Seedance shots must not receive audio references"
                )
        else:
            raise BuildPlanValidationError(f"mv uses unsupported video model: {model}")
        if clip.skill_ids:
            raise BuildPlanValidationError("mv must not inject a second video Director Skill")
    final = by_id.get("mixed-video") or by_id.get("final-video")
    if final is None:
        raise BuildPlanValidationError("mv is missing its final output")
    if by_id.get("mixed-video") is not None:
        final = by_id["mixed-video"]
    if final.capability != "media.mix_audio" or final.parameters.get("mode") != "replace":
        raise BuildPlanValidationError("mv must restore the original music with replace mode")


def compile_skill_workflow(
    workflow: WorkflowSpec, context: PluginContext, spec: VideoSpec,
) -> RebuildPlan:
    validate_original_cuti_workflow_contract(workflow)
    mode = workflow.mode
    if mode in UNAVAILABLE_WORKFLOW_MODES:
        raise BuildPlanValidationError(UNAVAILABLE_WORKFLOW_MODES[mode])
    contract = WORKFLOW_ID_COMPILERS.get(workflow.skill_name)
    if contract is None:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} has no dedicated installed compiler"
        )
    expected_mode, compiler = contract
    if mode != expected_mode:
        raise BuildPlanValidationError(
            f"workflow {workflow.skill_name} declares mode {mode}, but its dedicated "
            f"compiler requires {expected_mode}"
        )
    return compiler(workflow, context, spec)


# Bind the compiler to the authoritative Cuti Workflow Skill identity as well
# as its mode.  A mode is only a contract label; it is not permission for an
# unrelated or newly-installed Skill to inherit a similarly-shaped Cuti DAG.
# This prevents a misspelled/copied frontmatter mode from becoming an implicit
# default compiler.
WORKFLOW_ID_COMPILERS = {
    "cinematic": ("seedance2", compile_seedance2),
    "seedance2": ("seedance2", compile_seedance2),
    "mv": ("mv", compile_mv_compat),
    "short-drama-workflow": ("short_drama_workflow", compile_short_drama_workflow),
    "cuti-product-workflow": ("cuti_product_workflow", compile_cuti_product),
    "cuti-scenario-product-workflow": (
        "cuti_scenario_product_workflow", compile_scenario_product,
    ),
}

if {
    mode for mode, _compiler in WORKFLOW_ID_COMPILERS.values()
} != SUPPORTED_WORKFLOW_MODES:  # pragma: no cover - import invariant
    raise RuntimeError("workflow ids and supported workflow modes are out of sync")
