"""Tests for loguru file + SQLite sink setup."""

import sqlite3
import time
from pathlib import Path

from loguru import logger

from app.config.settings import Settings
from app.core.logging_config import reset_logging_state, setup_logging


def _wait_for_row(db_path: Path, timeout: float = 3.0) -> list:
    deadline = time.time() + timeout
    while time.time() < deadline:
        logger.complete()
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT level, message, job_id, document_id, stage, user_id, correlation_id FROM logs"
            ).fetchall()
            conn.close()
            if rows:
                return rows
        time.sleep(0.05)
    return []


def test_setup_logging_writes_sqlite_row_with_context(tmp_path):
    reset_logging_state()
    settings = Settings(
        log_dir=tmp_path / "logs",
        log_file_path=tmp_path / "logs" / "app.log",
        error_file_path=tmp_path / "logs" / "error.log",
        log_db_path=tmp_path / "logs" / "logs.db",
        log_level="DEBUG",
    )
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(settings)

    with logger.contextualize(
        job_id="job-1",
        document_id="doc-1",
        stage="parse",
        user_id="user-1",
        correlation_id="cid-1",
    ):
        logger.info("pipeline started")

    rows = _wait_for_row(settings.log_db_path)
    assert rows, "expected a row in logs.db"
    _level, message, job_id, document_id, stage, user_id, correlation_id = rows[-1]
    assert "pipeline started" in message
    assert job_id == "job-1"
    assert document_id == "doc-1"
    assert stage == "parse"
    assert user_id == "user-1"
    assert correlation_id == "cid-1"
    assert (tmp_path / "logs" / "app.log").exists()

    reset_logging_state()


def test_setup_logging_is_idempotent(tmp_path):
    reset_logging_state()
    settings = Settings(
        log_dir=tmp_path / "logs",
        log_file_path=tmp_path / "logs" / "app.log",
        error_file_path=tmp_path / "logs" / "error.log",
        log_db_path=tmp_path / "logs" / "logs.db",
    )
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(settings)
    setup_logging(settings)
    logger.info("once")
    rows = _wait_for_row(settings.log_db_path)
    assert len(rows) == 1
    reset_logging_state()
