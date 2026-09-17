from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.orchestration.workflow_compiler.registry import WorkflowSpec
from app.video_runtime.models import (
    CheckpointResolution, MediaArtifactVersion, ProjectIntent, RebuildPlan,
    RebuildPlanItem, ValidationResult, VideoLanguageContract,
)
from app.video_runtime.repository import PlanRevisionConflict
from app.video_runtime.checkpoint_coordinator import CheckpointCoordinator, checkpoint_prompt
from app.video_runtime.models import PlanCheckpoint
from app.video_runtime.runtime import (
    _bind_shared_video_references, _checkpoint_artifact_summary,
    _implicit_artifact_inputs, _parameter_step_references,
)
from app.video_runtime.staged_planning import (
    append_continuous_plan_patch,
    append_phase,
    compile_continuous_plan_initial,
    failed_checkpoint_step_ids,
    initial_checkpoint,
)
from app.video_runtime.plan_utils import BuildPlanValidationError
from app.video_runtime.plugins import PluginContext

from test_initial_build import FakePlanExecutor, video_runtime, video_spec


class _CheckpointRepo:
    def __init__(self, checkpoint: PlanCheckpoint) -> None:
        self.checkpoint = checkpoint
        self.failed: list[tuple[str, str]] = []

    async def claim_pending_checkpoint(self, _lease_seconds: int):
        value, self.checkpoint = self.checkpoint, None
        return value

    async def fail_checkpoint_delivery(self, checkpoint_id: str, error: str):
        self.failed.append((checkpoint_id, error))


class _CheckpointRuntime:
    def __init__(self, repo) -> None:
        self.repo = repo


class _DeepSeek:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str, str]] = []

    async def prompt(self, session_id: str, prompt: str, *, mode: str):
        self.prompts.append((session_id, prompt, mode))


class CheckpointCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    def test_media_parameter_artifact_ids_become_authoritative_inputs(self) -> None:
        image_id = "9ea8e8dc-1346-4ef0-8fcb-64e4caa9ad3e"
        audio_id = "223c2431-84d6-4109-8fa5-f7b191b3036b"
        self.assertCountEqual(
            _implicit_artifact_inputs(
                {
                    "reference_images": [image_id, "https://cdn.test/reference.webp"],
                    "audio_url": audio_id,
                    "prompt": image_id,
                },
                {image_id, audio_id},
            ),
            [image_id, audio_id],
        )

    def test_reference_step_selectors_become_dag_dependencies(self) -> None:
        self.assertCountEqual(
            _parameter_step_references(
                {
                    "character_reference_from_steps": ["character"],
                    "start_image_from_step": "tail",
                },
                {"character", "tail"},
            ),
            ["character", "tail"],
        )

    def test_reference_step_selectors_reject_unknown_tasks(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown tasks: missing"):
            _parameter_step_references(
                {"reference_from_steps": ["missing"]}, {"character"},
            )

    def test_shared_reference_policy_cannot_silently_degrade_to_text_to_video(self) -> None:
        character = RebuildPlanItem(
            step_id="character", action="create", capability="atomic.image.generate",
            output_artifact_type="character_setting_reference",
        )
        setting = RebuildPlanItem(
            step_id="setting", action="create", capability="atomic.image.generate",
            output_artifact_type="scene_setting_reference",
        )
        clip = RebuildPlanItem(
            step_id="clip", action="create", capability="atomic.video.generate",
            output_artifact_type="video_segment",
            parameters={"continuity_mode": "shared_reference_images"},
        )
        _bind_shared_video_references([character, setting, clip], [clip])
        self.assertEqual(clip.parameters["reference_from_steps"], ["character", "setting"])
        self.assertEqual(clip.depends_on, ["character", "setting"])

    def test_shared_reference_policy_rejects_missing_reference_media(self) -> None:
        clip = RebuildPlanItem(
            step_id="clip", action="create", capability="atomic.video.generate",
            output_artifact_type="video_segment",
            parameters={"continuity_mode": "shared_reference_images"},
        )
        with self.assertRaisesRegex(ValueError, "no identity or setting reference"):
            _bind_shared_video_references([clip], [clip])

    def test_legacy_intent_receives_a_complete_language_contract(self) -> None:
        intent = ProjectIntent(
            title="English film", brief="Make a film", language="en-US",
            workflow_id="seedance2",
        )
        self.assertEqual(intent.language_contract.content_language, "en-US")
        self.assertEqual(intent.language_contract.subtitle_language, "en-US")

    def test_conflicting_legacy_and_structured_languages_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "content_language"):
            ProjectIntent(
                title="Film", brief="Make a film", language="zh-CN",
                language_contract=VideoLanguageContract(content_language="en-US"),
                workflow_id="seedance2",
            )

    def test_unknown_plugin_has_no_implicit_direct_video_phase(self) -> None:
        with self.assertRaisesRegex(
            BuildPlanValidationError,
            "no dedicated staged-planning contract",
        ):
            initial_checkpoint(None, "unknown-plugin-workflow")

    def test_known_mode_cannot_select_a_default_staged_phase(self) -> None:
        copied = WorkflowSpec(
            skill_name="third-party-lookalike",
            title="Not a Cuti music workflow",
            mode="mv",
        )
        with self.assertRaisesRegex(
            BuildPlanValidationError,
            "no dedicated staged-planning contract",
        ):
            initial_checkpoint(copied, copied.skill_name)

    def test_workflow_id_cannot_change_its_staged_planning_mode(self) -> None:
        wrong_mode = WorkflowSpec(
            skill_name="mv",
            title="Music Video",
            mode="seedance2",
        )
        with self.assertRaisesRegex(
            BuildPlanValidationError,
            "dedicated staged-planning contract requires mv",
        ):
            initial_checkpoint(wrong_mode, wrong_mode.skill_name)

    async def test_checkpoint_summary_keeps_bounded_generated_text(self) -> None:
        artifact = MediaArtifactVersion(
            project_id="project-1",
            artifact_id="story:main",
            type="story_draft",
            metadata={"content": "x" * 20_000, "generation_parameters": {"secret": True}},
        )
        summary = _checkpoint_artifact_summary(artifact)
        self.assertTrue(summary["metadata"]["content"]["truncated"])
        self.assertNotIn("generation_parameters", summary["metadata"])

    async def test_checkpoint_summary_exposes_only_safe_generation_context(self) -> None:
        artifact = MediaArtifactVersion(
            project_id="project-1",
            artifact_id="shot:2:clip",
            type="video_clip",
            metadata={
                "generation_parameters": {
                    "prompt": "A complete duration-aware provider prompt",
                    "duration_seconds": 15,
                    "api_key": "must-not-leak",
                },
                "resolved_generation_parameters": {
                    "prompt": "The exact resolved provider prompt",
                    "model": "seedance-2.5",
                    "authorization": "must-not-leak-either",
                },
            },
        )
        summary = _checkpoint_artifact_summary(artifact)
        context = summary["metadata"]["generation_context"]
        self.assertEqual(context["prompt"], "The exact resolved provider prompt")
        self.assertEqual(context["duration_seconds"], 15)
        self.assertEqual(context["model"], "seedance-2.5")
        self.assertNotIn("api_key", context)
        self.assertNotIn("authorization", context)
        self.assertNotIn("generation_parameters", summary["metadata"])

    async def test_delivers_auditable_prompt_to_same_session(self) -> None:
        checkpoint = PlanCheckpoint(
            project_id="project-1", build_id="build-1", plan_id="plan-1",
            workflow_id="mv", session_id="session-1", user_id="user-1",
            phase="music_analysis", next_phase="visual_production",
            artifact_summaries=[{"id": "audio-1", "type": "audiomap", "duration": 58}],
            unresolved_sections=["shots", "captions"],
            base_plan_revision=1, base_spec_revision=1,
            delivery_attempts=1, delivery_id="delivery-1",
        )
        repo = _CheckpointRepo(checkpoint)
        deepseek = _DeepSeek()
        coordinator = CheckpointCoordinator(
            _CheckpointRuntime(repo), deepseek, poll_seconds=0.01,
        )
        self.assertTrue(await coordinator.run_once())
        self.assertEqual(deepseek.prompts[0][0], "session-1")
        self.assertEqual(deepseek.prompts[0][2], "queue")
        prompt = deepseek.prompts[0][1]
        self.assertIn("video_checkpoint_inspect", prompt)
        self.assertIn("video_checkpoint_resolve", prompt)
        self.assertIn("skillDependencies", prompt)
        self.assertIn("video_skill_load", prompt)
        self.assertIn("video_plan_patch_capability_list", prompt)
        self.assertIn("parameters_schema", prompt)
        self.assertIn('"duration": 58', prompt)
        self.assertIn('"thread_id": "session-1"', prompt)
        self.assertIn("Session's prior user instructions, tool results, and compaction summary", prompt)
        self.assertNotIn("chain-of-thought", checkpoint_prompt(checkpoint).lower())

    def test_continuous_patch_rejects_accidental_prompt_detail_regression(self) -> None:
        detailed = "Detailed cinematic direction with subject identity, wardrobe, setting, " * 5
        plan = RebuildPlan(
            project_id="project-1", base_project_version_id="version-1",
            workflow_id="seedance2", schema_version=2,
            items=[RebuildPlanItem(
                step_id="clip-1", action="create", capability="atomic.video.generate",
                output_artifact_type="video_clip",
                parameters={"prompt": detailed, "duration_seconds": 15},
            )],
        )
        with self.assertRaisesRegex(BuildPlanValidationError, "materially less detailed"):
            append_continuous_plan_patch(
                existing_plan=plan,
                proposed_steps=[RebuildPlanItem(
                    step_id="clip-2", action="create", capability="atomic.video.generate",
                    output_artifact_type="video_clip",
                    parameters={"prompt": "The character walks away.", "duration_seconds": 15},
                )],
                allowed_capabilities=None, completed_step_ids={"clip-1"},
                spec=None, spec_revision_id="spec-1",
            )

    def test_continuous_patch_allows_explicitly_intentional_concise_prompt(self) -> None:
        detailed = "Detailed cinematic direction with subject identity, wardrobe, setting, " * 5
        plan = RebuildPlan(
            project_id="project-1", base_project_version_id="version-1",
            workflow_id="seedance2", schema_version=2,
            items=[RebuildPlanItem(
                step_id="clip-1", action="create", capability="atomic.video.generate",
                output_artifact_type="video_clip",
                parameters={"prompt": detailed, "duration_seconds": 15},
            )],
        )
        updated, added = append_continuous_plan_patch(
            existing_plan=plan,
            proposed_steps=[RebuildPlanItem(
                step_id="clip-2", action="create", capability="atomic.video.generate",
                output_artifact_type="video_clip",
                parameters={
                    "prompt": "A deliberately minimal locked-off shot.",
                    "duration_seconds": 15,
                    "allow_concise_prompt": True,
                },
            )],
            allowed_capabilities=None, completed_step_ids={"clip-1"},
            spec=None, spec_revision_id="spec-1",
        )
        self.assertEqual(added, ["clip-2"])
        self.assertEqual(updated.current_revision, plan.current_revision + 1)

    async def test_semantic_repair_appends_one_new_media_branch(self) -> None:
        document = RebuildPlanItem(
            step_id="spec", action="create", capability="runtime.artifact.persist",
            output_artifact_type="video_spec",
        )
        clip = RebuildPlanItem(
            step_id="clip", action="create", capability="atomic.video.generate",
            output_artifact_type="video_clip", depends_on=["spec"],
        )
        validation = RebuildPlanItem(
            step_id="validate", action="validate", capability="cuti.continuity.validate",
            output_artifact_type="validation", depends_on=["clip"],
        )
        existing = RebuildPlan(
            project_id="project-1", base_project_version_id="version-1",
            workflow_id="seedance2", items=[document, clip, validation], schema_version=2,
        )
        full = existing.model_copy(deep=True)
        added, next_checkpoint = append_phase(
            existing_plan=existing, full_plan=full, workflow=None,
            checkpoint_id="semantic_validation",
        )
        self.assertIsNone(next_checkpoint)
        self.assertEqual(
            [item.step_id for item in added],
            ["clip-repair-1", "validate-repair-1"],
        )
        self.assertEqual(added[1].depends_on, ["clip-repair-1"])

    async def test_scene_repair_keeps_unaffected_character_and_product_references(self) -> None:
        items = [
            RebuildPlanItem(
                step_id="character", action="create", capability="atomic.image.generate",
                output_artifact_type="image",
            ),
            RebuildPlanItem(
                step_id="scene", action="create", capability="atomic.image.generate",
                output_artifact_type="image",
            ),
            RebuildPlanItem(
                step_id="product", action="create", capability="atomic.image.generate",
                output_artifact_type="image",
            ),
            RebuildPlanItem(
                step_id="validate-settings", action="validate",
                capability="cuti.continuity.validate",
                output_artifact_type="validation",
                depends_on=["character", "scene", "product"],
            ),
            RebuildPlanItem(
                step_id="clip", action="create", capability="api.provider.generate",
                output_artifact_type="video_clip",
                depends_on=["character", "scene", "product", "validate-settings"],
            ),
            RebuildPlanItem(
                step_id="final", action="create", capability="media.concat",
                output_artifact_type="final_video", depends_on=["clip"],
            ),
        ]
        existing = RebuildPlan(
            project_id="project-1", base_project_version_id="version-1",
            workflow_id="cuti-scenario-product-workflow", items=items,
            schema_version=2,
        )
        checkpoint = PlanCheckpoint(
            project_id="project-1", build_id="build-1", plan_id=existing.id,
            workflow_id=existing.workflow_id, session_id="session-1", user_id="user-1",
            phase="semantic_validation", next_phase="semantic_repair",
            base_plan_revision=1, base_spec_revision=1,
            artifact_summaries=[
                {"metadata": {"plan_step_id": "character"}},
                {
                    "metadata": {"plan_step_id": "scene"},
                    "issues": ["rendered scene contains a person"],
                },
                {"metadata": {"plan_step_id": "product"}},
            ],
        )
        repair_ids = failed_checkpoint_step_ids(checkpoint)
        added, next_checkpoint = append_phase(
            existing_plan=existing,
            full_plan=existing.model_copy(deep=True),
            workflow=None,
            checkpoint_id="semantic_validation",
            repair_step_ids=repair_ids,
        )

        self.assertIsNone(next_checkpoint)
        self.assertEqual(repair_ids, ["scene"])
        added_ids = {item.step_id for item in added}
        self.assertEqual(added_ids, {
            "scene-repair-1", "validate-settings-repair-1",
            "clip-repair-1", "final-repair-1",
        })
        self.assertNotIn("character-repair-1", added_ids)
        self.assertNotIn("product-repair-1", added_ids)


class StagedPlanningRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runtime = await video_runtime()
        self.runtime.staged_planning_enabled = True
        self.project, self.version = await self.runtime.create_project(
            user_id="user-1", title="Staged MV",
        )
        await self.runtime.bind_session(
            project_id=self.project.id,
            session_id="session-1",
            user_id="user-1",
        )

    async def asyncTearDown(self) -> None:
        await self.runtime.close()

    async def test_mv_waits_for_real_music_before_visual_plan(self) -> None:
        intent = ProjectIntent(
            title="Staged MV",
            brief="Create a city-night music video",
            target_duration_seconds=15,
            workflow_id="mv",
            workflow_parameters={"music_prompt": "quiet electronic pop"},
        )
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=intent,
            idempotency_key="plan-1",
        )
        self.assertEqual(plan.schema_version, 2)
        self.assertEqual(
            [item.step_id for item in plan.items],
            ["intent", "music", "music-analysis", "music-cut"],
        )
        self.assertNotIn("shot-one-video", {item.step_id for item in plan.items})

        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="build-1",
            session_id="session-1",
            user_id="user-1",
        )
        executor = FakePlanExecutor()
        waiting, committed = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=executor,
        )
        self.assertIsNone(committed)
        self.assertEqual(waiting.status, "waiting_agent")
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[0]
        self.assertEqual(checkpoint.phase, "music_analysis")
        self.assertEqual(checkpoint.session_id, "session-1")
        self.assertEqual(
            {item["type"] for item in checkpoint.artifact_summaries},
            {"audiomap", "audio_cut"},
        )

        complete_spec = video_spec().model_copy(update={
            "workflow_id": "mv",
            "audio": video_spec().audio.model_copy(update={
                "bgm_prompt": "quiet electronic pop", "subtitles": False,
            }),
        })
        updated = await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=checkpoint.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="resolve-1",
                video_spec_patch={
                    "characters": [
                        item.model_dump(mode="json") for item in complete_spec.characters
                    ],
                    "shots": [item.model_dump(mode="json") for item in complete_spec.shots],
                    "audio": complete_spec.audio.model_dump(mode="json"),
                },
                reason="Plan shots from the measured track",
            ),
            session_id="session-1",
            user_id="user-1",
        )
        self.assertEqual(updated.current_revision, 2)
        self.assertIn("shot-one-video", {item.step_id for item in updated.items})
        resumed = await self.runtime.repo.get_build(self.project.id, build.id)
        self.assertEqual(resumed.status, "queued")

    async def test_every_selectable_workflow_keeps_its_initial_phase_contract(self) -> None:
        expected = {
            "mv": ["intent", "music", "music-analysis", "music-cut"],
            "short-drama-workflow": ["intent", "story-draft"],
            "seedance2": ["intent"],
            "cuti-product-workflow": ["intent", "source-1", "product-analysis"],
            "cuti-scenario-product-workflow": ["intent", "source-1", "product-analysis"],
        }
        music = {"mv"}
        products = {
            "cuti-product-workflow",
            "cuti-scenario-product-workflow",
        }
        for index, (workflow_id, expected_steps) in enumerate(expected.items(), start=1):
            project, version = await self.runtime.create_project(
                user_id="user-1", title=f"phase {workflow_id}",
            )
            source_ids: list[str] = []
            if workflow_id in products:
                source = await self.runtime.add_artifact(MediaArtifactVersion(
                    artifact_id=f"source:product:{index}",
                    project_id=project.id,
                    type="source_image",
                    uri=f"https://media.test/product-{index}.png",
                ))
                source_ids = [source.artifact_id]
                project = await self.runtime.repo.get_project(project.id)
            intent = ProjectIntent(
                title=workflow_id,
                brief=f"Create with {workflow_id}",
                target_duration_seconds=15,
                workflow_id=workflow_id,
                source_asset_ids=source_ids,
                workflow_parameters=(
                    {"music_prompt": "electronic pop"}
                    if workflow_id in music else {}
                ),
            )
            plan = await self.runtime.plan_project(
                project_id=project.id,
                base_project_version_id=project.current_version_id or version.id,
                project_intent=intent,
                idempotency_key=f"initial-contract-{index}",
            )
            self.assertEqual(plan.workflow_id, workflow_id)
            self.assertEqual(
                [item.step_id for item in plan.items],
                expected_steps,
                workflow_id,
            )
            self.assertEqual(plan.schema_version, 2)
            self.assertIsNotNone(plan.next_checkpoint)


    async def test_scenario_product_checkpoint_restores_original_contract(self) -> None:
        source = await self.runtime.add_artifact(MediaArtifactVersion(
            artifact_id="source:product",
            project_id=self.project.id,
            type="source_image",
            uri="https://media.test/product.png",
        ))
        intent = ProjectIntent(
            title="Scenario product ad",
            brief="Use a noisy rehearsal to demonstrate the headphones",
            target_duration_seconds=15,
            workflow_id="cuti-scenario-product-workflow",
            source_asset_ids=[source.artifact_id],
        )
        current = await self.runtime.repo.get_project(self.project.id)
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=current.current_version_id,
            project_intent=intent,
            idempotency_key="plan-scenario-product",
        )
        self.assertEqual(
            [item.step_id for item in plan.items],
            ["intent", "source-1", "product-analysis"],
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=current.current_version_id,
            idempotency_key="build-scenario-product",
            session_id="session-1",
            user_id="user-1",
        )
        waiting, committed = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertIsNone(committed)
        self.assertEqual(waiting.status, "waiting_agent")
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        self.assertIn("segment_proofs", checkpoint.planner_instruction)

        base = video_spec()
        complete_spec = base.model_copy(update={
            "workflow_id": "cuti-scenario-product-workflow",
            "source_asset_ids": [source.artifact_id],
            "target_duration_seconds": 15,
            "shots": [base.shots[0].model_copy(update={
                "id": "one",
                "order": 1,
                "duration_seconds": 15,
                "visual_prompt": "0-2秒排练被噪声打断；2-15秒戴上耳机后听清节拍并完成合奏。",
                "narration": "",
            })],
            "audio": base.audio.model_copy(update={
                "bgm_prompt": "", "subtitles": False,
            }),
            "workflow_parameters": {
                "primary_selling_point": "嘈杂环境中依然清晰聆听",
                "segment_proofs": {
                    "one": "戴上耳机后环境噪声降低，人物听清节拍并完成合奏",
                },
                "dramatic_proposition": "耳机让嘈杂排练恢复清晰协作",
            },
        })
        updated = await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=checkpoint.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="resolve-scenario-product",
                video_spec=complete_spec,
            ),
            session_id="session-1",
            user_id="user-1",
        )
        by_id = {item.step_id: item for item in updated.items}
        clip = by_id["shot-one-video"]
        self.assertEqual(clip.capability, "api.provider.generate")
        self.assertEqual(clip.parameters["duration"], 15)
        self.assertTrue(clip.parameters["generate_audio"])
        self.assertEqual(clip.parameters["generation_mode"], "t2v")
        self.assertNotIn("start_image_from_step", clip.parameters)
        self.assertEqual(
            set(clip.parameters["reference_from_steps"]),
            {
                "source-1", "character-setting-reference",
                "scene-setting-reference", "product-setting-reference",
            },
        )
        self.assertTrue(all(
            "scenario-script" in by_id[step].depends_on
            for step in (
                "character-setting-reference", "scene-setting-reference",
                "product-setting-reference",
            )
        ))

    async def test_every_single_checkpoint_workflow_appends_its_own_compiler_plan(self) -> None:
        """Schema-v2 continuation may stage a compiler, but may never replace it."""
        workflows = (
            "mv", "seedance2",
            "short-drama-workflow", "cuti-product-workflow",
            "cuti-scenario-product-workflow",
        )
        product_workflows = {
            "cuti-product-workflow",
            "cuti-scenario-product-workflow",
        }
        music_workflows = {
            "mv",
        }
        for index, workflow_id in enumerate(workflows, start=1):
            project, version = await self.runtime.create_project(
                user_id="user-1", title=f"continuation {workflow_id}",
            )
            session_id = f"continuation-session-{index}"
            await self.runtime.bind_session(
                project_id=project.id, session_id=session_id, user_id="user-1",
            )
            source_ids: list[str] = []
            if workflow_id in product_workflows:
                source = await self.runtime.add_artifact(MediaArtifactVersion(
                    artifact_id=f"source:product:continuation:{index}",
                    project_id=project.id,
                    type="source_image",
                    uri=f"https://media.test/continuation-product-{index}.png",
                ))
                source_ids = [source.artifact_id]
                project = await self.runtime.repo.get_project(project.id)

            base = video_spec()
            one_segment = workflow_id in {
                "short-drama-workflow", "cuti-product-workflow",
                "cuti-scenario-product-workflow",
            }
            shots = (
                [base.shots[0].model_copy(update={
                    "id": "one", "order": 1, "duration_seconds": 15,
                    "visual_prompt": "0-15秒，人物通过连续动作完成这一段叙事。",
                    "narration": "原生同步对白。",
                    "reference_asset_ids": source_ids,
                })]
                if one_segment else [
                    shot.model_copy(update={"reference_asset_ids": source_ids})
                    for shot in base.shots
                ]
            )
            workflow_parameters = dict(base.workflow_parameters)
            if workflow_id in music_workflows:
                workflow_parameters["music_prompt"] = "electronic pop"
            if workflow_id == "cuti-scenario-product-workflow":
                workflow_parameters = {
                    "primary_selling_point": "嘈杂环境中保持清晰",
                    "segment_proofs": {"one": "戴上耳机后人物听清节拍"},
                    "dramatic_proposition": "噪声阻碍协作，产品恢复清晰",
                    "scenario": {"setting": "空置排练室，暖色顶灯"},
                }
            spec = base.model_copy(update={
                "title": workflow_id,
                "workflow_id": workflow_id,
                "target_duration_seconds": 15,
                "source_asset_ids": source_ids,
                "shots": shots,
                "workflow_parameters": workflow_parameters,
                "audio": base.audio.model_copy(update={
                    "bgm_prompt": "electronic pop" if workflow_id in music_workflows else "",
                    "subtitles": workflow_id == "mv",
                }),
            })
            intent = ProjectIntent(
                title=workflow_id,
                brief=f"Create with {workflow_id}",
                target_duration_seconds=15,
                workflow_id=workflow_id,
                source_asset_ids=source_ids,
                workflow_parameters=workflow_parameters,
                providers=spec.providers,
            )
            plan = await self.runtime.plan_project(
                project_id=project.id,
                base_project_version_id=project.current_version_id or version.id,
                project_intent=intent,
                idempotency_key=f"continuation-plan-{index}",
            )
            build = await self.runtime.start_build(
                project_id=project.id,
                plan_id=plan.id,
                base_project_version_id=project.current_version_id or version.id,
                idempotency_key=f"continuation-build-{index}",
                session_id=session_id,
                user_id="user-1",
            )
            waiting, committed = await self.runtime.execute_build(
                project_id=project.id, build_id=build.id, executor=FakePlanExecutor(),
            )
            self.assertIsNone(committed, workflow_id)
            self.assertEqual(waiting.status, "waiting_agent", workflow_id)
            checkpoint = (await self.runtime.repo.list_build_checkpoints(
                project.id, build.id,
            ))[-1]

            plugin = self.runtime._workflow_plugin(workflow_id)
            source_artifacts = {
                item.artifact_id: item
                for item in await self.runtime.repo.current_artifacts(project.id)
                if item.artifact_id in source_ids
            }
            from app.video_runtime.plugins import PluginContext
            expected = await plugin.implementation.compile_build_plan(
                PluginContext(project_id=project.id, values={
                    "base_project_version_id": project.current_version_id or version.id,
                    "source_artifacts": source_artifacts,
                }),
                spec,
            )
            updated = await self.runtime.resolve_checkpoint(
                project_id=project.id,
                build_id=build.id,
                checkpoint_id=checkpoint.id,
                resolution=CheckpointResolution(
                    base_plan_revision=plan.current_revision,
                    base_spec_revision=1,
                    idempotency_key=f"continuation-resolve-{index}",
                    video_spec=spec,
                ),
                session_id=session_id,
                user_id="user-1",
            )
            self.assertEqual(updated.workflow_id, workflow_id)
            updated_by_id = {item.step_id: item for item in updated.items}
            for expected_step in expected.items:
                self.assertIn(expected_step.step_id, updated_by_id, workflow_id)
                self.assertEqual(
                    updated_by_id[expected_step.step_id].capability,
                    expected_step.capability,
                    f"{workflow_id}:{expected_step.step_id}",
                )

    async def test_checkpoint_rejects_stale_plan_revision(self) -> None:
        intent = ProjectIntent(
            title="Direct", brief="One cinematic shot", workflow_id="seedance2",
        )
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=intent,
            idempotency_key="plan-direct",
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="build-direct",
            session_id="session-1",
            user_id="user-1",
        )
        await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[0]
        with self.assertRaises(PlanRevisionConflict):
            await self.runtime.resolve_checkpoint(
                project_id=self.project.id,
                build_id=build.id,
                checkpoint_id=checkpoint.id,
                resolution=CheckpointResolution(
                    base_plan_revision=2,
                    base_spec_revision=1,
                    idempotency_key="stale",
                    video_spec=video_spec().model_copy(update={"workflow_id": "seedance2"}),
                ),
                session_id="session-1",
                user_id="user-1",
            )

    async def test_seedance2_agentic_phase_cannot_switch_to_another_video_model(self) -> None:
        intent = ProjectIntent(
            title="Seedance agentic guard",
            brief="Create one native-audio Seedance clip",
            workflow_id="seedance2",
        )
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=intent,
            idempotency_key="plan-seedance-agentic-guard",
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="build-seedance-agentic-guard",
            session_id="session-1",
            user_id="user-1",
        )
        await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        wrong_provider_step = RebuildPlanItem(
            step_id="wrong-video",
            output_artifact_id=f"{self.project.id}:wrong-video",
            output_artifact_type="video_clip",
            action="create",
            capability="atomic.video.generate",
            parameters={
                "prompt": "one shot",
                "model": "minimax-h3",
                "generate_audio": True,
            },
            depends_on=["intent"],
        )
        with self.assertRaisesRegex(
            BuildPlanValidationError,
            "must use the Seedance 2.0 provider model",
        ):
            await self.runtime.resolve_checkpoint(
                project_id=self.project.id,
                build_id=build.id,
                checkpoint_id=checkpoint.id,
                resolution=CheckpointResolution(
                    base_plan_revision=1,
                    base_spec_revision=1,
                    idempotency_key="resolve-wrong-seedance-model",
                    video_spec=video_spec().model_copy(update={
                        "workflow_id": "seedance2",
                    }),
                    proposed_steps=[wrong_provider_step],
                ),
                session_id="session-1",
                user_id="user-1",
            )


    async def test_semantic_failure_pauses_once_for_agent_repair(self) -> None:
        intent = ProjectIntent(
            title="Continuity repair",
            brief="A traveler catches the last train",
            target_duration_seconds=15,
            workflow_id="seedance2",
        )
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=intent,
            idempotency_key="plan-semantic-repair",
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="build-semantic-repair",
            session_id="session-1",
            user_id="user-1",
        )
        executor = FakePlanExecutor()
        await self.runtime.execute_build(
            project_id=self.project.id, build_id=build.id, executor=executor,
        )
        creative = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        complete_spec = video_spec().model_copy(update={"workflow_id": "seedance2"})
        await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=creative.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="resolve-semantic-production",
                video_spec=complete_spec,
            ),
            session_id="session-1",
            user_id="user-1",
        )

        should_fail = True

        async def validate(*, build_id, artifact):
            return [ValidationResult(
                project_id=self.project.id,
                build_id=build_id,
                artifact_version_id=artifact.id,
                validator_id="cuti.continuity.scene-reference-isolation",
                passed=not should_fail,
                issues=["rendered scene contains a person and staged product"] if should_fail else [],
            )]

        self.runtime.validate_artifact = validate
        waiting, committed = await self.runtime.execute_build(
            project_id=self.project.id, build_id=build.id, executor=executor,
        )
        self.assertIsNone(committed)
        self.assertEqual(waiting.status, "waiting_agent")
        repair = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        self.assertEqual(repair.phase, "semantic_validation")
        self.assertEqual(repair.semantic_repair_attempts, 1)

        should_fail = False
        current_plan = await self.runtime.repo.get_plan(plan.id)
        current_spec = await self.runtime.repo.get_video_spec_revision(
            current_plan.video_spec_revision_id,
        )
        repaired_plan = await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=repair.id,
            resolution=CheckpointResolution(
                base_plan_revision=current_plan.current_revision,
                base_spec_revision=current_spec.revision,
                idempotency_key="resolve-semantic-repair",
                video_spec=complete_spec,
                reason="Regenerate only the empty environment without people or products",
            ),
            session_id="session-1",
            user_id="user-1",
        )
        self.assertTrue(any(
            item.step_id.endswith("-repair-1") for item in repaired_plan.items
        ))
        completed, version = await self.runtime.execute_build(
            project_id=self.project.id, build_id=build.id, executor=executor,
        )
        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(version)


