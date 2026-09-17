from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx

from ..security import CapabilityExecutionEnvelope
from .models import BaseVideoPlugin, VideoPluginManifest


class SandboxWorkerError(RuntimeError):
    pass


class SandboxWorkerClient:
    TERMINAL = {"succeeded", "failed", "timed_out", "cancelled"}

    def __init__(self, base_url: str, token: str = "", client: httpx.AsyncClient | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=30,
        )

    @classmethod
    def from_environment(cls) -> "SandboxWorkerClient":
        return cls(
            os.getenv("VIDEO_SANDBOX_WORKER_URL", "http://sandbox-worker:8080"),
            os.getenv("VIDEO_SANDBOX_WORKER_TOKEN", ""),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def execute(self, request: dict[str, Any], cancellation_id: str | None) -> dict[str, Any]:
        response = await self._client.post("/v1/runs", json=request)
        response.raise_for_status()
        run_id = str(response.json()["run_id"])
        try:
            while True:
                response = await self._client.get(f"/v1/runs/{run_id}")
                response.raise_for_status()
                result = response.json()
                if result.get("status") in self.TERMINAL:
                    if result["status"] != "succeeded":
                        raise SandboxWorkerError(
                            result.get("error") or f"sandbox run {result['status']}",
                        )
                    return result
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            await self._client.post(f"/v1/runs/{run_id}/cancel")
            raise


class SandboxedVideoPlugin(BaseVideoPlugin):
    """Executes an untrusted plugin bundle through the imported Cuti Sandbox Worker."""

    def __init__(
        self,
        manifest: VideoPluginManifest,
        bundle_root: Path,
        worker: SandboxWorkerClient | None = None,
    ) -> None:
        self.manifest = manifest
        self.bundle_root = bundle_root.resolve()
        self.worker = worker or SandboxWorkerClient.from_environment()

    def capability_handlers(self):
        return {
            capability: self._execute_capability
            for capability in self.manifest.contributions.capabilities
        }

    async def on_unload(self, _context) -> None:
        await self.worker.close()

    async def _execute_capability(
        self,
        envelope: CapabilityExecutionEnvelope,
        payload: dict[str, Any],
    ) -> Any:
        sandbox = self.manifest.sandbox_runtime
        if sandbox is None:
            raise SandboxWorkerError("plugin has no sandbox runtime")
        for domain in self.manifest.permissions.network_domains:
            envelope.assert_domain(domain)
        inputs = []
        for path in sorted(self.bundle_root.rglob("*")):
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(self.bundle_root).parts):
                inputs.append({
                    "path": f"plugin/{path.relative_to(self.bundle_root).as_posix()}",
                    "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                })
        invocation = {
            "protocol_version": 1,
            "identity": {
                "project_id": envelope.grant.project_id,
                "session_id": envelope.grant.session_id,
                "user_id": envelope.grant.user_id,
                "plugin_id": envelope.grant.plugin_id,
                "capability": envelope.grant.capability,
            },
            "limits": {
                "max_cost_usd": envelope.grant.max_cost_usd,
                "timeout_seconds": envelope.grant.timeout_seconds,
                "allowed_domains": envelope.grant.allowed_domains,
            },
            "idempotency_key": envelope.grant.idempotency_key,
            "payload": payload,
        }
        inputs.append({
            "path": "input.json",
            "content_base64": base64.b64encode(
                json.dumps(invocation, ensure_ascii=False).encode("utf-8"),
            ).decode("ascii"),
        })
        environment = {
            "VIDEO_PLUGIN_INPUT": "/workspace/input.json",
            "VIDEO_PLUGIN_OUTPUT": "/workspace/output/result.json",
        }
        for name in self.manifest.permissions.credentials:
            value = os.getenv(name)
            if value:
                environment[name] = value
        result = await self.worker.execute({
            "image": sandbox.image,
            "command": ["python", f"/workspace/plugin/{sandbox.entrypoint}"],
            "inputs": inputs,
            "artifacts": ["output/result.json"],
            "timeout_seconds": min(sandbox.timeout_seconds, envelope.grant.timeout_seconds),
            "environment": environment,
            "network": {
                "mode": "allowlist" if envelope.grant.allowed_domains else "none",
                "allowed_domains": envelope.grant.allowed_domains,
            },
        }, envelope.cancellation_id)
        encoded = next(
            (item["content_base64"] for item in result.get("artifacts", [])
             if item.get("path") == "output/result.json"),
            None,
        )
        if not encoded:
            raise SandboxWorkerError("sandbox plugin did not produce output/result.json")
        return json.loads(base64.b64decode(encoded, validate=True))
