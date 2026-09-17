from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.orchestration.workflow_compiler.registry import WorkflowSpec
from app.capabilities.models import canonical_capability_id
from app.video_runtime.plan_utils import BuildPlanValidationError, topological_steps
from app.video_runtime.models import MediaArtifactVersion, ValidationResult, VideoSpec
from app.video_runtime.plugins import PluginContext, VideoPluginRegistry
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.skill_workflows import load_workflow_skills
from app.video_runtime.skills import VideoSkillRuntime
from app.video_runtime.workflow_plans import (
    ORIGINAL_CUTI_WORKFLOW_CONTRACTS,
    WORKFLOW_ID_COMPILERS,
    _scenario_provider_prompt,
    compile_seedance2,
    compile_skill_workflow,
    validate_original_cuti_workflow_contract,
)


def _spec(
    workflow_id: str,
    *,
    segment_seconds: float = 5,
    source_asset_ids: list[str] | None = None,
    bgm_prompt: str = "",
    subtitles: bool = False,
) -> VideoSpec:
    return VideoSpec.model_validate({
        "title": f"{workflow_id} snapshot",
        "target_duration_seconds": segment_seconds * 2,
        "workflow_id": workflow_id,
        "source_asset_ids": source_asset_ids or [],
        "characters": [{
            "id": "hero", "name": "Hero", "appearance": "black hair",
        }],
        "shots": [{
            "id": str(index), "order": index,
            "duration_seconds": segment_seconds,
            "beat": f"beat {index}",
            "visual_prompt": (
                f"镜头{index}：0-{int(segment_seconds)}秒，主体完成一次清晰可见的动作变化。"
            ),
            "narration": "让产品价值通过画面中的动作被看见。",
            "character_ids": ["hero"],
        } for index in (1, 2)],
        "audio": {"bgm_prompt": bgm_prompt, "subtitles": subtitles},
        "workflow_parameters": {
            "scenes": [{
                "id": "main-location",
                "name": "Main location",
                "description": "A stable recurring interior with clear spatial geography",
            }],
        },
    })


def _signature(plan) -> list[str]:
    return [
        f"{item.step_id}:{item.action}:{item.capability}"
        for item in topological_steps(plan.items)
    ]


def _scenario_spec(source_asset_id: str) -> VideoSpec:
    spec = _spec(
        "cuti-scenario-product-workflow",
        segment_seconds=15,
        source_asset_ids=[source_asset_id],
    )
    return spec.model_copy(update={
        "workflow_parameters": {
            "primary_selling_point": "嘈杂环境中依然清晰聆听",
            # A planner may accidentally put the whole creative bible here.
            # The compiler must prefer the structured scenario.setting below.
            "scene_setting_prompt": (
                "Hero with black hair holds the advertised headphones in the rehearsal room"
            ),
            "segment_proofs": {
                "1": "戴上耳机后环境噪声降低，人物听清节拍",
                "2": "人物按清晰节拍带动团队完成同步表演",
            },
            "dramatic_proposition": "耳机让嘈杂排练恢复清晰协作",
            "scenario": {
                "setting": "雨夜的空置排练室，深色吸音墙和暖色顶灯",
            },
            "character_setting_reference_prompt": "仅生成角色设定图，不得包含产品或场景。",
            "product_setting_reference_prompt": "仅生成产品设定图，不得包含人物或使用场景。",
        },
    })


