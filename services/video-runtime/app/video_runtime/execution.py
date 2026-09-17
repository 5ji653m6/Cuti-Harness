from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from .plugins import PluginContext, VideoPluginRegistry
from .security import CapabilityExecutionEnvelope, CapabilityGrantSigner
from app.capabilities.models import canonical_capability_id


AuditSink = Callable[[str, dict[str, Any]], Awaitable[None]]
Execution = Callable[[CapabilityExecutionEnvelope], Awaitable[Any]]


async def _discard_audit(_event: str, _payload: dict[str, Any]) -> None:
    return None


class CapabilityExecutionGateway:
    """Single checked entrance for providers, Skills, sandbox and media operators."""

    def __init__(
        self,
        signer: CapabilityGrantSigner,
        plugins: VideoPluginRegistry,
        audit: AuditSink = _discard_audit,
    ) -> None:
        self._signer = signer
        self._plugins = plugins
        self._audit = audit
        self._semaphores: dict[tuple[str, str], asyncio.Semaphore] = {}

    @property
    def plugins(self) -> VideoPluginRegistry:
        return self._plugins

    async def execute(
        self,
        *,
        grant_token: str,
        project_id: str,
        session_id: str,
        user_id: str,
        plugin_id: str,
        capability: str,
        operation: Execution,
        cancellation_id: str | None = None,
        report_remote_operation: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> Any:
        envelope = self._signer.verify(
            grant_token,
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            plugin_id=plugin_id,
            capability=capability,
        )
        envelope = CapabilityExecutionEnvelope(
            envelope.grant, cancellation_id, report_remote_operation,
        )
        loaded = self._plugins.get(plugin_id)
        declared = set(loaded.manifest.contributions.capabilities)
        if canonical_capability_id(capability) not in declared:
            raise PermissionError(f"plugin does not declare capability: {capability}")
        granted_domains = set(envelope.grant.allowed_domains)
        declared_domains = set(loaded.manifest.permissions.network_domains)
        if not granted_domains <= declared_domains:
            raise PermissionError("grant contains a domain not declared by the plugin")
        if envelope.grant.max_cost_usd > loaded.manifest.permissions.max_cost_usd:
            raise PermissionError("grant cost exceeds the plugin manifest ceiling")

        context = PluginContext(project_id=project_id, values={
            "session_id": session_id,
            "user_id": user_id,
            "audit_id": envelope.grant.audit_id,
        })
        key = (project_id, plugin_id)
        semaphore = self._semaphores.setdefault(
            key, asyncio.Semaphore(envelope.grant.max_concurrency),
        )
        await self._audit("capability.started", self._audit_payload(envelope))
        try:
            async with semaphore:
                await loaded.implementation.before_execute(context, envelope)
                result = await self._run_with_retries(operation, envelope)
                result = await loaded.implementation.after_execute(context, result)
            await self._audit("capability.completed", self._audit_payload(envelope))
            return result
        except BaseException as exc:
            await self._audit("capability.failed", {
                **self._audit_payload(envelope),
                "error_type": type(exc).__name__,
            })
            raise

    @staticmethod
    async def _run_with_retries(operation: Execution, envelope: CapabilityExecutionEnvelope) -> Any:
        last_error: BaseException | None = None
        for attempt in range(envelope.grant.max_retries + 1):
            try:
                async with asyncio.timeout(envelope.grant.timeout_seconds):
                    return await operation(envelope)
            except (asyncio.TimeoutError, ConnectionError) as exc:
                last_error = exc
                if attempt == envelope.grant.max_retries:
                    raise
        assert last_error is not None
        raise last_error

    @staticmethod
    def _audit_payload(envelope: CapabilityExecutionEnvelope) -> dict[str, Any]:
        grant = envelope.grant
        return {
            "audit_id": grant.audit_id,
            "project_id": grant.project_id,
            "session_id": grant.session_id,
            "user_id": grant.user_id,
            "plugin_id": grant.plugin_id,
            "capability": grant.capability,
            "idempotency_key": grant.idempotency_key,
            "cancellation_id": envelope.cancellation_id,
        }
