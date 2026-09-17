from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.video_runtime.local_repository import LocalJsonVideoProjectRepository
from app.video_runtime.models import MediaArtifactVersion, PlanCheckpoint, RebuildPlan, RebuildPlanItem
from app.video_runtime.checkpoint_coordinator import CheckpointCoordinator
from app.video_runtime.deepseek_client import DeepSeekHarnessClient
from app.video_runtime.runtime import VideoBuildRuntime


class LocalJsonRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_project_build_binding_draft_and_idempotency_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "video-runtime-state.json"
            first_repo = LocalJsonVideoProjectRepository(state_path)
            first_runtime = VideoBuildRuntime(repository=first_repo)
            project, version = await first_runtime.create_project(
                user_id="user-1",
                title="Durable project",
                idempotency_key="create-1",
            )
            await first_runtime.bind_session(
                project_id=project.id,
                session_id="deepseek-session-1",
                user_id="user-1",
            )
            await first_repo.remember_compatibility_run(
                user_id="user-1",
                idempotency_key="compat-1",
                project_id=project.id,
                session_id="deepseek-session-1",
            )
            await first_repo.remember_operation_result(
                project.id, "upload", "upload-1", "source-version-1",
            )
            plan = await first_repo.save_plan(
                RebuildPlan(
                    project_id=project.id,
                    kind="initial",
                    base_project_version_id=version.id,
                    workflow_id="workflow-direct-video",
                    items=[RebuildPlanItem(
                        step_id="video",
                        action="create",
                        capability="atomic.video.generate",
                        output_artifact_id="video:final",
                        output_artifact_type="final_video",
                    )],
                ),
                "plan-1",
            )
            build = await first_repo.submit_build(
                project_id=project.id,
                plan_id=plan.id,
                base_version_id=version.id,
                idempotency_key="build-1",
                session_id="deepseek-session-1",
                user_id="user-1",
            )
            [step] = await first_repo.list_build_steps(project.id, build.id)
            step.status = "waiting_external"
            step.attempt = 1
            step.remote_provider = "wavespeed"
            step.remote_operation_id = "provider-job-1"
            await first_repo.update_build_step(step)
            draft = await first_repo.stage_artifact(MediaArtifactVersion(
                project_id=project.id,
                artifact_id="video:final",
                type="final_video",
                status="draft",
                uri="https://provider.test/video.mp4",
                metadata={"build_id": build.id},
            ))
            checkpoint = await first_repo.create_checkpoint(PlanCheckpoint(
                project_id=project.id, build_id=build.id, plan_id=plan.id,
                workflow_id=plan.workflow_id, session_id="deepseek-session-1", user_id="user-1",
                phase="reference", next_phase="video", base_plan_revision=1, base_spec_revision=1,
                artifact_version_ids=[draft.id],
                artifact_summaries=[{"id": draft.id, "status": "draft"}],
            ))
            await first_repo.close()

            second_repo = LocalJsonVideoProjectRepository(state_path)
            restored = await second_repo.get_project(project.id)
            self.assertEqual(restored.title, "Durable project")
            bound_project, binding = await second_repo.project_for_session(
                "deepseek-session-1", "user-1",
            )
            self.assertEqual(bound_project.id, project.id)
            self.assertEqual(binding.session_id, "deepseek-session-1")
            self.assertEqual(
                await second_repo.get_compatibility_run("user-1", "compat-1"),
                (project.id, "deepseek-session-1"),
            )
            self.assertEqual(
                await second_repo.get_operation_result(project.id, "upload", "upload-1"),
                "source-version-1",
            )
            restored_build = await second_repo.get_build(project.id, build.id)
            self.assertEqual(restored_build.status, "waiting_agent")
            restored_checkpoint = await second_repo.get_checkpoint(project.id, build.id, checkpoint.id)
            self.assertEqual(restored_checkpoint.session_id, binding.session_id)
            self.assertEqual(restored_checkpoint.artifact_version_ids, [draft.id])
            transport = AsyncMock(spec=DeepSeekHarnessClient)
            coordinator = CheckpointCoordinator(VideoBuildRuntime(repository=second_repo), transport)
            self.assertTrue(await coordinator.run_once())
            args = transport.prompt.call_args
            self.assertEqual(args.args[0], "deepseek-session-1")
            self.assertIn(draft.id, args.args[1])
            self.assertEqual(args.kwargs["mode"], "queue")
            [restored_step] = await second_repo.list_build_steps(project.id, build.id)
            self.assertEqual(restored_step.status, "waiting_external")
            self.assertEqual(restored_step.remote_operation_id, "provider-job-1")
            self.assertEqual(
                (await second_repo.get_artifact(project.id, draft.id)).status,
                "draft",
            )
            events = await second_repo.list_events(project.id)
            self.assertEqual(
                [item.sequence for item in events],
                list(range(1, len(events) + 1)),
            )

            duplicate_project, duplicate_version = await VideoBuildRuntime(
                repository=second_repo,
            ).create_project(
                user_id="user-1",
                title="Must not replace",
                idempotency_key="create-1",
            )
            self.assertEqual(duplicate_project.id, project.id)
            self.assertEqual(duplicate_version.id, version.id)

    async def test_corrupt_or_unknown_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "video-runtime-state.json"
            state_path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "state is unreadable"):
                LocalJsonVideoProjectRepository(state_path)
            state_path.write_text('{"schema_version":999}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unsupported.*schema"):
                LocalJsonVideoProjectRepository(state_path)


if __name__ == "__main__":
    unittest.main()
