from __future__ import annotations

import asyncio
import base64
import sys
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.video_runtime.api import set_runtime
from app.video_runtime.deepseek_bff import (
    _compat_event,
    _load_run_context,
    _sign_uploaded_file,
    _UI_DEFAULTS_SEPARATOR,
    router,
    set_deepseek_client,
    studio_router,
)
from app.video_runtime.deepseek_client import DeepSeekHarnessError
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.models import Build, PlanCheckpoint, ProjectIntent, RebuildPlan
from app.video_runtime.skills import VideoSkillRuntime


class FakeDeepSeekClient:
    def __init__(self) -> None:
        self.events: dict[str, list[dict]] = {}
        self.prompts: list[tuple[str, str]] = []
        self.prompt_images: list[list[dict]] = []
        self.missing_sessions: set[str] = set()
        self.session_count = 0
        self.history_calls = 0

    async def list_sessions(self) -> list[dict]:
        return [{"sessionId": session_id} for session_id in self.events]

    async def create_session(self, **options) -> str:
        self.session_count += 1
        session_id = options.get("session_id") or f"dsh-session-{self.session_count}"
        self.events.setdefault(session_id, [])
        return session_id

    async def prompt(self, session_id: str, text: str, **options) -> None:
        self.prompts.append((session_id, text))
        self.prompt_images.append(list(options.get("images") or []))
        previous = self.events[session_id]
        additions = [
            {"type": "turn/start", "seq": 0, "time": 1000, "data": {"turn": 1}},
            {"type": "user/message", "seq": 1, "time": 1001, "data": {
                "content": [{"type": "text", "text": text}],
                "source": {"kind": "user"},
            }},
            {"type": "user/message", "seq": 2, "time": 1002, "data": {
                "content": [{"type": "text", "text": "internal context"}],
                "source": {"kind": "plugin", "plugin": "test-context"},
            }},
            {"type": "assistant/message", "seq": 3, "time": 1003, "data": {
                "message": {"content": [{"type": "text", "text": "Project opened"}]},
            }},
            {"type": "turn/end", "seq": 4, "time": 1004, "data": {
                "turn": 1, "reason": {"kind": "complete"},
            }},
        ]
        offset = len(previous)
        self.events[session_id] = previous + [
            {**item, "seq": item["seq"] + offset, "time": item["time"] + offset}
            for item in additions
        ]

    async def history(self, session_id: str, **_options) -> dict:
        self.history_calls += 1
        if session_id in self.missing_sessions:
            raise DeepSeekHarnessError(
                f'session.history failed: session-not-found: session "{session_id}" not found',
            )
        return {
            "events": [{"event": item} for item in self.events[session_id]],
            "hasMore": False,
        }

    async def cancel(self, _session_id: str) -> None:
        return None


