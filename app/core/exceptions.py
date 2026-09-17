"""Domain exceptions raised by services; FastAPI handlers map them to ApiErrorResponse."""

from __future__ import annotations

from typing import Optional

from app.schemas.auth import ApiFieldError


class AppError(Exception):
    """Safe, client-facing application error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: Optional[list[ApiFieldError]] = None,
        retry_after: Optional[int] = None,
        clear_refresh_cookie: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or []
        self.retry_after = retry_after
        self.clear_refresh_cookie = clear_refresh_cookie


class NotFoundError(AppError):
    """Resource was not found (HTTP 404)."""

    def __init__(self, message: str, code: str = "NOT_FOUND"):
        super().__init__(status_code=404, code=code, message=message)
