"""Local identity is always local-user; optional service bearer is for trusted callers."""
import pytest

from app.services.auth_service import AuthService
from app.config import settings


@pytest.fixture
def auth():
    return AuthService()


@pytest.mark.asyncio
async def test_no_token_returns_local_user(auth, monkeypatch):
    monkeypatch.setattr(settings, "CUTI_SERVICE_DEFAULT_USER_ID", None, raising=False)
    uid = await auth.get_current_user(token=None)
    assert uid == "local-user"


@pytest.mark.asyncio
async def test_configured_default_user_id(auth, monkeypatch):
    monkeypatch.setattr(settings, "CUTI_SERVICE_DEFAULT_USER_ID", "workspace-user", raising=False)
    uid = await auth.get_current_user(token=None)
    assert uid == "workspace-user"


@pytest.mark.asyncio
async def test_cookie_is_ignored(auth, monkeypatch):
    monkeypatch.setattr(settings, "CUTI_SERVICE_DEFAULT_USER_ID", "workspace-user", raising=False)
    uid = await auth.get_current_user(token="not-a-jwt")
    assert uid == "workspace-user"


@pytest.mark.asyncio
async def test_service_resolver_returns_local_user_without_bearer(auth, monkeypatch):
    monkeypatch.setattr(settings, "CUTI_SERVICE_DEFAULT_USER_ID", "workspace-user", raising=False)
    uid = await auth.get_current_user_or_service_user(
        token=None, credentials=None, service_user_id=None
    )
    assert uid == "workspace-user"


@pytest.mark.asyncio
async def test_service_resolver_honors_explicit_service_user(auth, monkeypatch):
    monkeypatch.setattr(settings, "CUTI_SERVICE_DEFAULT_USER_ID", "workspace-user", raising=False)
    uid = await auth.get_current_user_or_service_user(
        token=None, credentials=None, service_user_id="explicit-user"
    )
    assert uid == "explicit-user"
