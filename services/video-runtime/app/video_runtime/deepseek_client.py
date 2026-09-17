from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx


class DeepSeekHarnessError(RuntimeError):
    pass


class DeepSeekHarnessClient:
    """Typed transport used by the legacy Cuti BFF to control Harness Sessions."""

    def __init__(
        self,
        base_url: str,
        *,
        authorization: str | None = None,
        timeout_seconds: float = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        headers = {"Authorization": authorization} if authorization else None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_session(
        self,
        *,
        session_id: str | None = None,
        cwd: str | None = None,
        agent_preset: str | None = None,
    ) -> str:
        payload = {
            **({"sessionId": session_id} if session_id else {}),
            **({"cwd": cwd} if cwd else {}),
            **({"agentPreset": agent_preset} if agent_preset else {}),
        }
        result = await self.rpc("session.create", payload)
        value = result.get("sessionId")
        if not isinstance(value, str) or not value:
            raise DeepSeekHarnessError("session.create returned no sessionId")
        return value

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return the lightweight Harness Session catalog.

        The compatibility BFF uses this before binding a caller-supplied
        ``/create/{threadId}`` route.  ``session.create`` is intentionally
        idempotent in DeepSeek Harness, so it cannot distinguish a fresh route
        id from an existing, orphaned conversation by itself.
        """
        result = await self.rpc("session.list", {})
        items = result.get("items")
        if not isinstance(items, list):
            raise DeepSeekHarnessError("session.list returned no items")
        return [item for item in items if isinstance(item, dict)]

    async def prompt(
        self,
        session_id: str,
        text: str,
        *,
        mode: str = "queue",
        client_time_zone: str | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> None:
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for image in images or []:
            media_type = str(image.get("mediaType") or "")
            data = str(image.get("data") or "")
            if media_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"} or not data:
                continue
            part: dict[str, Any] = {"type": "image", "mediaType": media_type, "data": data}
            name = str(image.get("name") or "").strip()
            if name:
                part["name"] = name
            content.append(part)
        payload: dict[str, Any] = {
            "sessionId": session_id,
            "mode": mode,
            "content": content,
        }
        if client_time_zone:
            payload["clientTimeZone"] = client_time_zone
        result = await self.rpc("session.prompt", payload)
        if result.get("accepted") is not True:
            raise DeepSeekHarnessError("session.prompt was not accepted")

    async def history(
        self,
        session_id: str,
        *,
        before_sequence: int | None = None,
        max_messages: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"sessionId": session_id}
        if before_sequence is not None:
            payload["beforeSeq"] = before_sequence
        if max_messages is not None:
            payload["maxMessages"] = max_messages
        return await self.rpc("session.history", payload)

    async def cancel(self, session_id: str) -> None:
        result = await self.rpc("session.cancel", {"sessionId": session_id})
        if result.get("accepted") is not True:
            raise DeepSeekHarnessError("session.cancel was not accepted")

    async def compact_session(self, session_id: str) -> dict[str, Any]:
        """Compact an idle bound Session through the Harness command lifecycle.

        The command records its summary in the existing Session log. Busy,
        unavailable and failed summarization outcomes remain explicit errors.
        """
        result = await self.rpc("commands/execute", {"args": {
            "agentId": session_id, "line": "/compact", "images": [],
        }}, timeout_seconds=300)
        outcome = result.get("result") or {}
        if outcome.get("kind") != "success":
            raise DeepSeekHarnessError(
                str(outcome.get("text") or "Harness session compaction is unavailable"),
            )
        return {"session_id": session_id, "command_id": result.get("commandId"),
                "message": outcome.get("text", ""), "status": "completed"}

    async def rpc(
        self, method: str, payload: dict[str, Any], *, timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        rpc_id = str(uuid4())
        try:
            response = await self._client.post(
                f"/api/{method}",
                json={
                    "type": "client-request",
                    "rpcId": rpc_id,
                    "method": method,
                    "payload": payload,
                },
                **({"timeout": timeout_seconds} if timeout_seconds is not None else {}),
            )
        except httpx.RequestError as exc:
            raise DeepSeekHarnessError(f"{method} transport failed: {exc}") from exc
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("rpcId") != rpc_id:
            raise DeepSeekHarnessError(f"{method} returned an invalid RPC envelope")
        result = body.get("result")
        if not isinstance(result, dict):
            raise DeepSeekHarnessError(f"{method} returned no RPC result")
        if result.get("ok") is not True:
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            raise DeepSeekHarnessError(
                f"{method} failed: {error.get('code', 'unknown')}: "
                f"{error.get('message', 'unknown error')}",
            )
        value = result.get("value")
        if not isinstance(value, dict):
            raise DeepSeekHarnessError(f"{method} returned a non-object value")
        return value

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        async with self._client.stream("GET", "/api/events.mux") as response:
            response.raise_for_status()
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif not line and data_lines:
                    value = json.loads("\n".join(data_lines))
                    if isinstance(value, dict):
                        yield value
                    data_lines.clear()
