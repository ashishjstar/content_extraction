import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_upload_pdf(tmp_path):
    # Create a mock PDF file
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"%PDF-1.4 mock content")

    with open(test_file, "rb") as f:
        response = client.post(
            "/documents/upload",
            files={"file": ("test.pdf", f, "application/pdf")}
        )
    
    assert response.status_code == 200
    data = response.json()
    assert "document_id" in data
    assert data["filename"] == "test.pdf"
    assert data["file_type"] == "pdf"

def test_upload_invalid_file(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Not a pdf")

    with open(test_file, "rb") as f:
        response = client.post(
            "/documents/upload",
            files={"file": ("test.txt", f, "text/plain")}
        )
    
    assert response.status_code == 400
    body = response.json()
    message = body.get("error", {}).get("message") or body.get("detail") or ""
    assert "Unsupported file type" in message
