"""Loguru setup: console, rotating files, and a SQLite sink."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from app.config.settings import Settings

_KNOWN_EXTRA = {
    "job_id",
    "document_id",
    "stage",
    "user_id",
    "user_email",
    "role",
    "session_id",
    "correlation_id",
}

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    level           TEXT    NOT NULL,
    logger_name     TEXT,
    function        TEXT,
    line            INTEGER,
    message         TEXT    NOT NULL,
    job_id          TEXT,
    document_id     TEXT,
    stage           TEXT,
    user_id         TEXT,
    user_email      TEXT,
    role            TEXT,
    session_id      TEXT,
    correlation_id  TEXT,
    thread          TEXT,
    exception       TEXT,
    extra_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_job         ON logs(job_id);
CREATE INDEX IF NOT EXISTS idx_logs_document    ON logs(document_id);
CREATE INDEX IF NOT EXISTS idx_logs_level       ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_time        ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_user        ON logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_correlation ON logs(correlation_id);
"""

_configured = False
_db_path: Optional[Path] = None
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    """Open (or reuse) the logs SQLite connection on the enqueue thread."""
    global _conn
    if _conn is None:
        if _db_path is None:
            raise RuntimeError("setup_logging() must be called before writing SQLite logs.")
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_db_path), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA synchronous=NORMAL;")
        _conn.execute("PRAGMA busy_timeout=5000;")
        _conn.executescript(_CREATE_SQL)
        _conn.execute("DELETE FROM logs WHERE timestamp < date('now','-14 days');")
        _conn.commit()
    return _conn


def _sqlite_sink(message) -> None:
    record = message.record
    extra = record.get("extra") or {}
    leftover = {k: v for k, v in extra.items() if k not in _KNOWN_EXTRA and not k.startswith("_")}
    exc = record.get("exception")
    ts = record["time"]
    if ts.tzinfo is None:
        ts_iso = ts.replace(tzinfo=timezone.utc).isoformat()
    else:
        ts_iso = ts.astimezone(timezone.utc).isoformat()

    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO logs (
            timestamp, level, logger_name, function, line, message,
            job_id, document_id, stage, user_id, user_email, role,
            session_id, correlation_id, thread, exception, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_iso,
            record["level"].name,
            record.get("name"),
            record.get("function"),
            record.get("line"),
            record.get("message"),
            extra.get("job_id"),
            extra.get("document_id"),
            extra.get("stage"),
            extra.get("user_id"),
            extra.get("user_email"),
            extra.get("role"),
            extra.get("session_id"),
            extra.get("correlation_id"),
            str(record["thread"].name) if record.get("thread") else None,
            str(exc) if exc else None,
            json.dumps(leftover, default=str) if leftover else None,
        ),
    )
    conn.commit()


def reset_logging_state() -> None:
    """Test helper: drop sinks and close the SQLite connection."""
    global _configured, _db_path, _conn
    logger.remove()
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None
    _db_path = None
    _configured = False


def setup_logging(settings: Settings) -> None:
    """Configure loguru sinks once. Safe to call again (no-op if already set up)."""
    global _configured, _db_path
    if _configured:
        return

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    _db_path = Path(settings.log_db_path)

    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, backtrace=True, diagnose=False)
    logger.add(
        str(settings.log_file_path),
        level=settings.log_level,
        rotation="10 MB",
        retention="14 days",
        enqueue=True,
    )
    logger.add(
        str(settings.error_file_path),
        level="WARNING",
        rotation="10 MB",
        retention="30 days",
        enqueue=True,
    )
    logger.add(_sqlite_sink, level=settings.log_level, enqueue=True)
    _configured = True
