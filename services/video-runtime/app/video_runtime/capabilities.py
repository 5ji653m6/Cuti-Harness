from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .execution import CapabilityExecutionGateway
from .security import CapabilityExecutionEnvelope
from app.capabilities.models import canonical_capability_id


CapabilityOperation = Callable[[CapabilityExecutionEnvelope, dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class RegisteredCapability:
    plugin_id: str
    capability: str
    operation: CapabilityOperation


class RuntimeCapabilityRegistry:
    """Dispatches every plugin capability through the checked execution gateway."""

    def __init__(self, gateway: CapabilityExecutionGateway) -> None:
        self._gateway = gateway
        self._handlers: dict[str, RegisteredCapability] = {}

    @property
    def gateway(self) -> CapabilityExecutionGateway:
        return self._gateway

    def describe(self, capability: str) -> RegisteredCapability:
        entry = self._handlers.get(canonical_capability_id(capability))
        if entry is None:
            raise LookupError(f"capability is not registered: {capability}")
        return entry

    def register(
        self,
        *,
        plugin_id: str,
        capability: str,
        operation: CapabilityOperation,
    ) -> Callable[[], None]:
        if capability in self._handlers:
            raise ValueError(f"capability is already registered: {capability}")
        loaded = self._gateway.plugins.get(plugin_id)
        if canonical_capability_id(capability) not in loaded.manifest.contributions.capabilities:
            raise ValueError(f"plugin does not declare capability: {capability}")
        entry = RegisteredCapability(plugin_id, capability, operation)
        self._handlers[capability] = entry

        def dispose() -> None:
            if self._handlers.get(capability) is entry:
                del self._handlers[capability]

        return dispose

    async def execute(
        self,
        *,
        grant_token: str,
        project_id: str,
        session_id: str,
        user_id: str,
        capability: str,
        payload: dict[str, Any],
        cancellation_id: str | None = None,
        report_remote_operation: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> Any:
        entry = self.describe(capability)

        async def operation(envelope: CapabilityExecutionEnvelope) -> Any:
            return await entry.operation(envelope, payload)

        return await self._gateway.execute(
            grant_token=grant_token,
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            plugin_id=entry.plugin_id,
            capability=capability,
            operation=operation,
            cancellation_id=cancellation_id,
            report_remote_operation=report_remote_operation,
        )
