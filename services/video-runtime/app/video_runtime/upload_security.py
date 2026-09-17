from __future__ import annotations

import hashlib
import hmac
import os


def sign_uploaded_file(user_id: str, kind: str, url: str) -> str:
    """Sign a BFF upload so it can only be attached by the same user."""
    secret = os.getenv(
        "VIDEO_CAPABILITY_GRANT_SECRET",
        "local-video-upload-receipt-secret-32b",
    ).encode()
    return hmac.new(
        secret,
        f"{user_id}\n{kind}\n{url}".encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_uploaded_file(
    user_id: str, kind: str, url: str, receipt: str,
) -> bool:
    return hmac.compare_digest(receipt, sign_uploaded_file(user_id, kind, url))
