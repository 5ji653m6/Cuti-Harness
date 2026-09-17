from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field


class CapabilityGrant(BaseModel):
    """Server-issued authority for exactly one nested runtime execution."""

    project_id: str
    session_id: str
    user_id: str
    plugin_id: str
    capability: str
    allowed_capabilities: list[str]
    allowed_domains: list[str] = Field(default_factory=list)
    max_cost_usd: float = Field(ge=0)
    timeout_seconds: int = Field(gt=0, le=86_400)
    max_concurrency: int = Field(default=1, gt=0, le=64)
    max_retries: int = Field(default=0, ge=0, le=10)
    idempotency_key: str
    audit_id: str
    nonce: str
    expires_at: int


class InvalidCapabilityGrant(PermissionError):
    pass


@dataclass(frozen=True)
class CapabilityExecutionEnvelope:
    grant: CapabilityGrant
    cancellation_id: str | None = None
    report_remote_operation: Callable[[str, str], Awaitable[None]] | None = None

    def assert_domain(self, domain: str) -> None:
        if domain not in self.grant.allowed_domains:
            raise InvalidCapabilityGrant(f"network domain is not granted: {domain}")


class CapabilityGrantSigner:
    """HMAC reference signer. Production deployments may replace it with KMS/JWT."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("capability grant secret must contain at least 32 bytes")
        self._secret = secret

    def issue(self, grant: CapabilityGrant) -> str:
        payload = self._encode(grant.model_dump(mode="json"))
        signature = self._sign(payload)
        return f"v1.{payload}.{signature}"

    def verify(
        self,
        token: str,
        *,
        project_id: str,
        session_id: str,
        user_id: str,
        plugin_id: str,
        capability: str,
        now_epoch: int | None = None,
    ) -> CapabilityExecutionEnvelope:
        try:
            version, payload, signature = token.split(".", 2)
        except ValueError as exc:
            raise InvalidCapabilityGrant("malformed capability grant") from exc
        if version != "v1" or not hmac.compare_digest(signature, self._sign(payload)):
            raise InvalidCapabilityGrant("invalid capability grant signature")
        try:
            grant = CapabilityGrant.model_validate(json.loads(self._decode(payload)))
        except Exception as exc:
            raise InvalidCapabilityGrant("invalid capability grant payload") from exc
        expected = (project_id, session_id, user_id, plugin_id, capability)
        actual = (grant.project_id, grant.session_id, grant.user_id, grant.plugin_id, grant.capability)
        if actual != expected:
            raise InvalidCapabilityGrant("capability grant identity does not match execution")
        if capability not in grant.allowed_capabilities:
            raise InvalidCapabilityGrant(f"capability is not granted: {capability}")
        if grant.expires_at <= (int(time.time()) if now_epoch is None else now_epoch):
            raise InvalidCapabilityGrant("capability grant expired")
        return CapabilityExecutionEnvelope(grant=grant)

    def _sign(self, payload: str) -> str:
        digest = hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()
        return self._encode_bytes(digest)

    @staticmethod
    def _encode(value: dict[str, Any]) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return CapabilityGrantSigner._encode_bytes(raw)

    @staticmethod
    def _encode_bytes(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode(value: str) -> str:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