class ProviderMockExecutor:
    async def execute_plan_step(
        self, *, build, step, completed_artifacts, idempotency_key,
        report_remote_operation=None,
    ) -> MediaArtifactVersion:
        metadata = {
            "generation_parameters": dict(step.parameters),
            "plan_step_id": step.step_id,
        }
        if step.output_artifact_type == "video_spec":
            metadata["content"] = step.parameters["content"]
        if step.output_artifact_type == "timeline":
            cursor = 0.0
            items = []
            for shot, source_step in zip(
                step.parameters["shots"], step.parameters["video_steps"], strict=True,
            ):
                source = completed_artifacts[source_step]
                items.append({
                    "artifactVersionId": source.id,
                    "startSeconds": cursor,
                    "durationSeconds": shot["duration_seconds"],
                })
                cursor += shot["duration_seconds"]
            metadata["timeline"] = {"items": items, "durationSeconds": cursor}
        document_types = {
            "video_spec", "script", "characters", "storyboard",
            "outline", "scenes", "shots", "timeline", "research",
        }
        return MediaArtifactVersion(
            project_id=build.project_id,
            type=step.output_artifact_type,
            uri=(
                None if step.output_artifact_type in document_types
                else f"https://provider-mock.test/{step.step_id}"
            ),
            metadata=metadata,
            provenance={"idempotency_key": idempotency_key},
        )


class WorkflowPlanSnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.skills = VideoSkillRuntime()
        plugins = VideoPluginRegistry()
        await load_workflow_skills(plugins, self.skills)
        self.plugin = plugins.get("cuti.skill-workflows").implementation
        self.source = MediaArtifactVersion(
            id="source-version-1", artifact_id="source:product",
            project_id="project-1", type="source_image",
            uri="https://example.test/product.png",
        )

    async def _compile(self, workflow_id: str, spec: VideoSpec | None = None):
        return await self.plugin.compile_build_plan(
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
                "source_artifacts": {self.source.artifact_id: self.source},
            }),
            spec or _spec(workflow_id),
        )

    def test_scenario_execution_header_is_canonical_after_repair(self) -> None:
        old_header = (
            "任务类型: 产品宣传片\n"
            "核心产品卖点：旧值\n"
            "本片段卖点证明: 旧证明\n"
            "镜头创作要求：旧要求\n"
        )
        result = _scenario_provider_prompt(
            visual_prompt=f"{old_header}{old_header}\n0-15秒：完整剧情动作。",
            primary_selling_point="新卖点",
            segment_proof="新证明",
        )
        self.assertEqual(result.count("任务类型：产品宣传片"), 1)
        self.assertEqual(result.count("核心产品卖点：新卖点"), 1)
        self.assertEqual(result.count("本片段卖点证明：新证明"), 1)
        self.assertNotIn("旧值", result)
        self.assertNotIn("旧证明", result)
        self.assertIn("0-15秒：完整剧情动作。", result)

    def test_every_original_workflow_has_a_distinct_named_compiler(self) -> None:
        compilers = [compiler for _mode, compiler in WORKFLOW_ID_COMPILERS.values()]
        self.assertEqual(len(compilers), len(set(compilers)))
        self.assertEqual(
            {function.__name__ for function in compilers},
            {
                "compile_seedance2", "compile_mv_compat",
                "compile_short_drama_workflow",
                "compile_cuti_product",
                "compile_scenario_product",
            },
        )

    def test_every_installed_workflow_matches_its_locked_cuti_source_contract(self) -> None:
        self.assertEqual(
            set(self.plugin._workflows),
            set(ORIGINAL_CUTI_WORKFLOW_CONTRACTS),
        )
        for workflow_id, workflow in self.plugin._workflows.items():
            with self.subTest(workflow_id=workflow_id):
                validate_original_cuti_workflow_contract(workflow)


    def test_known_mode_cannot_act_as_an_implicit_default_compiler(self) -> None:
        context = PluginContext(project_id="project-1", values={
            "base_project_version_id": "version-1", "source_artifacts": {},
        })
        copied_mode = WorkflowSpec(
            skill_name="third-party-lookalike",
            title="Not a Cuti workflow",
            mode="direct_video",
        )
        with self.assertRaisesRegex(
            BuildPlanValidationError,
            "has no locked original Cuti contract",
        ):
            compile_skill_workflow(
                copied_mode,
                context,
                _spec("third-party-lookalike"),
            )



    def test_original_cuti_workflow_instruction_bodies_are_preserved(self) -> None:
        """Planning frontmatter may grow; the original Cuti instructions may not drift."""
        expected_hashes = {
            "cuti-product-workflow": "141aa613a932a7552e6c6ea62fd88ad7ceec35c61ab7dff407eb138db7b68fb7",
            "cuti-scenario-product-workflow": "46f179443bbf2377dfe238a519b15cfff54adfee239a6b0bce61a5a1bc9a3996",
            "seedance2": "a496b7e4b2ed260753355de549b0606e38236692461cff601be05021fe4db7d7",
            "short-drama-workflow": "d81a99f35a4fddf2772e1aa5c861ec7f53ec88690e136f3048523c68c8143c4c",
        }
        root = Path(__file__).resolve().parents[2] / "skills"
        skills = {path.parent.name: path for path in root.rglob("SKILL.md")}
        self.assertTrue(set(expected_hashes) <= set(skills))
        for workflow_id, expected_hash in expected_hashes.items():
            text = skills[workflow_id].read_text(encoding="utf-8")
            parts = text.split("---", 2)
            self.assertEqual(len(parts), 3, workflow_id)
            body = re.sub(r"[ \t]+(?=\n|$)", "", parts[2].strip())
            actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
            self.assertEqual(actual, expected_hash, workflow_id)


    async def test_seedance2_uses_uploaded_images_as_shot_refs(self) -> None:
        spec = _spec("seedance2", source_asset_ids=[self.source.artifact_id])
        plan = compile_seedance2(
            WorkflowSpec(skill_name="seedance2", title="seedance2", mode="seedance2"),
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
                "source_artifacts": {self.source.artifact_id: self.source},
            }),
            spec,
        )
        by_id = {item.step_id: item for item in plan.items}
        self.assertNotIn("characters", by_id)
        self.assertNotIn("character-hero-reference", by_id)
        self.assertNotIn("atomic.image.generate", {item.capability for item in plan.items})
        clips = [item for item in plan.items if item.capability == "atomic.video.generate"]
        self.assertTrue(clips)
        self.assertEqual(clips[0].parameters["reference_from_steps"], ["source-1"])

    async def test_seedance2_preserves_uploaded_video_and_audio_references(self) -> None:
        video = MediaArtifactVersion(
            id="source-video-version", artifact_id="source:video",
            project_id="project-1", type="source_video",
            uri="https://example.test/motion.mp4",
        )
        audio = MediaArtifactVersion(
            id="source-audio-version", artifact_id="source:audio",
            project_id="project-1", type="source_audio",
            uri="https://example.test/rhythm.mp3",
        )
        spec = _spec(
            "seedance2",
            source_asset_ids=[video.artifact_id, audio.artifact_id],
        )
        plan = compile_seedance2(
            WorkflowSpec(skill_name="seedance2", title="seedance2", mode="seedance2"),
            PluginContext(project_id="project-1", values={
                "base_project_version_id": "version-1",
                "source_artifacts": {
                    video.artifact_id: video,
                    audio.artifact_id: audio,
                },
            }),
            spec,
        )
        clips = [item for item in plan.items if item.output_artifact_type == "video_clip"]
        self.assertTrue(clips)
        self.assertTrue(all(
            item.parameters["video_reference_from_steps"] == ["source-1"]
            and item.parameters["audio_reference_from_steps"] == ["source-2"]
            and item.parameters["generation_mode"] == "reference_to_video"
            for item in clips
        ))

    async def test_seedance2_tail_continuation_is_explicit_not_default(self) -> None:
        workflow = WorkflowSpec(skill_name="seedance2", title="seedance2", mode="seedance2")
        context = PluginContext(project_id="project-1", values={
            "base_project_version_id": "version-1", "source_artifacts": {},
        })
        cut_plan = compile_seedance2(workflow, context, _spec("seedance2"))
        self.assertFalse(any(item.capability == "media.extract_frame" for item in cut_plan.items))
        continuous = _spec("seedance2")
        continuous = continuous.model_copy(update={
            "shots": [
                continuous.shots[0],
                continuous.shots[1].model_copy(update={"transition": "continuous"}),
            ],
        })
        continuous_plan = compile_seedance2(workflow, context, continuous)
        tails = [item for item in continuous_plan.items if item.capability == "media.extract_frame"]
        self.assertEqual([item.step_id for item in tails], ["shot-1-tail-for-2"])

    async def test_scene_based_workflows_refuse_a_generic_runtime_location(self) -> None:
        for workflow_id in ("short-drama-workflow",):
            if workflow_id not in self.plugin._workflows:
                continue
            spec = _spec(
                workflow_id,
                segment_seconds=15,
            ).model_copy(update={"workflow_parameters": {}})
            with self.assertRaisesRegex(
                BuildPlanValidationError,
                "requires workflow_parameters.scenes",
            ):
                await self._compile(workflow_id, spec)

    async def test_scenario_product_fails_closed_without_execution_contract(self) -> None:
        if "cuti-scenario-product-workflow" not in self.plugin._workflows:
            self.skipTest("scenario product workflow is not installed")
        missing_selling_point = _spec(
            "cuti-scenario-product-workflow",
            segment_seconds=15,
            source_asset_ids=[self.source.artifact_id],
        )
        with self.assertRaisesRegex(BuildPlanValidationError, "primary_selling_point"):
            await self._compile(
                "cuti-scenario-product-workflow",
                missing_selling_point,
            )

        invalid_duration = _scenario_spec(self.source.artifact_id).model_copy(update={
            "target_duration_seconds": 10,
            "shots": [
                shot.model_copy(update={"duration_seconds": 5})
                for shot in _scenario_spec(self.source.artifact_id).shots
            ],
        })
        with self.assertRaisesRegex(BuildPlanValidationError, "15-second"):
            await self._compile("cuti-scenario-product-workflow", invalid_duration)

        contaminated = _scenario_spec(self.source.artifact_id).model_copy(deep=True)
        contaminated.workflow_parameters.pop("scenario", None)
        with self.assertRaisesRegex(
            BuildPlanValidationError,
            "scene_setting_prompt must describe the empty environment only",
        ):
            await self._compile("cuti-scenario-product-workflow", contaminated)

    async def test_scenario_product_copies_proof_from_canonical_prompt_header(self) -> None:
        if "cuti-scenario-product-workflow" not in self.plugin._workflows:
            self.skipTest("scenario product workflow is not installed")
        spec = _scenario_spec(self.source.artifact_id)
        parameters = dict(spec.workflow_parameters)
        parameters.pop("segment_proofs")
        shots = [
            shot.model_copy(update={
                "visual_prompt": (
                    "任务类型：产品宣传片\n"
                    "核心产品卖点：嘈杂环境中依然清晰聆听\n"
                    f"本片段卖点证明：第{index}段可见因果证明\n"
                    "0-15秒完整动作。"
                ),
            })
            for index, shot in enumerate(spec.shots, start=1)
        ]
        plan = await self._compile(
            "cuti-scenario-product-workflow",
            spec.model_copy(update={"workflow_parameters": parameters, "shots": shots}),
        )
        clips = [item for item in plan.items if item.output_artifact_type == "video_clip"]
        self.assertEqual(
            [item.parameters["segment_proof"] for item in clips],
            ["第1段可见因果证明", "第2段可见因果证明"],
        )
        self.assertTrue(all(
            item.parameters["prompt"].count("任务类型：产品宣传片") == 1
            and item.parameters["prompt"].count("核心产品卖点：") == 1
            and item.parameters["prompt"].count("本片段卖点证明：") == 1
            for item in clips
        ))

    async def test_unavailable_and_unknown_workflows_fail_closed(self) -> None:
        views = {item["id"]: item for item in self.plugin.describe_workflows()}
        for workflow_id in ("open-montage", "ink-press-product-workflow"):
            if workflow_id in views:
                with self.assertRaises(BuildPlanValidationError):
                    await self._compile(workflow_id)
                self.assertFalse(views[workflow_id]["available"])
                self.assertFalse(views[workflow_id]["userSelectable"])
            else:
                with self.assertRaises(LookupError):
                    await self._compile(workflow_id)

    async def test_every_available_workflow_completes_with_provider_mock(self) -> None:
        runtime = VideoBuildRuntime(skill_runtime=self.skills)
        await runtime.plugins.load_directories([
            Path(__file__).resolve().parents[2] / "plugins",
        ])
        await load_workflow_skills(runtime.plugins, self.skills)
        executable_capabilities = {
            capability
            for loaded in runtime.plugins.loaded
            for capability in loaded.manifest.contributions.capabilities
        }

        async def validate(*, build_id, artifact):
            return [ValidationResult(
                project_id=artifact.project_id,
                build_id=build_id,
                artifact_version_id=artifact.id,
                validator_id="provider-mock",
                passed=True,
            )]

        runtime.validate_artifact = validate
        installed = set(self.plugin._workflows)
        workflow_specs = {"mv": _spec("mv", bgm_prompt="test song")}
        if "short-drama-workflow" in installed:
            workflow_specs["short-drama-workflow"] = _spec(
                "short-drama-workflow", segment_seconds=15,
            )
        if "seedance2" in installed:
            workflow_specs["seedance2"] = _spec("seedance2")
        for workflow_id in (
            "cuti-product-workflow",
            "cuti-scenario-product-workflow",
        ):
            if workflow_id not in installed:
                continue
            workflow_specs[workflow_id] = (
                _scenario_spec("source:product")
                if workflow_id == "cuti-scenario-product-workflow"
                else _spec(
                    workflow_id,
                    segment_seconds=15 if workflow_id == "cuti-product-workflow" else 5,
                    source_asset_ids=["source:product"],
                )
            )

        for index, (workflow_id, spec) in enumerate(workflow_specs.items(), start=1):
            project, version = await runtime.create_project(
                user_id="user-1", title=f"Mock {workflow_id}",
            )
            retained_source = await runtime.add_artifact(MediaArtifactVersion(
                artifact_id="source:retained",
                project_id=project.id,
                type="source_image",
                uri="https://provider-mock.test/retained.png",
            ))
            if spec.source_asset_ids:
                await runtime.add_artifact(MediaArtifactVersion(
                    artifact_id="source:product",
                    project_id=project.id,
                    type="source_image",
                    uri="https://provider-mock.test/product.png",
                ))
            project = await runtime.repo.get_project(project.id)
            plan = await runtime.plan_project(
                project_id=project.id,
                base_project_version_id=project.current_version_id,
                video_spec=spec,
                idempotency_key=f"mock-plan-{index}",
            )
            missing_handlers = sorted({
                item.capability for item in plan.items
                if (
                    item.action == "create"
                    and item.capability
                    and canonical_capability_id(item.capability) not in executable_capabilities
                )
            })
            self.assertEqual(
                missing_handlers, [],
                f"{workflow_id} compiled capabilities with no Runtime handler",
            )
            build = await runtime.start_build(
                project_id=project.id,
                plan_id=plan.id,
                base_project_version_id=project.current_version_id,
                idempotency_key=f"mock-build-{index}",
            )
            completed, committed = await runtime.execute_build(
                project_id=project.id,
                build_id=build.id,
                executor=ProviderMockExecutor(),
            )
            self.assertEqual(completed.status, "completed", workflow_id)
            self.assertIn(
                retained_source.artifact_id,
                committed.selections,
                f"{workflow_id} dropped an existing source artifact",
            )
