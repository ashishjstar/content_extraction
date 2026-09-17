"""Tests for centralized AppError / HTTP exception handlers."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import AppError, NotFoundError
from app.core.logging_middleware import LoggingContextMiddleware


def _test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LoggingContextMiddleware)
    register_exception_handlers(app)

    @app.get("/app-error")
    def app_error():
        raise NotFoundError("No uploaded file found.", code="DOCUMENT_NOT_FOUND")

    @app.get("/http-error")
    def http_error():
        raise HTTPException(status_code=400, detail="Unsupported file type '.txt'.")

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-internal-path-must-not-leak")

    return app


def test_app_error_returns_envelope_and_correlation_id():
    client = TestClient(_test_app())
    cid = "11111111-1111-1111-1111-111111111111"
    response = client.get("/app-error", headers={"X-Correlation-ID": cid})
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert body["error"]["message"] == "No uploaded file found."
    assert body["meta"]["correlationId"] == cid
    assert response.headers.get("X-Correlation-ID") == cid


def test_http_exception_mapped_to_envelope():
    client = TestClient(_test_app())
    response = client.get("/http-error")
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert "Unsupported file type" in body["error"]["message"]
    assert body["error"]["code"] == "BAD_REQUEST"
    assert "correlationId" in body["meta"]


def test_unhandled_exception_does_not_leak_message():
    client = TestClient(_test_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "secret-internal-path-must-not-leak" not in str(body)
    assert "unexpected server error" in body["error"]["message"].lower()
