from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.video_runtime.api import _logical_artifact_id, router, set_runtime
from app.video_runtime.models import MediaArtifactVersion
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.skill_workflows import load_workflow_skills
from app.video_runtime.upload_security import sign_uploaded_file


class VideoRuntimeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = VideoBuildRuntime()
        asyncio.run(self.runtime.plugins.load_directories([
            Path(__file__).resolve().parents[2] / "plugins",
        ]))
        asyncio.run(load_workflow_skills(self.runtime.plugins, self.runtime.skills))
        set_runtime(self.runtime)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.headers = {
            "X-Video-User-Id": "user-1",
            "X-Video-Session-Id": "session-1",
        }

    def tearDown(self) -> None:
        self.client.close()

    def test_legacy_assembled_video_projects_to_stable_final_video_id(self) -> None:
        artifact = SimpleNamespace(
            artifact_id="project-1:assembled-video",
            metadata={},
        )
        self.assertEqual(_logical_artifact_id("project-1", artifact), "video:final")

    def test_receipt_verified_source_can_be_attached_idempotently(self) -> None:
        project = self.client.post(
            "/api/video/projects",
            headers=self.headers,
            json={"title": "Recovered", "sessionId": "session-1"},
        ).json()["data"]
        project_id = project["projectId"]
        uri = "http://127.0.0.1:8001/files/images/product.webp"
        body = {
            "mediaType": "image",
            "uri": uri,
            "title": "product.webp",
            "artifactId": "source:product",
            "uploadReceipt": sign_uploaded_file("user-1", "image", uri),
        }
        first = self.client.post(
            f"/api/video/projects/{project_id}/sources",
            headers=self.headers,
            json=body,
        )
        repeated = self.client.post(
            f"/api/video/projects/{project_id}/sources",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json()["data"]["id"], repeated.json()["data"]["id"])
        denied = self.client.post(
            f"/api/video/projects/{project_id}/sources",
            headers=self.headers,
            json={**body, "uploadReceipt": "forged"},
        )
        self.assertEqual(denied.status_code, 422)

    def test_dynamic_media_patch_api_is_workflow_independent(self) -> None:
        project = self.client.post(
            "/api/video/projects",
            headers=self.headers,
            json={"title": "Caption later", "sessionId": "session-1"},
        ).json()["data"]
        video = asyncio.run(self.runtime.repo.add_artifact(MediaArtifactVersion(
            artifact_id=f"{project['projectId']}:final-video",
            project_id=project["projectId"],
            type="final_video",
            uri="https://media.test/final.mp4",
            title="Final video",
            metadata={"plan_step_id": "final-video"},
        )))
        project = self.client.get(
            f"/api/video/projects/{project['projectId']}", headers=self.headers,
        ).json()["data"]

        artifacts = self.client.get(
            f"/api/video/projects/{project['projectId']}/artifacts",
            headers=self.headers,
        )
        self.assertEqual(artifacts.status_code, 200)
        self.assertEqual(artifacts.json()["data"][0]["artifactVersionId"], video.id)
        self.assertNotIn("uri", artifacts.json()["data"][0])

        capabilities = self.client.get(
            "/api/video/plan-patch-capabilities", headers=self.headers,
        )
        self.assertEqual(capabilities.status_code, 200)
        capability_ids = {item["id"] for item in capabilities.json()["data"]}
        self.assertTrue({
            "media.transcribe", "subtitle.compose", "media.subtitle_burn",
            "media.audio_analyze", "media.video_analyze", "media.audio_cut", "media.mix_audio",
            "atomic.image.generate", "suno.generate",
        } <= capability_ids)
        self.assertNotIn("media.audio.trim", capability_ids)
        self.assertNotIn("media.audio.analyze", capability_ids)
        self.assertNotIn("media.audio_trim", capability_ids)
        cut = next(item for item in capabilities.json()["data"] if item["id"] == "media.audio_cut")
        self.assertIn("parameters_schema", cut)
        self.assertIn("segments", cut["parameters_schema"].get("properties", {}))
        self.assertTrue(cut["workflow_free_available"])
        self.assertTrue(cut["workflow_free_inputs"])
        generate = next(item for item in capabilities.json()["data"] if item["id"] == "api.provider.generate")
        self.assertTrue(generate["workflow_free_available"])
        self.assertEqual(generate["workflow_free_inputs"][0]["role"], "images")

        preview = self.client.post(
            f"/api/video/projects/{project['projectId']}/plan-patches/preview",
            headers=self.headers,
            json={
                "baseProjectVersionId": project["currentVersionId"],
                "idempotencyKey": "caption-preview",
                "description": "add captions",
                "operations": [
                    {
                        "step_id": "transcribe", "capability": "media.transcribe",
                        "inputs": [{"role": "video", "artifact_version_id": video.id}],
                    },
                    {
                        "step_id": "captions", "capability": "subtitle.compose",
                        "inputs": [{"role": "transcript", "operation_step_id": "transcribe"}],
                    },
                    {
                        "step_id": "burn", "capability": "media.subtitle_burn",
                        "inputs": [
                            {"role": "video", "artifact_version_id": video.id},
                            {"role": "subtitle", "operation_step_id": "captions"},
                        ],
                    },
                ],
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        data = preview.json()["data"]
        self.assertEqual(data["workflowId"], "")
        self.assertEqual(
            [item["capability"] for item in data["steps"] if item["capability"]],
            ["media.transcribe", "subtitle.compose", "media.subtitle_burn"],
        )

    def test_project_binding_preview_idempotency_and_conflict(self) -> None:
        response = self.client.post(
            "/api/video/projects",
            headers={**self.headers, "Idempotency-Key": "create-film"},
            json={"title": "Film"},
        )
        self.assertEqual(response.status_code, 200)
        project = response.json()["data"]
        project_id = project["projectId"]
        repeated_project = self.client.post(
            "/api/video/projects",
            headers={**self.headers, "Idempotency-Key": "create-film"},
            json={"title": "Film"},
        ).json()["data"]
        self.assertEqual(repeated_project["projectId"], project_id)
        artifact = asyncio.run(self.runtime.add_artifact(MediaArtifactVersion(
            project_id=project_id,
            type="character",
            title="Hero",
        )))

        first_get = self.client.get(f"/api/video/projects/{project_id}", headers=self.headers)
        second_get = self.client.get(f"/api/video/projects/{project_id}", headers=self.headers)
        self.assertEqual(first_get.status_code, 200)
        self.assertEqual(second_get.status_code, 200)
        self.assertEqual(
            self.client.get(
                f"/api/video/projects/{project_id}",
                headers={"X-Video-User-Id": "user-2"},
            ).status_code,
            403,
        )

        # In the local single-user profile the BFF-created Session binding is
        # authoritative for Agent tool calls, even if a stale tool process has
        # a different development default user id. An unrelated Session must
        # still be rejected.
        recovered = self.client.post(
            f"/api/video/projects/{project_id}/edits/resolve",
            headers={
                "X-Video-User-Id": "stale-tool-user",
                "X-Video-Session-Id": "session-1",
            },
            json={
                "baseProjectVersionId": project["currentVersionId"],
                "idempotencyKey": "recover-bound-session",
                "edits": [{"op": "patch_shot"}],
            },
        )
        self.assertEqual(recovered.status_code, 200)
        recovered_project = self.client.get(
            f"/api/video/projects/{project_id}",
            headers={
                "X-Video-User-Id": "stale-tool-user",
                "X-Video-Session-Id": "session-1",
            },
        )
        self.assertEqual(recovered_project.status_code, 200)
        recovered_workspace = self.client.get(
            f"/api/video/projects/{project_id}/workspace",
            headers={
                "X-Video-User-Id": "stale-tool-user",
                "X-Video-Session-Id": "session-1",
            },
        )
        self.assertEqual(recovered_workspace.status_code, 200)
        unrelated = self.client.post(
            f"/api/video/projects/{project_id}/edits/resolve",
            headers={
                "X-Video-User-Id": "stale-tool-user",
                "X-Video-Session-Id": "unbound-session",
            },
            json={
                "baseProjectVersionId": project["currentVersionId"],
                "idempotencyKey": "reject-unbound-session",
                "edits": [{"op": "patch_shot"}],
            },
        )
        self.assertEqual(unrelated.status_code, 403)

        preview_response = self.client.post(
            f"/api/video/projects/{project_id}/changes/preview",
            headers={**self.headers, "Idempotency-Key": "preview-coat"},
            json={"change": "new coat", "targetArtifactVersionIds": [artifact.id]},
        )
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.json()["data"]
        repeated_preview = self.client.post(
            f"/api/video/projects/{project_id}/changes/preview",
            headers={**self.headers, "Idempotency-Key": "preview-coat"},
            json={"change": "new coat", "targetArtifactVersionIds": [artifact.id]},
        ).json()["data"]
        self.assertEqual(repeated_preview["planId"], preview["planId"])
        rebuild_body = {
            "planId": preview["planId"],
            "baseProjectVersionId": preview["baseProjectVersionId"],
            "idempotencyKey": "same-build",
        }
        first = self.client.post(
            f"/api/video/projects/{project_id}/rebuilds",
            headers=self.headers,
            json=rebuild_body,
        )
        second = self.client.post(
            f"/api/video/projects/{project_id}/rebuilds",
            headers=self.headers,
            json=rebuild_body,
        )
        self.assertEqual(first.json()["data"]["buildId"], second.json()["data"]["buildId"])

        stale = self.client.post(
            f"/api/video/projects/{project_id}/rebuilds",
            headers=self.headers,
            json={**rebuild_body, "baseProjectVersionId": "stale", "idempotencyKey": "stale"},
        )
        self.assertEqual(stale.status_code, 409)

        events = self.client.get(
            f"/api/video/projects/{project_id}/events",
            headers=self.headers,
        ).json()["data"]
        self.assertEqual(
            sum(event["type"] == "project.session_bound" for event in events),
            1,
        )

    def test_event_tail_skips_historical_project_events(self) -> None:
        project = self.client.post(
            "/api/video/projects",
            headers=self.headers,
            json={"title": "Tail", "sessionId": "session-1"},
        ).json()["data"]
        project_id = project["projectId"]
        history = self.client.get(
            f"/api/video/projects/{project_id}/events",
            headers=self.headers,
        ).json()["data"]
        self.assertGreater(len(history), 0)
        tailed = self.client.get(
            f"/api/video/projects/{project_id}/events?tail=1",
            headers=self.headers,
        ).json()["data"]
        self.assertEqual(tailed, [])

    def test_workspace_returns_current_view_without_history_bodies(self) -> None:
        project = self.client.post(
            "/api/video/projects",
            headers=self.headers,
            json={"title": "Slim", "sessionId": "session-1"},
        ).json()["data"]
        project_id = project["projectId"]
        asyncio.run(self.runtime.add_artifact(MediaArtifactVersion(
            project_id=project_id,
            type="project_intent",
            title="Intent",
            metadata={"content": {"brief": "x" * 200, "title": "Slim"}, "build_id": "b1"},
        )))
        orphan = MediaArtifactVersion(
            project_id=project_id,
            type="image",
            title="Rain night still",
            uri="https://cdn.test/frame.webp",
        )
        fat = MediaArtifactVersion(
            project_id=project_id,
            type="video_clip",
            title="clip",
            uri="https://cdn.test/clip.mp4",
            metadata={
                "build_id": "b2",
                "video_url": "https://cdn.test/clip.mp4",
                "skill_context": {"brief": "SKILL_CONTEXT_BLOB" * 200, "plan": "y" * 5000},
                "raw": {"provider": "x" * 8000},
                "generation_parameters": {
                    "prompt": "rain girl on the platform",
                    "seed": 7,
                    "internal_trace": "z" * 4000,
                },
            },
        )
        script = MediaArtifactVersion(
            project_id=project_id,
            type="script",
            title="导演方案",
            metadata={"content": "夜雨站台，五秒动漫MV。", "skill_context": {"unused": True}},
        )
        self.runtime.repo.artifacts[project_id][orphan.id] = orphan
        self.runtime.repo.artifacts[project_id][fat.id] = fat
        self.runtime.repo.artifacts[project_id][script.id] = script
        workspace = self.client.get(
            f"/api/video/projects/{project_id}/workspace",
            headers=self.headers,
        )
        self.assertEqual(workspace.status_code, 200)
        data = workspace.json()["data"]
        self.assertEqual(data["artifactGroups"], {})
        self.assertEqual(data["artifactEdges"], [])
        self.assertEqual(data["videoSpecRevisions"], [])
        self.assertEqual(data["planRevisions"], [])
        self.assertEqual(data["projectVersions"], [])
        self.assertGreaterEqual(data["projectVersionCount"], 1)
        self.assertLessEqual(len(data["builds"]), 1)
        intent = next(item for item in data["artifacts"] if item["type"] == "project_intent")
        self.assertEqual(intent["metadata"]["content"]["title"], "Slim")
        self.assertEqual(intent["metadata"]["build_id"], "b1")
        self.assertTrue(intent["isSelected"])
        self.assertTrue(any(item["id"] == orphan.id and item["uri"] == orphan.uri for item in data["artifacts"]))
        clip = next(item for item in data["artifacts"] if item["id"] == fat.id)
        self.assertEqual(clip["uri"], fat.uri)
        self.assertEqual(clip["metadata"]["build_id"], "b2")
        self.assertEqual(clip["metadata"]["generation_parameters"]["prompt"], "rain girl on the platform")
        self.assertEqual(clip["metadata"]["generation_parameters"]["seed"], 7)
        self.assertIn("raw", clip["metadata"])
        self.assertNotIn("skill_context", clip["metadata"])
        self.assertNotIn("provenance", clip)
        story = next(item for item in data["artifacts"] if item["id"] == script.id)
        self.assertEqual(story["metadata"]["content"], "夜雨站台，五秒动漫MV。")
        self.assertNotIn("skill_context", story["metadata"])
        encoded = json.dumps(data["artifacts"])
        self.assertNotIn('"skill_context"', encoded)
        self.assertNotIn("SKILL_CONTEXT_BLOB", encoded)
