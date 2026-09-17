from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.video_runtime.api import router, set_identity_resolver, set_runtime
from app.video_runtime.identity import ServiceOrLocalIdentityResolver
from app.video_runtime.plugins.models import VideoPluginManifest
from app.video_runtime.plugins.sandbox_proxy import SandboxedVideoPlugin, SandboxWorkerClient
from app.video_runtime.runtime import VideoBuildRuntime
from app.video_runtime.security import CapabilityExecutionEnvelope, CapabilityGrant


class IdentityAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        set_runtime(VideoBuildRuntime())
        set_identity_resolver(ServiceOrLocalIdentityResolver())

    def test_production_identity_fails_closed_without_adapter_or_service_token(self):
        app = FastAPI()
        app.include_router(router)
        with patch.dict(os.environ, {"VIDEO_RUNTIME_ENVIRONMENT": "production"}, clear=False):
            os.environ.pop("VIDEO_RUNTIME_SERVICE_TOKEN", None)
            with TestClient(app) as client:
                response = client.post(
                    "/api/video/projects",
                    headers={"X-Video-User-Id": "forged-user"},
                    json={"title": "Denied"},
                )
        self.assertEqual(response.status_code, 503)

    def test_service_identity_requires_matching_bearer_and_explicit_user(self):
        app = FastAPI()
        app.include_router(router)
        with patch.dict(os.environ, {
            "VIDEO_RUNTIME_ENVIRONMENT": "production",
            "VIDEO_RUNTIME_SERVICE_TOKEN": "runtime-secret",
        }, clear=False):
            with TestClient(app) as client:
                denied = client.post(
                    "/api/video/projects",
                    headers={"X-Video-User-Id": "user-1"},
                    json={"title": "Denied"},
                )
                allowed = client.post(
                    "/api/video/projects",
                    headers={
                        "Authorization": "Bearer runtime-secret",
                        "X-Video-User-Id": "user-1",
                    },
                    json={"title": "Allowed"},
                )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_development_browser_request_uses_local_identity_with_service_token_configured(self):
        app = FastAPI()
        app.include_router(router)
        with patch.dict(os.environ, {
            "VIDEO_RUNTIME_ENVIRONMENT": "development",
            "VIDEO_RUNTIME_SERVICE_TOKEN": "runtime-secret",
            "VIDEO_RUNTIME_LOCAL_USER_ID": "local-user",
        }, clear=False):
            with TestClient(app) as client:
                allowed = client.post(
                    "/api/video/projects",
                    json={"title": "Browser project"},
                )
                denied = client.post(
                    "/api/video/projects",
                    headers={"Authorization": "Bearer wrong-token"},
                    json={"title": "Denied"},
                )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["data"]["title"], "Browser project")
        self.assertEqual(denied.status_code, 401)


class SandboxedPluginTest(unittest.IsolatedAsyncioTestCase):
    async def test_untrusted_plugin_is_forwarded_to_worker_with_granted_limits(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(202, json={"run_id": "sandbox-1", "status": "queued"})
            artifact = base64.b64encode(json.dumps({
                "project_id": "project-1",
                "type": "video",
                "uri": "https://cdn.example.test/result.mp4",
            }).encode()).decode()
            return httpx.Response(200, json={
                "run_id": "sandbox-1",
                "status": "succeeded",
                "artifacts": [{
                    "path": "output/result.json",
                    "media_type": "application/json",
                    "size_bytes": 1,
                    "sha256": "digest",
                    "content_base64": artifact,
                }],
            })

        async_client = httpx.AsyncClient(
            base_url="http://sandbox.test",
            transport=httpx.MockTransport(handler),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run.py").write_text("# external plugin", encoding="utf-8")
            manifest = VideoPluginManifest.model_validate({
                "id": "external.caption",
                "version": "1.0.0",
                "contributions": {"capabilities": ["caption.burn"]},
                "permissions": {
                    "network_domains": ["cdn.example.test"],
                    "max_cost_usd": 1,
                },
                "sandbox_runtime": {
                    "image": "python:3.12-slim",
                    "entrypoint": "run.py",
                },
            })
            plugin = SandboxedVideoPlugin(
                manifest,
                root,
                SandboxWorkerClient("http://sandbox.test", client=async_client),
            )
            envelope = CapabilityExecutionEnvelope(CapabilityGrant(
                project_id="project-1",
                session_id="session-1",
                user_id="user-1",
                plugin_id="external.caption",
                capability="caption.burn",
                allowed_capabilities=["caption.burn"],
                allowed_domains=["cdn.example.test"],
                max_cost_usd=1,
                timeout_seconds=30,
                idempotency_key="caption-1",
                audit_id="audit-1",
                nonce="nonce-1",
                expires_at=int(time.time()) + 60,
            ))
            result = await plugin.capability_handlers()["caption.burn"](
                envelope, {"source": {"uri": "input.mp4"}},
            )
            submitted = json.loads(requests[0].content)
            self.assertEqual(submitted["network"]["allowed_domains"], ["cdn.example.test"])
            self.assertEqual(submitted["environment"]["VIDEO_PLUGIN_INPUT"], "/workspace/input.json")
            self.assertEqual(result["uri"], "https://cdn.example.test/result.mp4")
        await async_client.aclose()
