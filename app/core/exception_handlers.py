"""Central FastAPI exception handlers → ApiErrorResponse + loguru."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.schemas.auth import ApiErrorDetail, ApiErrorResponse, ApiFieldError, ApiMeta


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or request.headers.get(
        "X-Correlation-ID", "unknown"
    )


def _error_json(
    *,
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    field_errors: Optional[list[ApiFieldError]] = None,
    retry_after: Optional[int] = None,
    clear_refresh_cookie: bool = False,
) -> JSONResponse:
    body = ApiErrorResponse(
        success=False,
        error=ApiErrorDetail(
            code=code,
            message=message,
            fieldErrors=field_errors or None,
        ),
        meta=ApiMeta(correlationId=correlation_id),
    )
    headers = {}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    response = JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        headers=headers or None,
    )
    if clear_refresh_cookie:
        response.delete_cookie(
            key="refresh_token",
            path="/api/v1/auth",
            httponly=True,
            samesite="lax",
        )
    response.headers["X-Correlation-ID"] = correlation_id
    return response


def _http_code_for_status(status_code: int) -> str:
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
    }
    return mapping.get(status_code, "HTTP_ERROR")


def _detail_to_message(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "Request validation failed."
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "Request failed.")
    return "Request failed."


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers in specificity order (AppError → validation → HTTP → catch-all)."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        cid = _correlation_id(request)
        if exc.status_code >= 500:
            logger.exception("Application error: {}", exc.message)
        else:
            logger.warning("Application error {}: {}", exc.code, exc.message)
        return _error_json(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            correlation_id=cid,
            field_errors=exc.field_errors or None,
            retry_after=exc.retry_after,
            clear_refresh_cookie=exc.clear_refresh_cookie,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        cid = _correlation_id(request)
        field_errors: list[ApiFieldError] = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            field_errors.append(
                ApiFieldError(
                    field=loc or "body",
                    code="VALIDATION_ERROR",
                    message=err.get("msg") or "Invalid value.",
                )
            )
        logger.warning("Validation error on {}: {}", request.url.path, exc.errors())
        return _error_json(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="One or more fields are invalid.",
            correlation_id=cid,
            field_errors=field_errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        cid = _correlation_id(request)
        message = _detail_to_message(exc.detail)
        code = _http_code_for_status(exc.status_code)
        logger.warning("HTTP {}: {}", exc.status_code, message)
        return _error_json(
            status_code=exc.status_code,
            code=code,
            message=message,
            correlation_id=cid,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        cid = _correlation_id(request)
        logger.exception("Unhandled error processing request {}: {}", request.url, exc)
        return _error_json(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred. Please try again later.",
            correlation_id=cid,
        )
