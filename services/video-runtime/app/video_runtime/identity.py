from __future__ import annotations

import hmac
import os
from typing import Protocol

from fastapi import HTTPException, Request


class IdentityResolver(Protocol):
    async def resolve(self, request: Request) -> tuple[str, str | None]: ...


class ServiceOrLocalIdentityResolver:
    """Fail-closed service identity in production, convenient single-user identity locally."""

    async def resolve(self, request: Request) -> tuple[str, str | None]:
        expected = os.getenv("VIDEO_RUNTIME_SERVICE_TOKEN", "").strip()
        environment = os.getenv("VIDEO_RUNTIME_ENVIRONMENT", "development").lower()
        authorization = request.headers.get("Authorization", "")
        user_id = request.headers.get("X-Video-User-Id", "").strip()
        session_id = request.headers.get("X-Video-Session-Id") or None
        if expected and authorization:
            supplied = authorization.removeprefix("Bearer ")
            if not hmac.compare_digest(supplied, expected):
                raise HTTPException(status_code=401, detail="invalid video runtime service token")
            if not user_id:
                raise HTTPException(status_code=400, detail="X-Video-User-Id is required")
            return user_id, session_id
        if expected and environment == "production":
            raise HTTPException(status_code=401, detail="video runtime service token is required")
        if environment == "production":
            raise HTTPException(
                status_code=503,
                detail="VIDEO_RUNTIME_SERVICE_TOKEN or a production identity adapter is required",
            )
        return user_id or os.getenv("VIDEO_RUNTIME_LOCAL_USER_ID", "local-user"), session_id
