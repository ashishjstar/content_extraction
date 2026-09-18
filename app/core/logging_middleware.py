"""HTTP middleware: correlation id + optional JWT context for loguru."""

from __future__ import annotations

import uuid
from typing import Optional

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config.settings import get_settings
from app.services.auth.token_service import TokenService


def _decode_bearer(request: Request) -> dict:
    """Return JWT claims if a valid Bearer token is present; never raises."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return {}
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return {}
    try:
        settings = get_settings()
        decoded = TokenService(settings).decode_access_token(token)
        return {
            "user_id": decoded.get("sub"),
            "user_email": decoded.get("email"),
            "role": decoded.get("role"),
            "session_id": decoded.get("sid"),
        }
    except Exception:
        return {}


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """Stamp every request with correlation_id and optional user fields."""

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        claims = _decode_bearer(request)
        user_id: Optional[str] = claims.get("user_id")
        user_email: Optional[str] = claims.get("user_email")
        role: Optional[str] = claims.get("role")
        session_id: Optional[str] = claims.get("session_id")

        request.state.correlation_id = correlation_id
        request.state.user_id = user_id
        request.state.user_email = user_email
        request.state.role = role
        request.state.session_id = session_id

        with logger.contextualize(
            correlation_id=correlation_id,
            user_id=user_id,
            user_email=user_email,
            role=role,
            session_id=session_id,
            stage="http",
        ):
            response = await call_next(request)

        response.headers["X-Correlation-ID"] = correlation_id
        return response
