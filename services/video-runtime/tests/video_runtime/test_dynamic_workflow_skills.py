from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.v2.skill_install import extract_skill_archive, install_skill_directory
from app.video_runtime.api import _workflow_views, get_workflow, get_runtime, router
from app.video_runtime.deepseek_bff import _validate_workflow_selection
from app.video_runtime.models import CheckpointResolution, ProjectIntent, RebuildPlanItem
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.skills import VideoSkillRuntime
from app.video_runtime.skill_workflows import reload_workflow_skills
from app.video_runtime.workflow_plans import workflow_execution_kind
from test_initial_build import FakePlanExecutor


class DynamicWorkflowSkillTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.skills = VideoSkillRuntime([root / "external"])
        self.runtime = VideoBuildRuntime(
            skill_runtime=self.skills, staged_planning_enabled=True,
            continuous_plan_patch_enabled=True,
        )
        archive = io.BytesIO()
        fixture = Path(__file__).parents[1] / "fixtures/dynamic-workflow/SKILL.md"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("independent-story-workflow/SKILL.md", fixture.read_bytes())
        source = extract_skill_archive(archive.getvalue(), root / "upload")
        self.name = install_skill_directory(
            source, root / "external", catalog=self.skills.catalog,
            registry=self.skills.capabilities,
        )
        await reload_workflow_skills(self.runtime.plugins, self.skills)

    async def asyncTearDown(self):
        await self.runtime.close()
        self.temp.cleanup()

    async def test_zip_catalog_load_patch_execute_and_complete_document(self):
        view = next(item for item in _workflow_views(self.runtime) if item["id"] == self.name)
        self.assertEqual((view["available"], view["executionKind"], view["compiler"]),
                         (True, "agent_plan_patch", None))
        self.assertTrue(self.skills.prompt_view()[0]["available"])
        _validate_workflow_selection(self.runtime, self.name)
        loaded = await get_workflow(self.name, ("u", "s"), self.runtime)
        self.assertIn("opening, turning point, and ending", loaded["data"]["instructions"])
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_runtime] = lambda: self.runtime
        with TestClient(app) as client:
            response = client.get("/api/video/workflows/" + self.name)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"], loaded["data"])
        project, version = await self.runtime.create_project(user_id="u", title="Story")
        await self.runtime.bind_session(project_id=project.id, session_id="s", user_id="u")
        plan = await self.runtime.plan_project(
            project_id=project.id, base_project_version_id=version.id,
            project_intent=ProjectIntent(title="Story", brief="A quiet journey", workflow_id=self.name),
            idempotency_key="plan",
        )
        self.assertEqual([step.step_id for step in plan.items], ["intent"])
        build = await self.runtime.start_build(
            project_id=project.id, plan_id=plan.id, base_project_version_id=version.id,
            idempotency_key="build", session_id="s", user_id="u",
        )
        executor = FakePlanExecutor()

        async def execute():
            return await self.runtime.execute_build(project_id=project.id, build_id=build.id, executor=executor)

        async def resolve(key, **kwargs):
            checkpoints = await self.runtime.repo.list_build_checkpoints(project.id, build.id)
            checkpoint = next(item for item in reversed(checkpoints) if item.status in {"pending", "planning"})
            return await self.runtime.resolve_checkpoint(
                project_id=project.id, build_id=build.id, checkpoint_id=checkpoint.id,
                session_id="s", user_id="u",
                resolution=CheckpointResolution(
                    base_plan_revision=checkpoint.base_plan_revision,
                    base_spec_revision=checkpoint.base_spec_revision,
                    idempotency_key=key, video_spec_patch={}, **kwargs,
                ),
            )

        await execute()
        with self.assertRaisesRegex(ValueError, "completed script"):
            await resolve("premature", goal_satisfied=True)
        with self.assertRaisesRegex(ValueError, "not allow capability"):
            await resolve("forbidden", proposed_steps=[RebuildPlanItem(
                step_id="forbidden", action="create", capability="atomic.video.generate",
                output_artifact_type="video", parameters={"prompt": "A quiet journey"},
            )])
        await resolve("story", proposed_steps=[RebuildPlanItem(
            step_id="story", action="create", capability="atomic.text.generate",
            output_artifact_type="script", parameters={"prompt": "Opening, turning point, ending"},
            depends_on=["intent"],
        )])
        await execute()
        await resolve("finish", goal_satisfied=True)
        await execute()
        saved = await self.runtime.repo.get_build(project.id, build.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(executor.calls, ["intent", "story"])
        self.assertTrue(any(item.type == "script" for item in await self.runtime.repo.current_artifacts(project.id)))

    async def test_missing_allowlist_or_unsupported_planning_never_inherits_a_compiler(self):
        spec = self.skills.workflows.get(self.name)
        for candidate in (
            replace(spec, allowed_capabilities=None),
            replace(spec, planning=replace(spec.planning, mode="full")),
        ):
            with self.assertRaises(ValueError):
                workflow_execution_kind(candidate)

    async def test_disabled_continuous_execution_is_unavailable_in_catalog_and_bff(self):
        self.runtime.continuous_plan_patch_enabled = False
        self.assertFalse(_workflow_views(self.runtime)[0]["available"])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _validate_workflow_selection(self.runtime, self.name)
