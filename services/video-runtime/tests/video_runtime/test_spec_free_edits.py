"""Editing persisted production output does not require a monolithic VideoSpec."""
import unittest

from app.video_runtime.models import CheckpointResolution, MediaArtifactVersion, MediaEditOperation, ProjectIntent, RebuildPlanItem
from app.video_runtime.repository import ProjectVersionConflict
from test_initial_build import FakePlanExecutor, video_runtime


class SpecFreeEditsTest(unittest.IsolatedAsyncioTestCase):
    async def test_edit_failure_can_change_parameters_in_same_session_and_commit(self):
        runtime = await video_runtime()
        self.addAsyncCleanup(runtime.close)
        runtime.staged_planning_enabled = True
        runtime.continuous_plan_patch_enabled = True
        project, _ = await runtime.create_project(user_id="user", title="Existing film")
        await runtime.bind_session(project_id=project.id, session_id="edit-session", user_id="user")
        old = await runtime.repo.add_artifact(MediaArtifactVersion(
            project_id=project.id, artifact_id="clip", type="video", uri="http://127.0.0.1/old.mp4",
        ))
        untouched = await runtime.repo.add_artifact(MediaArtifactVersion(
            project_id=project.id, artifact_id="other", type="video", uri="https://media.test/other.mp4",
        ))
        project = await runtime.repo.get_project(project.id)
        args = dict(project_id=project.id, base_project_version_id=project.current_version_id,
                    edits=[{"type": "regenerate_artifact", "artifactVersionId": old.id,
                            "patch": {"prompt": "faster hard cuts"}}], idempotency_key="edit")
        plan = await runtime.preview_edits(**args)
        self.assertEqual(plan.id, (await runtime.preview_edits(**args)).id)
        self.assertTrue(runtime._is_continuous_plan(plan))
        self.assertEqual(plan.project_intent.constraints["edits"], args["edits"])
        self.assertFalse(any(item.capability == "atomic.video.generate" for item in plan.items))
        build = await runtime.apply_rebuild(project_id=project.id, plan_id=plan.id,
            base_project_version_id=project.current_version_id, idempotency_key="build",
            session_id="edit-session", user_id="user")

        class Provider(FakePlanExecutor):
            attempts = []
            async def execute_plan_step(self, **kwargs):
                step = kwargs["step"]
                if step.capability == "atomic.video.generate":
                    self.attempts.append(dict(step.parameters))
                    if step.parameters["prompt"] == "bad input":
                        raise ValueError("400 Invalid reference videos URL")
                return await super().execute_plan_step(**kwargs)

        executor = Provider()
        async def run():
            return await runtime.execute_build(project_id=project.id, build_id=build.id, executor=executor)
        async def checkpoint():
            cp = next(item for item in reversed(await runtime.repo.list_build_checkpoints(project.id, build.id))
                      if item.status in {"pending", "planning"})
            return await runtime.inspect_checkpoint(project_id=project.id, build_id=build.id,
                checkpoint_id=cp.id, session_id="edit-session", user_id="user")
        async def patch(**kwargs):
            cp = await checkpoint()
            return await runtime.resolve_checkpoint(project_id=project.id, build_id=build.id,
                checkpoint_id=cp.id, session_id="edit-session", user_id="user",
                resolution=CheckpointResolution(base_plan_revision=cp.base_plan_revision,
                    base_spec_revision=cp.base_spec_revision, idempotency_key=cp.id, video_spec_patch={}, **kwargs))

        await run()
        self.assertIn("faster hard cuts", (await checkpoint()).planner_instruction)
        with self.assertRaisesRegex(ValueError, "goal_satisfied requires"):
            await patch(goal_satisfied=True)
        task = RebuildPlanItem(step_id="edit-clip", action="create", output_artifact_id="clip",
            output_artifact_type="video", capability="atomic.video.generate",
            parameters={"prompt": "bad input", "model": "seedance-2.5"})
        await patch(proposed_steps=[task])
        await run()
        cp = await checkpoint()
        self.assertEqual(cp.session_id, "edit-session")
        self.assertIn("Invalid reference videos URL", cp.planner_instruction)
        self.assertEqual(len(executor.attempts), 1)
        self.assertEqual((await runtime.repo.get_project(project.id)).current_version_id, project.current_version_id)
        repaired = task.model_copy(deep=True)
        repaired.step_id = "edit-clip-repair"
        repaired.parameters["prompt"] = "faster hard cuts"
        await patch(proposed_steps=[repaired], replace_failed_step_ids={"edit-clip": "edit-clip-repair"})
        await run()
        await patch(goal_satisfied=True)
        result, version = await run()
        self.assertEqual(result.status, "completed")
        self.assertNotEqual(version.selections["clip"], old.id)
        self.assertEqual(version.selections["other"], untouched.id)
        self.assertEqual(len(executor.attempts), 2)
        self.assertNotIn("reference_videos", executor.attempts[-1])

    async def test_postproduction_and_dependency_preview_use_dynamic_loop_without_workflow(self):
        runtime = await video_runtime()
        self.addAsyncCleanup(runtime.close)
        runtime.staged_planning_enabled = True
        runtime.continuous_plan_patch_enabled = True
        project, _ = await runtime.create_project(user_id="user", title="Imported clip")
        clip = await runtime.repo.add_artifact(MediaArtifactVersion(
            project_id=project.id, artifact_id="clip", type="video", uri="https://media.test/clip.mp4",
        ))
        project = await runtime.repo.get_project(project.id)
        operation = MediaEditOperation.model_validate({
            "step_id": "concat", "capability": "media.concat",
            "inputs": [{"role": "videos", "artifact_version_id": clip.id}],
            "parameters": {"normalize": True},
        })
        plan = await runtime.preview_plan_patch(project_id=project.id,
            base_project_version_id=project.current_version_id, operations=[operation],
            description="Assemble selected media", idempotency_key="media")
        self.assertTrue(runtime._is_continuous_plan(plan))
        self.assertEqual(plan.workflow_id, "")
        self.assertEqual(plan.project_intent.constraints["edits"][0]["capability"], "media.concat")
        impact = await runtime.preview_change(project_id=project.id,
            description="Change this clip", target_artifact_version_ids=[clip.id], idempotency_key="impact")
        self.assertTrue(runtime._is_continuous_plan(impact))
        self.assertEqual(impact.project_intent.constraints["target_artifact_version_ids"], [clip.id])

    async def test_followup_intent_retains_selected_generated_media(self):
        runtime = await video_runtime()
        runtime.staged_planning_enabled = True
        runtime.continuous_plan_patch_enabled = True
        project, _ = await runtime.create_project(user_id="user", title="Existing film")
        clip = await runtime.repo.add_artifact(MediaArtifactVersion(
            project_id=project.id, artifact_id="clip", type="video", uri="https://media.test/clip",
        ))
        project = await runtime.repo.get_project(project.id)
        plan = await runtime.plan_project(project_id=project.id,
            base_project_version_id=project.current_version_id, idempotency_key="followup",
            project_intent=ProjectIntent(title="Edit film", brief="Add another scene", workflow_id="seedance2"))
        self.assertEqual([item.artifact_version_id for item in plan.items if item.action == "reuse"], [clip.id])
        self.assertEqual(plan.next_checkpoint.planning_mode, "agentic")

    async def test_parameter_patch_rebuilds_descendants_and_preserves_other_media(self):
        runtime = await video_runtime()
        project, _ = await runtime.create_project(user_id="user", title="Dynamic film")
        outputs = []
        for name, capability, params in [
            ("reference", "atomic.image.generate", {"prompt": "character"}),
            ("clip", "atomic.video.generate", {"prompt": "original detailed prompt", "duration": 15, "generation_mode": "i2v"}),
            ("final", "media.concat", {"video_steps": ["clip"]}),
        ]:
            outputs.append(await runtime.repo.add_artifact(MediaArtifactVersion(
                project_id=project.id, artifact_id=name, type="image" if name == "reference" else "video",
                uri=f"https://media.test/{name}",
                metadata={"plan_step_id": name, "rebuild_capability": capability, "generation_parameters": params},
            )))
        # Public watermark versions may retain recipes but omit graph edges.
        # The final's saved video_steps must still invalidate it when clip changes.
        project = await runtime.repo.get_project(project.id)
        plan = await runtime.preview_edits(
            project_id=project.id, base_project_version_id=project.current_version_id,
            edits=[{"type": "regenerate_artifact", "artifactVersionId": outputs[1].id,
                    "patch": {"generation_mode": "reference", "start_image_url": None}}],
            idempotency_key="edit",
        )
        clip = next(item for item in plan.items if item.step_id == "clip")
        self.assertEqual(clip.parameters["prompt"], "original detailed prompt")
        self.assertEqual(clip.parameters["generation_mode"], "reference")
        self.assertEqual(set(plan.ids_for("rebuild")), {outputs[1].id, outputs[2].id})
        build = await runtime.start_build(project_id=project.id, plan_id=plan.id,
            base_project_version_id=project.current_version_id, idempotency_key="build")
        result, version = await runtime.execute_build(project_id=project.id, build_id=build.id, executor=FakePlanExecutor())
        self.assertEqual(result.status, "completed")
        self.assertEqual(version.selections["reference"], outputs[0].id)
        self.assertNotEqual(version.selections["clip"], outputs[1].id)
        with self.assertRaises(ProjectVersionConflict):
            await runtime.preview_edits(project_id=project.id, base_project_version_id=project.current_version_id,
                edits=[{"type": "regenerate_artifact", "artifactVersionId": outputs[1].id}])