class ContinuousPlanInitializationTest(unittest.TestCase):
    def test_initialization_does_not_require_a_fixed_workflow_compiler(self) -> None:
        # Include aliases and a plugin-owned workflow with no built-in compiler.
        # Availability is checked by Runtime before reaching this function.
        for workflow_id in (
            "seedance2", "cuti.music-video",
            "cuti.lipsync-music-video",
            "cuti-scenario-product-workflow", "workflow-keyframe-pipeline",
            "third-party-agentic-workflow",
        ):
            with self.subTest(workflow=workflow_id):
                plan = compile_continuous_plan_initial(
                    workflow=None,
                    context=PluginContext(project_id="project-1"),
                    intent=ProjectIntent(
                        title="User goal", brief="Create a video", workflow_id=workflow_id,
                    ),
                )
                self.assertEqual([item.step_id for item in plan.items], ["intent"])
                self.assertEqual(plan.workflow_id, workflow_id)
                self.assertEqual(plan.estimated_cost, 0)
                self.assertEqual(plan.next_checkpoint.planning_mode, "agentic")
                self.assertIn(
                    "The loaded Workflow supplies creative choices the user left open.",
                    plan.next_checkpoint.planner_instruction,
                )
                self.assertNotIn("unavailable Artifacts", plan.next_checkpoint.planner_instruction)

    def test_sources_are_reused_but_missing_or_foreign_sources_are_rejected(self) -> None:
        source = MediaArtifactVersion(
            project_id="project-1", artifact_id="source:product", type="source_image",
        )
        intent = ProjectIntent(
            title="Product", brief="Use my product image", workflow_id="cuti-product-workflow",
            source_asset_ids=[source.artifact_id],
        )
        context = PluginContext(project_id="project-1", values={
            "source_artifacts": {source.artifact_id: source},
        })
        plan = compile_continuous_plan_initial(workflow=None, context=context, intent=intent)
        self.assertEqual([item.action for item in plan.items], ["create", "reuse"])
        self.assertEqual(plan.items[1].artifact_version_id, source.id)
        for sources in ({}, {source.artifact_id: source.model_copy(update={"project_id": "other"})}):
            with self.subTest(sources=sources):
                context.values["source_artifacts"] = sources
                with self.assertRaisesRegex(BuildPlanValidationError, "source artifact is unavailable"):
                    compile_continuous_plan_initial(workflow=None, context=context, intent=intent)


class ContinuousPlanPatchRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runtime = await video_runtime()
        self.runtime.staged_planning_enabled = True
        self.runtime.continuous_plan_patch_enabled = True
        self.project, self.version = await self.runtime.create_project(
            user_id="user-1", title="Continuous Cuti loop",
        )
        await self.runtime.bind_session(
            project_id=self.project.id,
            session_id="session-1",
            user_id="user-1",
        )

    async def asyncTearDown(self) -> None:
        await self.runtime.close()

    async def test_plugin_plan_patch_capability_is_available_to_every_workflow(self) -> None:
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=ProjectIntent(
                title="Short drama",
                brief="Create a short drama from an Agent-authored blueprint",
                workflow_id="short-drama-workflow",
            ),
            idempotency_key="continuous-universal-persist-plan",
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="continuous-universal-persist-build",
            session_id="session-1",
            user_id="user-1",
        )
        await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]

        updated = await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=checkpoint.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="continuous-universal-persist-patch",
                video_spec_patch={},
                proposed_steps=[RebuildPlanItem(
                    step_id="production-blueprint",
                    action="create",
                    capability="runtime.artifact.persist",
                    output_artifact_type="production_blueprint",
                    parameters={"content": {"segments": [{"duration": 15}]}},
                    depends_on=["intent"],
                )],
            ),
            session_id="session-1",
            user_id="user-1",
        )

        persisted = next(item for item in updated.items if item.step_id == "production-blueprint")
        self.assertEqual(persisted.capability, "runtime.artifact.persist")
        self.assertEqual(persisted.output_artifact_type, "production_blueprint")

    async def test_deepseek_adds_one_frontier_then_finishes_from_real_artifact(self) -> None:
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=ProjectIntent(
                title="Continuous Cuti loop",
                brief="Generate one native-audio cinematic clip",
                workflow_id="seedance2",
            ),
            idempotency_key="continuous-plan",
        )
        self.assertEqual([item.step_id for item in plan.items], ["intent"])
        self.assertEqual(plan.next_checkpoint.planning_mode, "agentic")
        self.assertTrue(plan.project_intent.constraints["continuous_plan_patch"])

        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="continuous-build",
            session_id="session-1",
            user_id="user-1",
        )
        waiting, version = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertIsNone(version)
        self.assertEqual(waiting.status, "waiting_agent")
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        self.assertIn("video_plan_patch_submit", checkpoint_prompt(checkpoint))

        updated = await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=checkpoint.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="continuous-patch-1",
                video_spec_patch={"workflow_parameters": {"shot_count": 1}},
                proposed_steps=[RebuildPlanItem(
                    step_id="clip-1",
                    action="create",
                    capability="atomic.video.generate",
                    parameters={
                        "prompt": "one cinematic native-audio shot",
                        "model": "seedance-2.0",
                        "generate_audio": True,
                    },
                    depends_on=["intent"],
                )],
            ),
            session_id="session-1",
            user_id="user-1",
        )
        self.assertIsNone(updated.video_spec)
        self.assertEqual(updated.current_revision, 2)

        waiting, version = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertIsNone(version)
        self.assertEqual(waiting.status, "waiting_agent")
        checkpoint = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        final = await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=checkpoint.id,
            resolution=CheckpointResolution(
                base_plan_revision=2,
                base_spec_revision=2,
                idempotency_key="continuous-patch-final",
                video_spec_patch={},
                goal_satisfied=True,
                response="The video is ready in the creation workspace.",
            ),
            session_id="session-1",
            user_id="user-1",
        )
        self.assertIsNone(final.next_checkpoint)
        completed, version = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(version)

    async def test_task_update_checkpoint_reopens_after_each_frontier(self) -> None:
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=ProjectIntent(
                title="Continuous Cuti loop",
                brief="Generate clips in successive frontiers",
                workflow_id="seedance2",
            ),
            idempotency_key="continuous-plan-two-frontiers",
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="continuous-build-two-frontiers",
            session_id="session-1",
            user_id="user-1",
        )
        waiting, _ = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        first = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=first.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="continuous-patch-1",
                video_spec_patch={"workflow_parameters": {"shot_count": 1}},
                proposed_steps=[RebuildPlanItem(
                    step_id="clip-1",
                    action="create",
                    capability="atomic.video.generate",
                    parameters={
                        "prompt": "first frontier clip",
                        "model": "seedance-2.0",
                        "generate_audio": True,
                    },
                    depends_on=["intent"],
                )],
            ),
            session_id="session-1",
            user_id="user-1",
        )
        waiting, _ = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertEqual(waiting.status, "waiting_agent")
        second = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        self.assertTrue(second.phase.startswith("task-update:"))
        await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=second.id,
            resolution=CheckpointResolution(
                base_plan_revision=2,
                base_spec_revision=2,
                idempotency_key="continuous-patch-2",
                video_spec_patch={},
                proposed_steps=[RebuildPlanItem(
                    step_id="clip-2",
                    action="create",
                    capability="atomic.video.generate",
                    parameters={
                        "prompt": "second frontier clip",
                        "model": "seedance-2.0",
                        "generate_audio": True,
                    },
                    depends_on=["clip-1"],
                )],
            ),
            session_id="session-1",
            user_id="user-1",
        )
        waiting, version = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertIsNone(version)
        self.assertEqual(waiting.status, "waiting_agent")
        checkpoints = await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        )
        task_updates = [
            item for item in checkpoints if item.phase.startswith("task-update:")
        ]
        self.assertEqual(len(task_updates), 3)
        self.assertEqual(task_updates[-1].status, "pending")
        self.assertNotEqual(task_updates[0].id, task_updates[-1].id)

    async def test_second_frontier_reopens_waiting_agent_checkpoint(self) -> None:
        plan = await self.runtime.plan_project(
            project_id=self.project.id,
            base_project_version_id=self.version.id,
            project_intent=ProjectIntent(
                title="Continuous Cuti loop",
                brief="Generate clips in successive frontiers",
                workflow_id="seedance2",
            ),
            idempotency_key="continuous-plan-two-frontiers",
        )
        build = await self.runtime.start_build(
            project_id=self.project.id,
            plan_id=plan.id,
            base_project_version_id=self.version.id,
            idempotency_key="continuous-build-two-frontiers",
            session_id="session-1",
            user_id="user-1",
        )
        waiting, _ = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        first = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=first.id,
            resolution=CheckpointResolution(
                base_plan_revision=1,
                base_spec_revision=1,
                idempotency_key="continuous-patch-1",
                video_spec_patch={"workflow_parameters": {"shot_count": 1}},
                proposed_steps=[RebuildPlanItem(
                    step_id="clip-1",
                    action="create",
                    capability="atomic.video.generate",
                    parameters={
                        "prompt": "first frontier clip",
                        "model": "seedance-2.0",
                        "generate_audio": True,
                    },
                    depends_on=["intent"],
                )],
            ),
            session_id="session-1",
            user_id="user-1",
        )
        waiting, _ = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertEqual(waiting.status, "waiting_agent")
        second = (await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        ))[-1]
        self.assertTrue(second.phase.startswith("task-update:"))
        await self.runtime.resolve_checkpoint(
            project_id=self.project.id,
            build_id=build.id,
            checkpoint_id=second.id,
            resolution=CheckpointResolution(
                base_plan_revision=2,
                base_spec_revision=2,
                idempotency_key="continuous-patch-2",
                video_spec_patch={},
                proposed_steps=[RebuildPlanItem(
                    step_id="clip-2",
                    action="create",
                    capability="atomic.video.generate",
                    parameters={
                        "prompt": "second frontier clip",
                        "model": "seedance-2.0",
                        "generate_audio": True,
                    },
                    depends_on=["clip-1"],
                )],
            ),
            session_id="session-1",
            user_id="user-1",
        )
        waiting, version = await self.runtime.execute_build(
            project_id=self.project.id,
            build_id=build.id,
            executor=FakePlanExecutor(),
        )
        self.assertIsNone(version)
        self.assertEqual(waiting.status, "waiting_agent")
        checkpoints = await self.runtime.repo.list_build_checkpoints(
            self.project.id, build.id,
        )
        task_updates = [
            item for item in checkpoints if item.phase.startswith("task-update:")
        ]
        self.assertEqual(len(task_updates), 3)
        self.assertEqual(task_updates[-1].status, "pending")
        self.assertNotEqual(task_updates[0].id, task_updates[-1].id)
