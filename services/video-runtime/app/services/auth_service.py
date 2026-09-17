import logging
import secrets
from typing import Optional

from fastapi import Header, Security
from fastapi.security import HTTPBearer, APIKeyCookie, HTTPAuthorizationCredentials

from app.config import settings
from app.exceptions import BusinessException, BusinessExceptionCode

logger = logging.getLogger(__name__)

security = APIKeyCookie(name="token", auto_error=False)
service_security = HTTPBearer(auto_error=False)


class AuthService:
    """Local-user and optional service-bearer identity. No JWT product login."""

    @staticmethod
    def _local_user_id() -> str:
        uid = (getattr(settings, "CUTI_SERVICE_DEFAULT_USER_ID", None) or "").strip()
        return uid or "local-user"

    async def get_current_user(self, token: Optional[str] = Security(security)) -> str:
        del token
        return self._local_user_id()

    def _validate_service_credentials(
        self,
        credentials: Optional[HTTPAuthorizationCredentials],
    ) -> None:
        if not settings.CUTI_SERVICE_ENABLED:
            raise BusinessException(
                BusinessExceptionCode.PERMISSION_DENIED,
                "Service access is disabled",
            )
        if not settings.CUTI_SERVICE_TOKEN:
            raise BusinessException(
                BusinessExceptionCode.CONFIGURATION_ERROR,
                "Service token is not configured",
            )
        if not credentials or credentials.scheme.lower() != "bearer":
            raise BusinessException(
                BusinessExceptionCode.UNAUTHORIZED,
                "Missing bearer service token",
            )
        if not secrets.compare_digest(credentials.credentials, settings.CUTI_SERVICE_TOKEN):
            raise BusinessException(
                BusinessExceptionCode.PERMISSION_DENIED,
                "Invalid service token",
            )

    async def get_current_user_or_service_user(
        self,
        token: Optional[str] = Security(security),
        credentials: Optional[HTTPAuthorizationCredentials] = Security(service_security),
        service_user_id: Optional[str] = Header(None, alias="X-Cuti-Service-User-Id"),
    ) -> str:
        """Resolve local-user, or a trusted service caller when a bearer token is set."""
        del token
        local_uid = self._local_user_id()
        if credentials is not None:
            self._validate_service_credentials(credentials)
            resolved = (service_user_id or local_uid).strip()
            if not resolved:
                raise BusinessException(
                    BusinessExceptionCode.INVALID_REQUEST_PARAMETERS,
                    "Service requests must provide X-Cuti-Service-User-Id or CUTI_SERVICE_DEFAULT_USER_ID",
                )
            return resolved
        return (service_user_id or local_uid).strip()


auth_service = AuthService()
