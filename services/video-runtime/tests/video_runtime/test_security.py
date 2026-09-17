from __future__ import annotations

import time
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.video_runtime.security import (
    CapabilityGrant,
    CapabilityGrantSigner,
    InvalidCapabilityGrant,
)


def _grant(**changes) -> CapabilityGrant:
    values = {
        "project_id": "project-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "plugin_id": "provider.seedance",
        "capability": "video.generate",
        "allowed_capabilities": ["video.generate"],
        "allowed_domains": ["api.provider.test"],
        "max_cost_usd": 2,
        "timeout_seconds": 60,
        "idempotency_key": "generate-1",
        "audit_id": "audit-1",
        "nonce": "nonce-1",
        "expires_at": int(time.time()) + 60,
    }
    values.update(changes)
    return CapabilityGrant(**values)


class CapabilityGrantTest(unittest.TestCase):
    def test_signed_grant_is_bound_to_all_execution_identities(self):
        signer = CapabilityGrantSigner(b"a sufficiently long server-owned secret")
        token = signer.issue(_grant())
        envelope = signer.verify(
            token,
            project_id="project-1",
            session_id="session-1",
            user_id="user-1",
            plugin_id="provider.seedance",
            capability="video.generate",
        )
        envelope.assert_domain("api.provider.test")
        with self.assertRaises(InvalidCapabilityGrant):
            envelope.assert_domain("attacker.invalid")
        with self.assertRaises(InvalidCapabilityGrant):
            signer.verify(
                token,
                project_id="another-project",
                session_id="session-1",
                user_id="user-1",
                plugin_id="provider.seedance",
                capability="video.generate",
            )


    def test_tampered_or_expired_grants_are_rejected(self):
        signer = CapabilityGrantSigner(b"a sufficiently long server-owned secret")
        token = signer.issue(_grant())
        with self.assertRaises(InvalidCapabilityGrant):
            signer.verify(
                token[:-1] + ("A" if token[-1] != "A" else "B"),
                project_id="project-1", session_id="session-1", user_id="user-1",
                plugin_id="provider.seedance", capability="video.generate",
            )
        expired = signer.issue(_grant(expires_at=1))
        with self.assertRaises(InvalidCapabilityGrant):
            signer.verify(
                expired,
                project_id="project-1", session_id="session-1", user_id="user-1",
                plugin_id="provider.seedance", capability="video.generate",
                now_epoch=2,
            )