class DeepSeekCompatibilityBffTest(unittest.TestCase):
    def setUp(self) -> None:
        self._wavespeed_patch = patch.dict(
            os.environ, {"WAVESPEED_API_KEY": "test-wavespeed-key"}, clear=False,
        )
        self._wavespeed_patch.start()
        self.runtime = VideoBuildRuntime()
        self.deepseek = FakeDeepSeekClient()
        set_runtime(self.runtime)
        set_deepseek_client(self.deepseek)
        subapp = FastAPI()
        subapp.include_router(router)
        subapp.include_router(studio_router)
        app = FastAPI()
        app.mount("/chat-v1/service", subapp)
        self.client = TestClient(app)

        async def local_source_bytes(url: str) -> bytes | None:
            path = Path(str(url or "").strip())
            if path.is_file():
                return path.read_bytes()
            return None

        self._source_bytes_patch = patch(
            "app.video_runtime.deepseek_bff._load_source_image_bytes",
            side_effect=local_source_bytes,
        )
        self._source_bytes_patch.start()

    def tearDown(self) -> None:
        self._source_bytes_patch.stop()
        self._wavespeed_patch.stop()
        self.client.close()
        set_deepseek_client(None)

    def test_runtime_options_default_to_code_video_without_wavespeed(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WAVESPEED_API_KEY", None)
            response = self.client.get("/chat-v1/service/v2/runtime-options")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {
            "wavespeed_configured": False,
            "default_code_video_mode": True,
        })

    def test_code_video_mode_defaults_without_wavespeed_and_persists(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WAVESPEED_API_KEY", None)
            created = self.client.post("/chat-v1/service/v2/runs", json={
                "objective": "Create a kinetic typography video",
                "idempotency_key": "code-video-default",
            })

        self.assertEqual(created.status_code, 200)
        run = created.json()["data"]
        self.assertTrue(run["code_video_mode"])
        self.assertFalse(run["automatic_video"])
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn("CODE-TO-VIDEO MODE IS ENABLED", prompt)
        self.assertIn("media.hyperframes_render", prompt)
        self.assertIn("do not call atomic.video.generate", prompt)

        follow_up = self.client.post(
            f"/chat-v1/service/v2/runs/{run['project_id']}/messages",
            json={
                "content": "Change the headline to Local rendering",
                "idempotency_key": "code-video-follow-up",
            },
        )
        self.assertEqual(follow_up.status_code, 200)
        self.assertTrue(follow_up.json()["data"]["code_video_mode"])
        self.assertIn("generation_parameters.composition_html", self.deepseek.prompts[-1][1])

    def test_explicit_code_video_false_overrides_missing_wavespeed_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WAVESPEED_API_KEY", None)
            response = self.client.post("/chat-v1/service/v2/runs", json={
                "objective": "Create a cloud video",
                "idempotency_key": "code-video-disabled",
                "code_video_mode": False,
            })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["code_video_mode"])
        self.assertNotIn("CODE-TO-VIDEO MODE IS ENABLED", self.deepseek.prompts[-1][1])

    def test_planning_off_suppresses_missing_wavespeed_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WAVESPEED_API_KEY", None)
            response = self.client.post("/chat-v1/service/v2/runs", json={
                "objective": "Generate one image",
                "idempotency_key": "planning-off-no-wavespeed",
                "planning_off": True,
            })

        self.assertEqual(response.status_code, 200)
        run = response.json()["data"]
        self.assertTrue(run["planning_off"])
        self.assertFalse(run["code_video_mode"])

    def test_planning_off_and_code_video_cannot_both_be_enabled(self) -> None:
        response = self.client.post("/chat-v1/service/v2/runs", json={
            "objective": "Create a video",
            "idempotency_key": "conflicting-modes",
            "planning_off": True,
            "code_video_mode": True,
        })

        self.assertEqual(response.status_code, 422)
        self.assertIn("cannot be enabled together", response.json()["detail"])

    def test_stop_cancels_build_and_resume_requires_explicit_confirmation(self) -> None:
        response = self.client.post("/chat-v1/service/v2/runs", json={
            "objective": "Make a video", "idempotency_key": "stop-create",
        })
        project_id = response.json()["data"]["project_id"]
        project = asyncio.run(self.runtime.repo.get_project(project_id))
        build = Build(project_id=project_id, plan_id="test-plan",
                      base_project_version_id=project.current_version_id,
                      idempotency_key="test-build", status="waiting_agent")
        self.runtime.repo.builds[build.id] = build
        base = f"/chat-v1/service/v2/runs/{project_id}"
        stopped = self.client.post(base + "/cancel")
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["data"]["status"], "cancelled")
        self.assertEqual(self.runtime.repo.builds[build.id].status, "cancelled")
        denied = self.client.post(base + "/messages", json={
            "content": "continue", "idempotency_key": "unconfirmed",
        })
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["detail"]["code"], "task_stopped_resume_required")
        resumed = self.client.post(base + "/resume", json={
            "content": "continue", "idempotency_key": "confirmed",
        })
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(self.runtime.repo.builds[build.id].status, "queued")
        self.assertIn("Do not create a replacement build", self.deepseek.prompts[-1][1])

    def test_old_v2_paths_drive_deepseek_session_and_video_project(self) -> None:
        uploaded_url = "https://example.test/hero.png"
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Make a trailer",
                "idempotency_key": "request-1",
                "automatic_video": True,
                "user_option": {
                    "duration": 15,
                    "aspect_ratio": "9:16",
                    "resolution": "720p",
                    "video_generation_tool": "seedance_2_i2v",
                },
                "input_files": [{
                    "type": "image",
                    "url": uploaded_url,
                    "metadata": {
                        "upload_receipt": _sign_uploaded_file("local-user", "image", uploaded_url),
                    },
                }],
            },
        )
        self.assertEqual(created.status_code, 200)
        run = created.json()["data"]
        self.assertEqual(run["thread_id"], "dsh-session-1")
        self.assertIn(run["project_id"], self.deepseek.prompts[0][1])
        prompt = self.deepseek.prompts[0][1]
        self.assertIn("video_project_plan", prompt)
        self.assertIn("video_project_build", prompt)
        self.assertIn("video_workflow_list", prompt)
        self.assertIn("video_workflow_load", prompt)
        self.assertIn("video_skill_load", prompt)
        self.assertIn("video_skill_read_resource", prompt)
        self.assertIn("video_plan_patch_capability_list", prompt)
        self.assertIn("parameters_schema", prompt)
        self.assertNotIn("load_skill", prompt)
        self.assertNotIn("Set VideoSpec.workflow_id exactly to \"cuti.seedance-story\"", prompt)
        self.assertIn("Do not create another project", prompt)
        self.assertIn('"duration": 15', prompt)
        self.assertNotIn(uploaded_url, prompt)
        self.assertIn("source:", prompt)
        self.assertIn("never normalize Seedance 2.5 to Seedance 2.0", prompt)
        self.assertIn("never send JSON null", prompt)

        snapshot = self.client.get(
            f"/chat-v1/service/v2/runs/{run['id']}",
        ).json()["data"]
        self.assertEqual(snapshot["run"]["status"], "completed")
        self.assertEqual(snapshot["run"]["user_option"]["duration"], 15)
        self.assertEqual(
            snapshot["run"]["input_files"][0]["url"],
            "https://example.test/hero.png",
        )
        self.assertEqual(len(snapshot["messages"]), 2)
        self.assertEqual(snapshot["messages"][0]["content"], "Make a trailer")
        self.assertEqual(snapshot["messages"][-1]["content"], "Project opened")
        self.assertEqual(
            self.client.get("/chat-v1/service/v2/runs").json()["data"][0]["id"],
            run["id"],
        )
        repeated = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Make a trailer", "idempotency_key": "request-1"},
        ).json()["data"]
        self.assertEqual(repeated["id"], run["id"])
        self.assertEqual(repeated["user_option"]["duration"], 15)
        self.assertEqual(len(self.deepseek.prompts), 1)

    def test_create_attaches_source_images_without_copying_urls(self) -> None:
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(png)
            uploaded_path = handle.name
        try:
            with patch.dict("os.environ", {
                "VIDEO_STAGED_PLANNING_ENABLED": "true",
                "VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED": "true",
            }):
                created = self.client.post(
                    "/chat-v1/service/v2/runs",
                    json={
                        "objective": "生成mv",
                        "idempotency_key": "attach-image-1",
                        "automatic_video": True,
                        "input_files": [{
                            "type": "image",
                            "url": uploaded_path,
                            "filename": "source.png",
                            "metadata": {
                                "upload_receipt": _sign_uploaded_file(
                                    "local-user", "image", uploaded_path,
                                ),
                            },
                        }],
                    },
                )
        finally:
            Path(uploaded_path).unlink(missing_ok=True)
        self.assertEqual(created.status_code, 200, created.text)
        prompt = self.deepseek.prompts[0][1]
        self.assertNotIn(uploaded_path, prompt)
        self.assertIn("source:", prompt)
        self.assertIn("Source images attached to this message", prompt)
        self.assertIn(
            "Write ProjectIntent.brief as the working plan: the user request, plus what you can "
            "see in any attached source media",
            prompt,
        )
        images = self.deepseek.prompt_images[0]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["type"], "image")
        self.assertEqual(images[0]["mediaType"], "image/png")
        self.assertEqual(images[0]["name"], "source.png")
        self.assertEqual(base64.b64decode(images[0]["data"]), png)

    def test_list_runs_keeps_project_when_deepseek_session_was_removed(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Make a trailer", "idempotency_key": "missing-session-1"},
        ).json()["data"]
        self.deepseek.missing_sessions.add(created["thread_id"])

        response = self.client.get("/chat-v1/service/v2/runs")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"][0]["id"], created["id"])
        self.assertEqual(response.json()["data"][0]["thread_id"], created["thread_id"])

    def test_list_runs_does_not_load_deepseek_history(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Make a trailer", "idempotency_key": "list-no-history"},
        ).json()["data"]
        before = self.deepseek.history_calls
        listed = self.client.get("/chat-v1/service/v2/runs").json()["data"]
        self.assertEqual(self.deepseek.history_calls, before)
        self.assertEqual(listed[0]["id"], created["id"])
        snapshot = self.client.get(f"/chat-v1/service/v2/runs/{created['id']}").json()["data"]
        listed = self.client.get("/chat-v1/service/v2/runs").json()["data"][0]
        self.assertEqual(listed["last_response"], snapshot["run"]["last_response"])
        self.assertTrue(snapshot["events"])
        self.assertFalse(snapshot["has_more_events"])
        self.assertEqual(snapshot["messages"][-1]["content"], "Project opened")

    def test_snapshot_keeps_messages_but_tails_trace_events(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Make a trailer", "idempotency_key": "tail-events"},
        ).json()["data"]
        session_id = created["thread_id"]
        extras = [
            {
                "type": "tool/call",
                "seq": 10 + index,
                "time": 2000 + index,
                "data": {"callId": f"c{index}", "name": "search", "arguments": "{}"},
            }
            for index in range(120)
        ]
        self.deepseek.events[session_id].extend(extras)
        snapshot = self.client.get(f"/chat-v1/service/v2/runs/{created['id']}").json()["data"]
        event_log = self.client.get(
            f"/chat-v1/service/v2/runs/{created['id']}/event-log",
        ).json()["data"]
        self.assertTrue(snapshot["has_more_events"])
        self.assertEqual(len(snapshot["events"]), 80)
        self.assertGreater(len(event_log), 80)
        self.assertEqual(snapshot["last_event_sequence"], extras[-1]["seq"] + 1)
        self.assertEqual(snapshot["messages"][-1]["content"], "Project opened")
        self.assertTrue(any(message["role"] == "user" for message in snapshot["messages"]))
        self.assertEqual(snapshot["events"][-1]["payload"]["call_id"], "c119")

    def test_orphaned_create_route_gets_a_fresh_deepseek_session(self) -> None:
        replacement = FakeDeepSeekClient()
        replacement.events["orphaned-route-session"] = [{
            "type": "assistant/message",
            "seq": 0,
            "time": 1000,
            "data": {"message": {"content": [{"type": "text", "text": "stale"}]}},
        }]
        self.deepseek = replacement
        set_deepseek_client(replacement)

        response = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Restart an orphaned Create route",
                "idempotency_key": "orphaned-route-request",
                "thread_id": "orphaned-route-session",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()["data"]
        self.assertEqual(run["thread_id"], "dsh-session-1")
        self.assertNotEqual(run["thread_id"], "orphaned-route-session")
        self.assertEqual(replacement.prompts[0][0], run["thread_id"])

    def test_unused_create_route_keeps_its_requested_session_id(self) -> None:
        response = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Start from a fresh Create route",
                "idempotency_key": "fresh-route-request",
                "thread_id": "fresh-route-session",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()["data"]
        self.assertEqual(run["thread_id"], "fresh-route-session")
        self.assertEqual(self.deepseek.prompts[0][0], "fresh-route-session")

    def test_old_studio_paths_keep_thread_based_navigation(self) -> None:
        created = self.client.post(
            "/chat-v1/service/studio/projects",
            json={"objective": "Make a studio trailer"},
        )
        self.assertEqual(created.status_code, 200)
        project = created.json()["data"]["project"]
        thread_id = project["thread_id"]

        snapshot = self.client.get(
            f"/chat-v1/service/studio/projects/{thread_id}",
        ).json()["data"]
        self.assertEqual(snapshot["run"]["id"], project["id"])

        skills = self.client.get(
            f"/chat-v1/service/studio/projects/{thread_id}/skills",
        )
        self.assertEqual(skills.status_code, 200)
        self.assertEqual(skills.json()["data"], [])

        updated = self.client.post(
            f"/chat-v1/service/studio/projects/{thread_id}/commands",
            json={"objective": "Make it shorter"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["data"]["project"]["thread_id"], thread_id)
        self.assertEqual(len(self.deepseek.prompts), 2)

    def test_skill_catalog_structured_selection_and_project_locks(self) -> None:
        catalog = self.client.get("/chat-v1/service/v2/skills")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        names = {item["name"] for item in catalog.json()["data"]}
        self.assertIn("product-voiceover-narration", names)
        self.assertNotIn("cuti.atomic-providers", names)

        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Make a Skill-driven trailer",
                "idempotency_key": "skill-selection-1",
                "workflow_id": "cuti-product-workflow",
                "activated_skill_ids": ["product-voiceover-narration"],
            },
        ).json()["data"]
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn('"cuti-product-workflow"', prompt)
        self.assertIn("Call video_workflow_load", prompt)
        self.assertIn('VideoSpec.activated_skill_ids exactly to ["product-voiceover-narration"]', prompt)
        self.assertNotIn("$cuti-product-workflow", prompt)

        lock_response = self.client.post(
            f"/chat-v1/service/studio/projects/{created['thread_id']}"
            "/skills/product-voiceover-narration/enable",
            json={"enabled": True},
        )
        self.assertEqual(lock_response.status_code, 200, lock_response.text)
        lock = lock_response.json()["data"]
        self.assertEqual(lock["project_id"], created["project_id"])
        self.assertEqual(lock["skill_id"], "product-voiceover-narration")
        self.assertTrue(lock["enabled"])
        listed = self.client.get(
            f"/chat-v1/service/studio/projects/{created['thread_id']}/skills",
        ).json()["data"]
        self.assertEqual([item["skill_id"] for item in listed], ["product-voiceover-narration"])

        self.client.post(
            f"/chat-v1/service/v2/runs/{created['id']}/messages",
            json={
                "content": "Make the hero warmer",
                "idempotency_key": "skill-edit-1",
                "automatic_video": True,
            },
        )
        self.assertIn(
            'VideoSpec.activated_skill_ids exactly to ["product-voiceover-narration"]',
            self.deepseek.prompts[-1][1],
        )

    def test_seedance2_dollar_activation_loads_original_cuti_instructions(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "$seedance2 make a connected one minute film",
                "idempotency_key": "seedance2-original-1",
                "user_option": {"duration": 60},
            },
        )

        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["workflow_id"], "seedance2")
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn('"seedance2"', prompt)
        self.assertIn("Call video_workflow_load", prompt)
        self.assertNotIn("BEGIN seedance2/SKILL.md", prompt)

        snapshot = self.client.get(
            f"/chat-v1/service/v2/runs/{run['id']}",
        ).json()["data"]
        self.assertEqual(snapshot["run"]["workflow_id"], "seedance2")

    def test_workflow_selection_priority_and_unknown_rejection(self) -> None:
        explicit = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "$seedance2 make a product spot",
                "idempotency_key": "workflow-priority-1",
                "workflow_id": "cuti-product-workflow",
            },
        )
        self.assertEqual(explicit.status_code, 200, explicit.text)
        self.assertEqual(explicit.json()["data"]["workflow_id"], "cuti-product-workflow")

        unavailable = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Use the Ink Press template",
                "idempotency_key": "workflow-unavailable-1",
                "workflow_id": "ink-press-product-workflow",
            },
        )
        self.assertEqual(unavailable.status_code, 422, unavailable.text)
        self.assertIn("not installed", unavailable.json()["detail"].lower())

        ambiguous = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "$seedance2 or $mv",
                "idempotency_key": "workflow-ambiguous-1",
            },
        )
        self.assertEqual(ambiguous.status_code, 422, ambiguous.text)

    def test_empty_project_follow_up_reapplies_create_contract(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Inspect only", "idempotency_key": "draft-1"},
        ).json()["data"]

        response = self.client.post(
            f"/chat-v1/service/v2/runs/{created['id']}/messages",
            json={
                "content": "Make a 15 second product video",
                "idempotency_key": "follow-up-1",
                "automatic_video": True,
                "user_option": {"duration": 15},
            },
        )

        self.assertEqual(response.status_code, 200)
        prompt = self.deepseek.prompts[-1][1]
        self.assertTrue(prompt.startswith("CUTI_VIDEO_CREATE_V1\n"))
        self.assertIn("video_project_plan", prompt)
        self.assertIn("video_project_build", prompt)
        self.assertIn("Make a 15 second product video", prompt)

    def test_plain_greeting_uses_agent_routing_without_forcing_video(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "你好", "idempotency_key": "greeting-1"},
        )

        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        prompt = self.deepseek.prompts[-1][1]
        self.assertTrue(prompt.startswith("CUTI_AGENT_CHAT_V1\n"))
        self.assertIn("must receive a normal direct answer", prompt)
        self.assertIn("without calling any video_* tool", prompt)
        self.assertNotIn("Start the build in this turn", prompt)
        self.assertEqual(asyncio.run(self.runtime.repo.list_builds(run["project_id"])), [])

        snapshot = self.client.get(
            f"/chat-v1/service/v2/runs/{run['id']}",
        ).json()["data"]
        self.assertEqual(snapshot["messages"][0]["content"], "你好")
        self.assertFalse(snapshot["run"]["automatic_video"])

    def test_planning_off_persists_and_bypasses_all_workflow_and_skill_selection(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Generate one image of a blue fox",
                "idempotency_key": "planning-off-create",
                "planning_off": True,
                "automatic_video": True,
                "workflow_id": "not-installed-workflow",
                "activated_skill_ids": ["not-installed-skill"],
            },
        )

        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertTrue(run["planning_off"])
        self.assertFalse(run["automatic_video"])
        self.assertIsNone(run["workflow_id"])
        self.assertEqual(run["activated_skill_ids"], [])
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn("PLANNING-OFF MODE IS ENABLED", prompt)
        self.assertIn("runtime.artifact.persist", prompt)
        self.assertIn("atomic.image.generate", prompt)
        self.assertIn("atomic.video.generate", prompt)
        self.assertNotIn("video_workflow_list", prompt)
        self.assertNotIn("video_workflow_load", prompt)
        self.assertNotIn("video_skill_load", prompt)
        self.assertNotIn(_UI_DEFAULTS_SEPARATOR, prompt)

        follow_up = self.client.post(
            f"/chat-v1/service/v2/runs/{run['id']}/messages",
            json={
                "content": "Make it warmer",
                "idempotency_key": "planning-off-follow-up",
            },
        )
        self.assertEqual(follow_up.status_code, 200, follow_up.text)
        self.assertTrue(follow_up.json()["data"]["planning_off"])
        self.assertIn("PLANNING-OFF MODE IS ENABLED", self.deepseek.prompts[-1][1])

        restored = self.client.post(
            f"/chat-v1/service/v2/runs/{run['id']}/messages",
            json={
                "content": "Return to normal planning",
                "idempotency_key": "planning-off-disable",
                "planning_off": False,
            },
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertFalse(restored.json()["data"]["planning_off"])
        self.assertNotIn("PLANNING-OFF MODE IS ENABLED", self.deepseek.prompts[-1][1])

    def test_planning_off_command_enables_minimal_mode(self) -> None:
        response = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "/planning-off create a short caption",
                "idempotency_key": "planning-off-command",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["data"]["planning_off"])
        self.assertIn("PLANNING-OFF MODE IS ENABLED", self.deepseek.prompts[-1][1])

    def test_planning_off_keeps_one_session_for_multi_turn_media_operations(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "为我生成音乐",
                "idempotency_key": "planning-off-media-1",
                "thread_id": "planning-off-media-thread",
                "planning_off": True,
            },
        ).json()["data"]
        url = f"/chat-v1/service/v2/runs/{created['id']}/messages"
        turns = [
            "为我生成图片",
            "根据刚才的音乐和图片生成视频",
            "把刚才的音乐和视频合成起来",
        ]
        for index, content in enumerate(turns, start=2):
            response = self.client.post(url, json={
                "content": content,
                "idempotency_key": f"planning-off-media-{index}",
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["data"]["planning_off"])

        self.assertEqual(self.deepseek.session_count, 1)
        self.assertEqual(
            {session_id for session_id, _prompt in self.deepseek.prompts},
            {"planning-off-media-thread"},
        )
        prompts = [prompt for _session_id, prompt in self.deepseek.prompts]
        self.assertIn("one music Artifact, never a music-video Workflow", prompts[0])
        self.assertIn("atomic.music.generate", prompts[0])
        self.assertIn("atomic.image.generate", prompts[1])
        self.assertIn("prior music/audio with the audio role", prompts[2])
        self.assertIn("media.mix_audio", prompts[3])
        self.assertTrue(all("video_workflow_list" not in prompt for prompt in prompts))

    def test_plain_follow_up_in_empty_draft_stays_agent_routed(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "你好", "idempotency_key": "greeting-draft-1"},
        ).json()["data"]

        response = self.client.post(
            f"/chat-v1/service/v2/runs/{created['id']}/messages",
            json={"content": "你能做什么？", "idempotency_key": "greeting-follow-up-1"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        prompt = self.deepseek.prompts[-1][1]
        self.assertTrue(prompt.startswith("CUTI_AGENT_CHAT_V1\n"))
        self.assertNotIn("Start the build in this turn", prompt)

    def test_plain_message_in_existing_project_keeps_tool_choice_conditional(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "Make a video",
                "idempotency_key": "existing-chat-1",
                "automatic_video": True,
            },
        ).json()["data"]
        project = asyncio.run(self.runtime.repo.get_project(created["project_id"]))
        build = Build(
            project_id=created["project_id"],
            plan_id="existing-plan",
            base_project_version_id=project.current_version_id,
            idempotency_key="existing-build",
            status="completed",
        )
        self.runtime.repo.builds[build.id] = build

        response = self.client.post(
            f"/chat-v1/service/v2/runs/{created['id']}/messages",
            json={"content": "你好", "idempotency_key": "existing-chat-2"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        prompt = self.deepseek.prompts[-1][1]
        self.assertTrue(prompt.startswith('CUTI_AGENT_CHAT_V1\nVISIBLE_USER_REQUEST_JSON: "你好"'))
        self.assertIn("If it does not, answer directly", prompt)
        self.assertNotIn("the user's edit request authorizes", prompt)

    def test_saved_workflow_does_not_force_a_greeting_into_production(self) -> None:
        run = self.client.post('/chat-v1/service/v2/runs', json={
            'objective': 'A fox film', 'workflow_id': 'seedance2', 'idempotency_key': 'saved-workflow',
        }).json()['data']
        response = self.client.post(f"/chat-v1/service/v2/runs/{run['id']}/messages", json={
            'content': 'Hello', 'idempotency_key': 'saved-workflow-chat',
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.deepseek.prompts[-1][1].startswith('CUTI_AGENT_CHAT_V1\n'))
        self.assertFalse(response.json()['data']['automatic_video'])

    def test_followups_keep_session_history_and_persist_changed_options(self) -> None:
        run = self.client.post('/chat-v1/service/v2/runs', json={
            'objective': 'Remember the blue fox', 'thread_id': 'fixed-thread',
            'idempotency_key': 'multi-1',
        }).json()['data']
        url = f"/chat-v1/service/v2/runs/{run['id']}"
        for index, content in enumerate(['What character did I name?', 'Continue with that character']):
            response = self.client.post(url + '/messages', json={
                'content': content, 'thread_id': 'fixed-thread',
                'idempotency_key': f'multi-{index + 2}', 'user_option': {'duration': 24},
            })
            self.assertEqual(response.status_code, 200, response.text)
        snapshot = self.client.get(url).json()['data']
        self.assertEqual(self.deepseek.session_count, 1)
        self.assertEqual({item[0] for item in self.deepseek.prompts}, {'fixed-thread'})
        self.assertEqual([item['content'] for item in snapshot['messages'] if item['role'] == 'user'], [
            'Remember the blue fox', 'What character did I name?', 'Continue with that character',
        ])
        self.assertEqual(snapshot['last_event_sequence'], 15)
        self.assertEqual(snapshot['run']['user_option']['duration'], 24)
        mismatch = self.client.post(url + '/messages', json={
            'content': 'continue', 'thread_id': 'wrong-thread', 'idempotency_key': 'wrong',
        })
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(len(self.deepseek.prompts), 3)

    def test_followup_logs_existing_checkpoint_and_artifact_references(self) -> None:
        run = self.client.post('/chat-v1/service/v2/runs', json={
            'objective': 'A blue fox film', 'idempotency_key': 'checkpoint-context',
        }).json()['data']
        project = asyncio.run(self.runtime.repo.get_project(run['id']))
        build = Build(project_id=project.id, plan_id='plan-1',
                      base_project_version_id=project.current_version_id,
                      idempotency_key='build-1', status='waiting_agent')
        self.runtime.repo.builds[build.id] = build
        checkpoint = PlanCheckpoint(
            project_id=project.id, build_id=build.id, plan_id=build.plan_id,
            workflow_id='seedance2', session_id=run['thread_id'], user_id='local-user',
            phase='reference', next_phase='video', base_plan_revision=1, base_spec_revision=1,
            artifact_version_ids=['blue-fox-reference-v1'],
        )
        self.runtime.repo.checkpoints[checkpoint.id] = checkpoint
        self.runtime.repo.build_checkpoints[build.id].append(checkpoint.id)
        response = self.client.post(f"/chat-v1/service/v2/runs/{run['id']}/messages", json={
            'content': 'Continue with that character', 'idempotency_key': 'checkpoint-followup',
        })
        self.assertEqual(response.status_code, 200, response.text)
        session_id, prompt = self.deepseek.prompts[-1]
        payload = json.loads(prompt.splitlines()[-1])
        self.assertEqual(session_id, run['thread_id'])
        self.assertEqual(payload['thread_id'], session_id)
        self.assertEqual(payload['latest_build']['id'], build.id)
        self.assertEqual(payload['checkpoints'][0]['artifact_version_ids'], ['blue-fox-reference-v1'])
        self.assertIn('conversation history, tool results', prompt)

    def test_zip_install_reloads_the_runtime_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "external"
            runtime = VideoBuildRuntime(skill_runtime=VideoSkillRuntime([root]))
            set_runtime(runtime)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("test-helper/SKILL.md", """---
name: test-helper
description: Test helper guidance
metadata:
  roles: [guidance]
---
Keep the requested visual tone consistent.
""")

            response = self.client.post(
                "/chat-v1/service/studio/skills/install",
                files={"bundle": ("test-helper.zip", archive.getvalue(), "application/zip")},
                data={"overwrite": "false"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["data"]["name"], "test-helper")
            catalog = self.client.get("/chat-v1/service/v2/skills").json()["data"]
            installed = next(item for item in catalog if item["name"] == "test-helper")
            self.assertEqual(installed["description"], "Test helper guidance")
            self.assertTrue(installed["installed_at"])

    def test_failed_turn_exposes_provider_error_to_studio_notice(self) -> None:
        message = "You have no credits remaining. Add credits to continue using the API."
        for error, expected in [
            ({"message": message, "code": "PI_AI_ERROR"}, message),
            ("Connection timed out", "Connection timed out"),
            ({}, "Model request failed"),
        ]:
            with self.subTest(error=error):
                event = _compat_event("project-1", {
                    "type": "turn/end", "seq": 14, "time": 1004,
                    "data": {"turn": 1, "reason": {"kind": "error", "error": error}},
                })
                self.assertEqual(event["type"], "run.failed")
                self.assertEqual(event["payload"]["error"], expected)
                if isinstance(error, dict):
                    self.assertEqual(event["payload"]["error_code"], error.get("code"))

    def test_compat_events_match_reducer_contract_and_stream_text(self) -> None:
        message = _compat_event("project-1", {
            "type": "assistant/message",
            "seq": 7,
            "time": 1000,
            "data": {"message": {"content": [{"type": "text", "text": "Done"}]}},
        })
        self.assertEqual(message["type"], "chat.message.created")
        self.assertEqual(message["payload"]["message"]["content"], "Done")
        self.assertEqual(message["payload"]["message"]["id"], "dsh-project-1-7")

        delta = _compat_event("project-1", {
            "type": "assistant/chunk",
            "seq": 8,
            "time": 1001,
            "data": {"turn": 2, "chunk": {"type": "text-delta", "text": "Working"}},
        })
        self.assertEqual(delta["type"], "agent.message.delta")
        self.assertEqual(delta["payload"]["delta"], "Working")
        usage = _compat_event("project-1", {
            "type": "assistant/chunk",
            "seq": 9,
            "time": 1002,
            "data": {"turn": 2, "step": 1, "chunk": {
                "type": "usage",
                "usage": {
                    "inputTokens": 12,
                    "outputTokens": 8,
                    "cacheReadTokens": 100,
                    "cacheWriteTokens": 5,
                },
            }},
        })
        self.assertEqual(usage["type"], "llm.usage")
        self.assertEqual(usage["payload"]["total_tokens"], 125)
        self.assertIsNone(_compat_event("project-1", {
            "type": "assistant/chunk",
            "seq": 10,
            "time": 1003,
            "data": {"turn": 2, "chunk": {"type": "thinking-delta", "text": "private"}},
        }))

        user = _compat_event("project-1", {
            "type": "user/message",
            "seq": 11,
            "time": 1004,
            "data": {
                "source": {"kind": "user"},
                "content": [{
                    "type": "text",
                    "text": "Make a video\n\nCurrent creation controls and inputs:\n{\"duration\": 15}",
                }],
            },
        })
        self.assertEqual(user["payload"]["message"]["content"], "Make a video")

        user_defaults = _compat_event("project-1", {
            "type": "user/message",
            "seq": 12,
            "time": 1005,
            "data": {
                "source": {"kind": "user"},
                "content": [{
                    "type": "text",
                    "text": (
                        "Make a video"
                        + _UI_DEFAULTS_SEPARATOR
                        + "{\"duration\": 15}"
                    ),
                }],
            },
        })
        self.assertEqual(user_defaults["payload"]["message"]["content"], "Make a video")

        tool = _compat_event("project-1", {
            "type": "tool/call",
            "seq": 12,
            "time": 1005,
            "data": {
                "turn": 2,
                "step": 2,
                "callId": "call-1",
                "name": "video_project_build",
                "arguments": "{\"plan_id\":\"plan-1\"}",
            },
        })
        self.assertEqual(tool["payload"]["tool"], "video_project_build")
        self.assertEqual(tool["payload"]["input"]["plan_id"], "plan-1")

        result = _compat_event("project-1", {
            "type": "tool/result",
            "seq": 13,
            "time": 1006,
            "data": {"turn": 2, "step": 2, "message": {
                "source": {"kind": "tool", "callId": "call-1"},
                "content": [{
                    "type": "tool-result",
                    "toolCallId": "call-1",
                    "content": [{"type": "text", "text": "Build queued"}],
                    "isError": False,
                }],
            }},
        })
        self.assertEqual(result["payload"]["call_id"], "call-1")
        self.assertEqual(result["payload"]["output"], "Build queued")

    def test_token_usage_is_aggregated_from_deepseek_usage_chunks(self) -> None:
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Measure usage", "idempotency_key": "usage-1"},
        ).json()["data"]
        session_id = created["thread_id"]
        self.deepseek.events[session_id].insert(-1, {
            "type": "assistant/chunk",
            "seq": 4,
            "time": 1004,
            "data": {"turn": 1, "step": 1, "chunk": {
                "type": "usage",
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 20,
                    "cacheReadTokens": 30,
                    "cacheWriteTokens": 4,
                },
            }},
        })

        usage = self.client.get(
            f"/chat-v1/service/v2/runs/{created['id']}/token-usage",
        ).json()["data"]

        self.assertEqual(usage["calls"], 1)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 20)
        self.assertEqual(usage["cached_tokens"], 30)
        self.assertEqual(usage["total_tokens"], 64)

    def test_create_prompt_follows_named_skills_without_workflow_hardcodes(self):
        from app.video_runtime.deepseek_bff import _initial_video_build_prompt

        prompt = _initial_video_build_prompt(
            objective="做一首 MV",
            project_id="p1",
            base_project_version_id="v1",
            idempotency_key="k1",
            user_option=None,
            input_files=[],
            workflow_id="mv",
            activated_skill_ids=[],
        )
        self.assertIn("video_workflow_load", prompt)
        self.assertIn('"mv"', prompt)
        self.assertIn("video_skill_load", prompt)
        self.assertIn("video_skill_read_resource", prompt)
        self.assertIn("video_plan_patch_capability_list", prompt)
        self.assertIn("UI defaults (creation controls)", prompt)
        self.assertIn("highest priority", prompt)
        self.assertIn("only to fields the user did not mention", prompt)
        self.assertNotIn("6smv", prompt)
        self.assertNotIn(
            "Respect duration, aspect ratio, resolution, selected image/video providers",
            prompt,
        )
        self.assertNotIn("load_skill", prompt)
        self.assertNotIn("read_skill_resource", prompt)
        self.assertNotIn("suno-song", prompt)
        self.assertNotIn("video-research", prompt)
        self.assertNotIn("hyperframes-captions", prompt)
        self.assertNotIn("Bitwize", prompt)
        self.assertNotIn("minimax-h3", prompt)
        self.assertNotIn("Call video_skill_load for every activated_skill_id", prompt)

        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={
                "objective": "做一首 MV",
                "idempotency_key": "mv-no-inject-1",
                "workflow_id": "mv",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["workflow_id"], "mv")
        self.assertEqual(run["activated_skill_ids"], [])

    def test_staged_project_intent_prompt_states_brief_job(self):
        from unittest.mock import patch
        from app.video_runtime.deepseek_bff import _initial_video_build_prompt

        with patch.dict("os.environ", {
            "VIDEO_STAGED_PLANNING_ENABLED": "true",
            "VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED": "true",
        }):
            prompt = _initial_video_build_prompt(
                objective="做个mv 30s $mv",
                project_id="p1",
                base_project_version_id="v1",
                idempotency_key="k1",
                user_option=None,
                input_files=[],
                workflow_id="mv",
                activated_skill_ids=[],
            )
        self.assertIn(
            "Write ProjectIntent.brief as the working plan: the user request, plus what you can "
            "see in any attached source media",
            prompt,
        )
        self.assertIn("Shots, captions, and timing wait for media that does not exist yet", prompt)
        self.assertNotIn("containing only known goals and constraints", prompt)
        self.assertNotIn("or other details that depend on media not generated yet", prompt)
        self.assertNotIn("brief is the requested film", prompt)
        self.assertNotIn("Example: user asked", prompt)

    def test_subtitle_translation_message_reaches_agent(self):
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "Make a film", "idempotency_key": "translation-create"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        text = "为当前完整成片添加 HyperFrames 字幕，根据实际英文对白生成中文字幕，保持画面和原声不变。"
        response = self.client.post(
            f"/chat-v1/service/v2/runs/{run['id']}/messages",
            json={"content": text, "idempotency_key": "translation-message"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(text, self.deepseek.prompts[-1][1])

    def test_language_conflict_is_actionable_not_server_error(self):
        response = self.client.post(
            "/chat-v1/service/v2/runs",
            json={"objective": "使用中文字幕和英文字幕", "idempotency_key": "language-conflict"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("字幕", response.json()["detail"])

    def test_create_persists_independent_ui_and_content_languages(self):
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            headers={"X-App-Language": "zh"},
            json={
                "objective": "请用英文展示全部策划，人物对白使用中文，并配英文字幕",
                "idempotency_key": "language-contract-1",
                "workflow_id": "seedance2",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["output_language"], "en")
        self.assertEqual(run["language_contract"], {
            "ui_locale": "zh-CN",
            "content_language": "en-US",
            "spoken_language": "zh-CN",
            "subtitle_language": "en-US",
            "provider_prompt_language": "auto",
        })
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn("content_language=en-US", prompt)
        self.assertIn("spoken_language=zh-CN", prompt)
        self.assertIn("ui_locale is chrome only", prompt)

    def test_create_english_objective_beats_chinese_studio_ui(self):
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            headers={"X-App-Language": "zh"},
            json={
                "objective": (
                    "Magician. A stage magician closes a show; "
                    "the last spark hides in his palm."
                ),
                "idempotency_key": "language-contract-magician",
                "workflow_id": "seedance2",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["output_language"], "en")
        self.assertEqual(run["language_contract"], {
            "ui_locale": "zh-CN",
            "content_language": "en-US",
            "spoken_language": "en-US",
            "subtitle_language": "en-US",
            "provider_prompt_language": "auto",
        })
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn("content_language=en-US", prompt)
        self.assertIn("Write every user-visible", prompt)
        self.assertIn("English", prompt)

    def test_create_chinese_objective_beats_english_studio_ui(self):
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            headers={"X-App-Language": "en"},
            json={
                "objective": "做一首中文说唱MV，舞台上的魔术师把最后一点光藏进掌心。",
                "idempotency_key": "language-contract-rap-mv",
                "workflow_id": "seedance2",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["output_language"], "zh")
        self.assertEqual(run["language_contract"]["ui_locale"], "en-US")
        self.assertEqual(run["language_contract"]["content_language"], "zh-CN")
        self.assertEqual(run["language_contract"]["provider_prompt_language"], "auto")
        prompt = self.deepseek.prompts[-1][1]
        self.assertIn("content_language=zh-CN", prompt)
        self.assertIn("Simplified Chinese", prompt)

    def test_create_language_neutral_ack_falls_back_to_studio_ui(self):
        created = self.client.post(
            "/chat-v1/service/v2/runs",
            headers={"X-App-Language": "zh"},
            json={
                "objective": "OK",
                "idempotency_key": "language-contract-ok-fallback",
                "workflow_id": "seedance2",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["language_contract"]["ui_locale"], "zh-CN")
        self.assertEqual(run["language_contract"]["content_language"], "zh-CN")

    def test_legacy_run_context_recovers_dialogue_language_from_project_intent(self):
        project, version = asyncio.run(self.runtime.create_project(
            user_id="local-user", title="Legacy English dialogue",
        ))
        plan = asyncio.run(self.runtime.repo.save_plan(RebuildPlan(
            project_id=project.id,
            kind="initial",
            base_project_version_id=version.id,
            workflow_id="seedance2",
            project_intent=ProjectIntent(
                title="中文策划",
                brief="制作中文策划，人物对白保持英文。",
                language="zh-CN",
                workflow_id="seedance2",
                style_id="cinematic",
                constraints={"dialogue_language": "English"},
            ),
            items=[],
        ), "legacy-language-plan"))
        build = Build(
            project_id=project.id,
            plan_id=plan.id,
            base_project_version_id=version.id,
            idempotency_key="legacy-language-build",
        )
        self.runtime.repo.builds[build.id] = build
        context = asyncio.run(_load_run_context(self.runtime, project.id))
        self.assertEqual(context["language_contract"]["content_language"], "zh-CN")
        self.assertEqual(context["language_contract"]["spoken_language"], "en-US")
        self.assertEqual(context["language_contract_version"], 1)
