from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.video_runtime.api import _identity, get_runtime
from app.video_runtime.checkpoint_coordinator import CheckpointCoordinator
from app.video_runtime.deepseek_bff import get_deepseek_client
from app.video_runtime.deepseek_client import DeepSeekHarnessClient, DeepSeekHarnessError
from app.video_runtime.session_context import router


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_compaction_uses_native_command_and_checks_handler_outcome(success):
    def handle(request):
        body = json.loads(request.content)
        assert request.url.path == "/api/commands/execute"
        assert body["payload"]["args"] == {"agentId": "s", "line": "/compact", "images": []}
        assert request.extensions["timeout"]["read"] == 300
        return httpx.Response(200, json={"rpcId": body["rpcId"], "result": {
            "ok": True, "value": {"commandId": "c", "result": {
                "kind": "success" if success else "error", "text": "summary outcome",
            }},
        }})
    async with httpx.AsyncClient(base_url="http://harness", transport=httpx.MockTransport(handle)) as http:
        client = DeepSeekHarnessClient("http://harness", client=http)
        if success:
            assert (await client.compact_session("s"))["command_id"] == "c"
        else:
            with pytest.raises(DeepSeekHarnessError, match="summary outcome"):
                await client.compact_session("s")


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_project,status", [("p", 200), ("other", 403)])
async def test_project_compaction_cannot_rebind_foreign_session(bound_project, status):
    runtime = SimpleNamespace(repo=SimpleNamespace(
        get_project=AsyncMock(return_value=SimpleNamespace(id="p", user_id="u")),
        project_for_session=AsyncMock(return_value=(SimpleNamespace(id=bound_project), None)),
    ), session_control_locks={})
    harness = SimpleNamespace(compact_session=AsyncMock(return_value={"status": "completed"}))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_identity] = lambda: ("u", None)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_deepseek_client] = lambda: harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://runtime") as http:
        response = await http.post("/api/video/projects/p/sessions/s/compact")
    assert response.status_code == status
    assert harness.compact_session.await_count == (1 if status == 200 else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow,compact_fails", [(True, False), (True, True), (False, False)])
async def test_checkpoint_overflow_compacts_before_bounded_redelivery(overflow, compact_fails):
    checkpoint = SimpleNamespace(id="c", project_id="p", session_id="s", delivery_attempts=1,
                                 updated_at=datetime.fromtimestamp(0, timezone.utc))
    history = {"events": [
        {"event": {"type": "user/message", "time": 1, "data": {"content": [
            {"type": "text", "text": "CUTI_VIDEO_CHECKPOINT_V1 c"},
        ]}}},
        {"event": {"type": "turn/end", "time": 2, "data": {"reason": {"error": {
            "code": "CONTEXT_WINDOW_EXCEEDED" if overflow else "OTHER",
        }}}}},
    ]}
    operations = []
    async def compact(_session):
        operations.append("compact")
        if compact_fails:
            raise DeepSeekHarnessError("summary failed")
    async def redeliver(*args, **kwargs):
        operations.append("redeliver")
        assert kwargs["expected_attempt"] == 1
        if compact_fails:
            assert "summary failed" in args[1]
    runtime = SimpleNamespace(session_control_locks={}, repo=SimpleNamespace(
        list_planning_checkpoints=AsyncMock(return_value=[checkpoint]),
        fail_checkpoint_delivery=redeliver,
    ))
    harness = SimpleNamespace(history=AsyncMock(return_value=history), compact_session=compact)
    await CheckpointCoordinator(runtime, harness).reconcile_finished_turns()
    assert operations == (["compact", "redeliver"] if overflow else ["redeliver"])
