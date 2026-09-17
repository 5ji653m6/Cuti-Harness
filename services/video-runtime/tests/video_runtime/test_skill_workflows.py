from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.video_runtime.api import router, set_runtime
from app.video_runtime.models import MediaArtifactVersion, VideoSpec
from app.video_runtime.plugins import PluginContext, VideoPluginRegistry
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.skill_workflows import load_workflow_skills
from app.video_runtime.skills import VideoSkillRuntime


def _video_spec(workflow_id: str) -> VideoSpec:
    return VideoSpec.model_validate({
        "title": "Workflow adapter",
        "target_duration_seconds": 10,
        "workflow_id": workflow_id,
        "workflow_parameters": {
            "scenes": [{
                "id": "main-location",
                "name": "Main location",
                "description": "A stable recurring interior with clear spatial geography",
            }],
        },
        "characters": [{
            "id": "hero",
            "name": "Hero",
            "appearance": "black hair",
        }],
        "shots": [
            {
                "id": "1",
                "order": 1,
                "duration_seconds": 5,
                "beat": "arrives",
                "visual_prompt": "0-5秒，主角进入画面并完成一次清晰动作。",
                "character_ids": ["hero"],
            },
            {
                "id": "2",
                "order": 2,
                "duration_seconds": 5,
                "beat": "leaves",
                "visual_prompt": "0-5秒，主角离开画面，动作完整收束。",
                "character_ids": ["hero"],
            },
        ],
    })


async def _add_product_source(
    runtime: VideoBuildRuntime,
    project_id: str,
) -> MediaArtifactVersion:
    return await runtime.add_artifact(MediaArtifactVersion(
        artifact_id=f"{project_id}:source:product",
        project_id=project_id,
        type="source_image",
        uri="https://example.test/product.png",
        title="Product source image",
        provenance={"source": "test_upload"},
    ))


class SkillWorkflowPluginTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_installed_workflows_declare_staged_or_agentic_planning(self):
        plugins = VideoPluginRegistry()
        skills = VideoSkillRuntime()
        await load_workflow_skills(plugins, skills)
        workflow_plugin = plugins.get("cuti.skill-workflows")
        workflows = workflow_plugin.implementation._workflows
        self.assertEqual(
            set(workflows),
            {
                "cinematic",
                "cuti-product-workflow",
                "cuti-scenario-product-workflow",
                "mv",
                "seedance2",
                "short-drama-workflow",
            },
        )
        self.assertTrue(all(
            workflow.planning.mode in {"staged", "agentic"}
            for workflow in workflows.values()
        ))
        self.assertEqual(workflows["seedance2"].planning.mode, "agentic")


    async def test_seedance2_does_not_inherit_generic_cuti_director_skills(self):
        skills = VideoSkillRuntime()
        if not skills.catalog.has("seedance2"):
            self.skipTest("seedance2 Skill is not installed in this checkout")
        runtime = VideoBuildRuntime(skill_runtime=skills)
        await runtime.plugins.load_directories([
            Path(__file__).resolve().parents[2] / "plugins",
        ])
        await load_workflow_skills(runtime.plugins, skills)
        project, version = await runtime.create_project(
            user_id="user-1",
            title="Original Seedance workflow",
        )

        plan = await runtime.plan_project(
            project_id=project.id,
            base_project_version_id=version.id,
            video_spec=_video_spec("seedance2"),
            idempotency_key="seedance2-plan",
        )

        clips = [
            item for item in plan.items
            if item.capability == "atomic.video.generate"
        ]
        self.assertTrue(clips)
        self.assertTrue(all(not item.resolved_skills for item in clips))
        self.assertTrue(all(item.skill_context is None for item in clips))

    async def test_missing_skill_dependency_and_unknown_capability_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing-dependency"
            missing.mkdir()
            (missing / "SKILL.md").write_text("""---
name: missing-dependency
description: missing dependency
metadata:
  kind: workflow
  workflow:
    mode: test
    pipeline: [atomic.video.generate]
    allowed_capabilities: [atomic.video.generate]
    dependencies:
      skills: [not-installed]
---
instructions
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires missing Skills"):
                VideoSkillRuntime([root])

            (missing / "SKILL.md").unlink()
            missing.rmdir()
            unknown = root / "unknown-capability"
            unknown.mkdir()
            (unknown / "SKILL.md").write_text("""---
name: unknown-capability
description: unknown capability
metadata:
  kind: workflow
  workflow:
    mode: test
    pipeline: [unsafe.unknown]
    allowed_capabilities: [unsafe.unknown]
---
instructions
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown capability"):
                VideoSkillRuntime([root])

    async def test_project_skill_lock_is_runtime_owned_and_frozen_into_steps(self):
        skills = VideoSkillRuntime()
        if not skills.catalog.has("cuti-product-workflow"):
            self.skipTest("cuti-product-workflow Skill is not installed in this checkout")
        runtime = VideoBuildRuntime(skill_runtime=skills)
        await runtime.plugins.load_directories([
            Path(__file__).resolve().parents[2] / "plugins",
        ])
        await load_workflow_skills(runtime.plugins, skills)
        project, version = await runtime.create_project(
            user_id="user-1",
            title="Locked direction",
        )
        source = await _add_product_source(runtime, project.id)
        lock = await runtime.set_project_skill_enabled(
            project_id=project.id,
            skill_id="product-voiceover-narration",
            enabled=True,
        )
        self.assertEqual(lock.project_id, project.id)
        self.assertTrue(lock.digest)

        plan = await runtime.plan_project(
            project_id=project.id,
            base_project_version_id=(await runtime.repo.get_project(project.id)).current_version_id,
            video_spec=_video_spec("cuti-product-workflow").model_copy(
                update={
                    "source_asset_ids": [source.artifact_id],
                    "target_duration_seconds": 30,
                    "shots": [shot.model_copy(update={
                        "duration_seconds": 15,
                        "visual_prompt": "0-15秒，产品保持外观一致，镜头完整展示产品。",
                    }) for shot in _video_spec("cuti-product-workflow").shots],
                    "workflow_parameters": {"narration_mode": "music_only"},
                },
            ),
            idempotency_key="locked-skill-plan",
        )
        persisted = await runtime.list_project_skill_locks(project.id)
        self.assertEqual(
            {item.skill_id for item in persisted},
            {"product-voiceover-narration", "cuti-product-workflow"},
        )
        brief_step = next(item for item in plan.items if item.step_id == "commercial-strategy")
        resolved = {item.skill_id: item for item in brief_step.resolved_skills}
        self.assertEqual(resolved["product-voiceover-narration"].source, "project_lock")

        switched = await runtime.plan_project(
            project_id=project.id,
            base_project_version_id=(await runtime.repo.get_project(project.id)).current_version_id,
            video_spec=_video_spec("seedance2"),
            idempotency_key="explicit-workflow-switch",
        )
        self.assertEqual(switched.workflow_id, "seedance2")
        locks = {item.skill_id: item.enabled for item in await runtime.list_project_skill_locks(project.id)}
        self.assertFalse(locks["cuti-product-workflow"])
        self.assertTrue(locks["seedance2"])


class SkillWorkflowApiTest(unittest.TestCase):
    def test_workflow_api_exposes_skill_metadata(self):
        plugins = VideoPluginRegistry()
        skills = VideoSkillRuntime()
        asyncio.run(load_workflow_skills(plugins, skills))
        set_runtime(VideoBuildRuntime(plugins=plugins, skill_runtime=skills))
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.get(
                "/api/video/workflows",
                headers={"X-Video-User-Id": "user-1"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        workflows = {item["id"]: item for item in response.json()["data"]}
        self.assertIn("mv", workflows)
        self.assertEqual(workflows["mv"]["mode"], "mv")
        self.assertTrue(workflows["mv"]["available"])
        self.assertNotIn("workflow-short-drama", workflows)
        self.assertNotIn("workflow-keyframe-pipeline", workflows)
        self.assertNotIn("open-montage", workflows)
        if not skills.catalog.has("seedance2"):
            return
        with TestClient(app) as client:
            detail = client.get(
                "/api/video/workflows/seedance2",
                headers={"X-Video-User-Id": "user-1"},
            ).json()["data"]
        self.assertIn("你不是模板填充器", detail["instructions"])
        self.assertEqual(detail["resourceOwnerSkillId"], "seedance2")
        resources = {item["path"]: item["content"] for item in detail["resourceContents"]}
        self.assertIn("reference.md", resources)

        catalog = {item["name"]: item for item in skills.prompt_view()}
        self.assertEqual(catalog["seedance2"]["kind"], "workflow")
        with TestClient(app) as client:
            shotcraft = client.get(
                "/api/video/skills/video-shotcraft",
                headers={"X-Video-User-Id": "user-1"},
            )
            keyframe = client.get(
                "/api/video/workflows/workflow-keyframe-pipeline",
                headers={"X-Video-User-Id": "user-1"},
            )
        self.assertEqual(shotcraft.status_code, 404, shotcraft.text)
        self.assertEqual(keyframe.status_code, 404, keyframe.text)

    def test_complete_catalog_has_no_implicit_plugin_compiler(self):
        runtime = VideoBuildRuntime()
        asyncio.run(runtime.plugins.load_directories([
            Path(__file__).resolve().parents[2] / "plugins",
        ]))
        asyncio.run(load_workflow_skills(runtime.plugins, runtime.skills))
        set_runtime(runtime)
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.get(
                "/api/video/workflows",
                headers={"X-Video-User-Id": "user-1"},
            )
            music_detail = client.get(
                "/api/video/workflows/cuti.music-video",
                headers={"X-Video-User-Id": "user-1"},
            )
            lipsync_detail = client.get(
                "/api/video/workflows/cuti.lipsync-music-video",
                headers={"X-Video-User-Id": "user-1"},
            )
            seedance_story = client.get(
                "/api/video/workflows/cuti.seedance-story",
                headers={"X-Video-User-Id": "user-1"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(music_detail.status_code, 404, music_detail.text)
        self.assertEqual(lipsync_detail.status_code, 404, lipsync_detail.text)
        self.assertEqual(seedance_story.status_code, 404, seedance_story.text)
        workflows = {item["id"]: item for item in response.json()["data"]}
        self.assertFalse([
            item["id"] for item in workflows.values()
            if item["executionKind"] == "plugin"
        ])
        for item in workflows.values():
            if item["available"] and item["userSelectable"]:
                self.assertIn(
                    item["executionKind"],
                    {"dedicated_compiler", "dedicated_plugin_compiler"},
                    item["id"],
                )
