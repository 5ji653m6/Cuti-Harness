from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.video_runtime.api import router, set_runtime
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.skill_workflows import load_workflow_skills
from app.video_runtime.skills import VideoSkillRuntime
from app.video_runtime.staged_planning import WORKFLOW_PLANNING_CONTRACTS
from app.video_runtime.workflow_plans import (
    ORIGINAL_CUTI_WORKFLOW_CONTRACTS, WORKFLOW_ID_COMPILERS,
)


class RemovedProductWorkflowsTest(unittest.IsolatedAsyncioTestCase):
    async def test_removed_bundles_have_no_catalog_compiler_or_api_entry(self):
        skills = VideoSkillRuntime()
        runtime = VideoBuildRuntime(skill_runtime=skills)
        await load_workflow_skills(runtime.plugins, skills)
        set_runtime(runtime)
        app = FastAPI()
        app.include_router(router)
        root = Path(__file__).resolve().parents[2]
        removed = ("product-ad-video", "libtv-product-workflow")
        with TestClient(app) as client:
            response = client.get(
                "/api/video/workflows", headers={"X-Video-User-Id": "user-1"},
            )
            self.assertEqual(response.status_code, 200)
            visible = {item["id"] for item in response.json()["data"]}
            self.assertIn("cuti-product-workflow", visible)
            self.assertIn("cuti-scenario-product-workflow", visible)
            for name in removed:
                with self.subTest(workflow=name):
                    self.assertFalse((root / "skills" / "external" / name).exists())
                    self.assertFalse(skills.catalog.has(name))
                    self.assertNotIn(name, visible)
                    self.assertNotIn(name, WORKFLOW_ID_COMPILERS)
                    self.assertNotIn(name, ORIGINAL_CUTI_WORKFLOW_CONTRACTS)
                    self.assertNotIn(name, WORKFLOW_PLANNING_CONTRACTS)
                    with self.assertRaises(LookupError):
                        skills.catalog.load(name)
                    detail = client.get(
                        f"/api/video/workflows/{name}",
                        headers={"X-Video-User-Id": "user-1"},
                    )
                    self.assertEqual(detail.status_code, 404)
        skills.reload()
        self.assertTrue(all(not skills.catalog.has(name) for name in removed))
