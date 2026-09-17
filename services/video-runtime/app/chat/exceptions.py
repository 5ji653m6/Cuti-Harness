"""Compatibility exports for the application's canonical exception types.

Using one class identity ensures exceptions raised by mounted chat and V2
routes are handled by the root FastAPI application's registered handlers.
"""

from app.exceptions import BusinessException, BusinessExceptionCode

__all__ = ["BusinessException", "BusinessExceptionCode"]
