# Logging Implementation Guide

Simple, traceable logging for the SOP Migration pipeline using **loguru** (already a dependency) with a **SQLite** sink. Every log line is automatically stamped with `job_id`, `document_id`, `stage`, and (when a user is logged in) `user_id` / `correlation_id` so a full pipeline run can be traced with one query.

**Status:** this is a design to implement. Services already call `loguru.logger`, but there is no `app/core/`, no file/SQLite sinks, and no `contextualize()` around the pipeline. Logs currently go to the console only.

## Goals

- One logging setup, configured once at startup — no per-file boilerplate.
- Capture every pipeline stage (parse → extract → AST → chunk → export).
- Attach the logged-in user to HTTP and extraction logs without rewriting extractors.
- Thread-safe, non-blocking persistence to SQLite (workers run in threads).
- Keep it minimal: no new dependencies, no external log services.

## Architecture

```
Browser (login) ──▶ /api/v1/auth/*     ──▶ auth.db  audit_events   (security trail)
                 └── Bearer on /sops…  ──▶ logs.db  (who did parse / tables / export)

services / API  ──▶  loguru.logger  ──▶  [ console sink   ]  (human-readable)
(self.logger)         │                  [ app.log        ]  (all levels, rotating)
                      │                  [ error.log      ]  (WARNING+ only, rotating)
                      │                  [ sqlite sink     ]  (structured, queryable)
                      │
            HTTP middleware: contextualize(user_id, correlation_id, stage="http")
            JobManager:      contextualize(job_id, document_id, user_id, stage=...)
            → fields flow into worker threads via asyncio.to_thread
```

Two logging stores stay **separate**:

| Store      | File                            | Purpose                                                           |
| ---------- | ------------------------------- | ----------------------------------------------------------------- |
| Auth audit | `data/auth.db` → `audit_events` | `LOGIN_SUCCEEDED`, `LOGIN_FAILED`, `LOGOUT` (already implemented) |
| App logs   | `data/logs/logs.db` → `logs`    | HTTP + extraction stages (this guide)                             |

Join them later with the same `correlation_id`. Do **not** write extraction logs into `auth.db`, and do **not** replace `audit_events` with `logs.db`.

Two file sinks by design: **`app.log`** captures everything at `log_level`, while **`error.log`** captures only `WARNING`+ so problems are visible without scanning the full log. Both use the same rotation/retention.

- **Single facade:** all existing `self.logger` / global `logger` calls keep working; only the sink config changes.
- **`enqueue=True`** on the file + SQLite sinks routes every record through loguru's one background thread → serialized, non-blocking writes (no `SQLITE_BUSY`).
- **`contextualize()`** stores context in a `contextvar`, which `asyncio.to_thread` copies into worker threads — so logs emitted deep in the parser/extractors carry the run identifiers automatically.
- **Job queue is a new asyncio task.** Middleware context dies when the upload request returns. Stamp `user_id` / `correlation_id` on `BatchJob` at enqueue time, then `contextualize` again in the worker.

## Current code vs what to add

| Already there                                                                      | Missing (implement this guide)                                |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `from loguru import logger` in most services                                       | `app/core/logging_config.py`                                  |
| `SOP_LOG_LEVEL` / `log_level` in settings                                          | `log_dir`, `log_file_path`, `error_file_path`, `log_db_path`  |
| `logger.exception` on job failure                                                  | `logger.contextualize(job_id, document_id, user_id, stage)`   |
| Frontend `ProtectedRoute` + Bearer on `frontend/src/lib/api.ts`                    | HTTP logging middleware                                       |
| `AuthStore.record_audit_event` + JWT (`sub`, `email`, `role`, `sid`)               | User fields on `BatchJob` so workers still know who uploaded  |
| SOP APIs (`/documents/upload`, `/jobs`, `/sops`) **not** auth-gated on the backend | Decode JWT if present; do not 401 from logging middleware     |
| `LoginError` / `SignupError` + `ApiErrorResponse` on auth routes                   | Shared `AppError` + central FastAPI handlers for **all** APIs |
| Catch-all `@app.exception_handler(Exception)` that returns `str(exc)`              | Safe client envelope; traceback only in logs                  |

`app/services/export/migration_exporter.py` still uses stdlib `logging.getLogger(__name__)`. Until it switches to loguru, export-stage lines will not hit `app.log` / SQLite.

Do **not** sprinkle `job_id=` / `user_id=` into every extractor. Bind context once (middleware + `JobManager`).

## File structure / changes

| File                                               | Change                                                                                                                                                             |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `app/core/logging_config.py`                       | **New.** `setup_logging(settings)` + SQLite sink + schema init + 14-day prune.                                                                                     |
| `app/core/logging_middleware.py`                   | **New.** Per-request `correlation_id`, optional JWT decode, `request.state.user_id`, `logger.contextualize(...)`.                                                  |
| `app/core/exceptions.py`                           | **New.** `AppError` base (status, code, safe message); `LoginError` / `SignupError` subclass it.                                                                   |
| `app/core/exception_handlers.py`                   | **New.** FastAPI handlers for `AppError`, `HTTPException`, `RequestValidationError`, catch-all `Exception`.                                                        |
| `app/config/settings.py`                           | Add `log_dir`, `log_file_path`, `error_file_path`, `log_db_path`; register in `ensure_directories()` and `resolve_paths()`.                                        |
| `app/main.py`                                      | Call `setup_logging(settings)` **first** in `lifespan`; register middleware **and** exception handlers; `logger.remove()` on shutdown to flush.                    |
| `app/api/auth.py`                                  | Remove duplicated `except SignupError` / `except Exception` JSON mapping; let handlers do it.                                                                      |
| `app/api/extract.py`, `migration.py`, `sops.py`, … | Raise `AppError` / `NotFoundError` instead of wrapping `except Exception` as HTTP 500 with `str(e)`.                                                               |
| `app/schemas/jobs.py`                              | Add optional `user_id`, `user_email`, `correlation_id` on `BatchJob`.                                                                                              |
| `app/services/job_manager.py`                      | Accept actor fields in `create_batch_job`; wrap `_process_document` stages in `logger.contextualize(...)`; change worker-loop `logger.error` → `logger.exception`. |
| `app/api/upload.py` (and extract if it enqueues)   | Pass `request.state.user_id` / `correlation_id` into `create_batch_job`.                                                                                           |
| `app/services/export/migration_exporter.py`        | Switch stdlib `logging` → loguru (or add an `InterceptHandler` in setup to capture stdlib + uvicorn).                                                              |
| `.gitignore`                                       | Ignore `data/logs/`.                                                                                                                                               |
| `.env.example`                                     | Optional `SOP_LOG_LEVEL`, `SOP_LOG_DIR`.                                                                                                                           |

Leave **unchanged:** extractors’ best-effort `except` (skip one icon/cell), `AuthStore.audit_events`, frontend `ProtectedRoute` / `authStore`. Do change how APIs **map** those failures to HTTP (see Errors + logging).

New runtime artifacts (git-ignored): `data/logs/app.log`, `data/logs/error.log`, `data/logs/logs.db`.

## SQLite schema

```sql
CREATE TABLE IF NOT EXISTS logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,   -- ISO8601 UTC
    level           TEXT    NOT NULL,
    logger_name     TEXT,
    function        TEXT,
    line            INTEGER,
    message         TEXT    NOT NULL,
    job_id          TEXT,               -- from contextualize()
    document_id     TEXT,               -- from contextualize()
    stage           TEXT,               -- http / auth / parse / tables / icons / ast / chunk / export
    user_id         TEXT,               -- JWT sub (nullable)
    user_email      TEXT,               -- JWT email (nullable)
    role            TEXT,               -- JWT role (nullable)
    session_id      TEXT,               -- JWT sid (nullable)
    correlation_id  TEXT,               -- X-Correlation-ID or generated UUID
    thread          TEXT,
    exception       TEXT,               -- full traceback when present
    extra_json      TEXT                -- any other bound fields, as JSON
);
CREATE INDEX IF NOT EXISTS idx_logs_job         ON logs(job_id);
CREATE INDEX IF NOT EXISTS idx_logs_document    ON logs(document_id);
CREATE INDEX IF NOT EXISTS idx_logs_level       ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_time        ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_user        ON logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_correlation ON logs(correlation_id);
```

Connection PRAGMAs (set once): `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`.

Never persist passwords, secret answers, refresh cookies, or raw JWTs in `message` or `extra_json`.

## How to implement (order)

Implement in this order. Each step is additive.

### 1. Settings (`app/config/settings.py`)

Next to existing `log_level`, add:

- `log_dir = Path("data/logs")`
- `log_file_path = Path("data/logs/app.log")`
- `error_file_path = Path("data/logs/error.log")`
- `log_db_path = Path("data/logs/logs.db")`

In `resolve_paths()`: resolve those four paths against `base`.

In `ensure_directories()`: also create `self.log_dir`.

Optional `.env`:

```
SOP_LOG_LEVEL=INFO
SOP_LOG_DIR=data/logs
```

### 2. `app/core/logging_config.py` (new)

`setup_logging(settings)`:

1. `logger.remove()` — drop the default handler.
2. Add sinks (see Workflow below). File + SQLite sinks **must** use `enqueue=True`.
3. Keep a module-level `_db_path`. Open SQLite **lazily inside `_sqlite_sink`** (that runs on loguru’s enqueue thread — not on the FastAPI event loop).
4. On first open: PRAGMAs, `CREATE TABLE`, indexes, then `DELETE FROM logs WHERE timestamp < date('now','-14 days')`.

`_sqlite_sink(message)` maps `message.record` → INSERT:

| Column                                                          | From                                                        |
| --------------------------------------------------------------- | ----------------------------------------------------------- |
| `timestamp`                                                     | `record["time"]` as UTC ISO8601                             |
| `level`                                                         | `record["level"].name`                                      |
| `logger_name`                                                   | `record["name"]`                                            |
| `function` / `line` / `message`                                 | `record["function"]`, `record["line"]`, `record["message"]` |
| `job_id`, `document_id`, `stage`                                | `record["extra"]`                                           |
| `user_id`, `user_email`, `role`, `session_id`, `correlation_id` | `record["extra"]`                                           |
| `thread`                                                        | `record["thread"].name`                                     |
| `exception`                                                     | `str(record["exception"])` if present                       |
| `extra_json`                                                    | remaining extra keys (not the known columns above)          |

### 3. Wire startup (`app/main.py`)

Call `setup_logging(settings)` **first** in `lifespan`, before `SopStore` / `AuthStore` / `JobManager`.

On shutdown: `await job_manager.stop()` then `logger.remove()` to flush queued sinks.

Register the logging middleware on the FastAPI app (after `setup_logging` exists). CORS already exposes `X-Correlation-ID`.

### 4. HTTP middleware + login (`app/core/logging_middleware.py`)

Frontend already sends `Authorization: Bearer …` from `frontend/src/lib/api.ts`. Backend SOP routes are not JWT-gated. Logging must work with that: attach the user when a token is present, still log when it is not.

For every request:

1. `correlation_id` = header `X-Correlation-ID` or a new UUID.
2. If `Authorization: Bearer …` is present, decode with `TokenService` (same claims as `/api/v1/auth/me`: `sub` → `user_id`, `email`, `role`, `sid` → `session_id`). On invalid/expired token, leave user fields empty — **do not 401** from this middleware. Gating APIs is a separate change.
3. Set `request.state.user_id`, `request.state.user_email`, `request.state.correlation_id` for upload/job enqueue.
4. Wrap `call_next(request)` in:

```
logger.contextualize(
    correlation_id=...,
    user_id=...,          # None on /login before success
    user_email=...,
    role=...,
    session_id=...,
    stage="http",
)
```

5. Echo `X-Correlation-ID` on the response.

Auth handlers can keep `logger.exception` as they do now; those lines inherit `correlation_id`. `LoginService` / `AuthStore.record_audit_event` remains the security source of truth. An extra `stage="auth"` info line after successful login is optional.

### 5. Carry the user across the job queue

`POST /documents/upload/batch` calls `job_manager.create_batch_job(document_ids)` and returns. `_worker` runs later in a **different** asyncio task, so middleware `contextualize` does not apply to parse/tables/export.

**Stamp the actor on the job:**

- `BatchJob`: optional `user_id`, `user_email`, `correlation_id`.
- `create_batch_job(document_ids, user_id=..., user_email=..., correlation_id=...)`.
- In `upload.py`: pass `getattr(request.state, "user_id", None)` (and correlation) into `create_batch_job`.

Then in `_process_document` bind those fields again (see Workflow). `asyncio.to_thread` copies them into parser/extractors.

### 6. Pipeline stages in `JobManager._process_document`

Match the **current** pipeline (not a generic sketch):

1. `stage="parse"` — `parser.parse`
2. `stage="tables"` — `TableExtractor` then `CrossPageTableStitcher`
3. `stage="icons"` — `IconExtractor` then `CaptionExtractor`
4. `stage="ast"` — `ASTBuilder.build`
5. `stage="chunk"` — hierarchical then semantic chunker
6. `stage="export"` — `MigrationExporter.export` + write `*_v2.json` + sop_store upsert

Inner `contextualize(stage=...)` overrides `stage` and keeps `job_id` / `document_id` / `user_id` / `correlation_id`.

Also change `_worker` `logger.error` → `logger.exception` so tracebacks land in `error.log` and `logs.exception`.

### 7. Switch `migration_exporter.py` to loguru

Replace `import logging` / `logging.getLogger(__name__)` with `from loguru import logger`. Existing `logger.debug` / `logger.warning` calls stay.

### 8. Gitignore

Add `data/logs/`.

### 9. Errors + logging (same change set)

Add `AppError`, register FastAPI handlers, stop leaking `str(exc)` on 500, stamp `correlation_id` on every error JSON. Details in **Errors + logging** below. Do this after middleware exists so handlers can read `request.state.correlation_id`.

## Workflow

**Setup (startup)**

1. `lifespan` calls `setup_logging(settings)`.
2. `logger.remove()` drops the default handler; add the sinks:

```python
logger.remove()
logger.add(sys.stderr, level=settings.log_level, backtrace=True, diagnose=False)
logger.add(settings.log_file_path,  level=settings.log_level, rotation="10 MB",
           retention="14 days", enqueue=True)                       # app.log — all levels
logger.add(settings.error_file_path, level="WARNING", rotation="10 MB",
           retention="30 days", enqueue=True)                       # error.log — problems only
logger.add(_sqlite_sink, level=settings.log_level, enqueue=True)    # structured DB
```

3. SQLite sink lazily opens the DB (inside loguru's enqueue thread), applies PRAGMAs, creates the table.

**Per HTTP request (middleware)**

Logged-in UI calls (repository, review, migrate) inherit `user_id` + `correlation_id` automatically. Login/signup inherit `correlation_id` even when `user_id` is still empty.

**Per document (in `JobManager._process_document`)**

```python
with logger.contextualize(
    job_id=job_id,
    document_id=document_id,
    user_id=job.user_id,
    correlation_id=job.correlation_id,
    stage="parse",
):
    raw = await asyncio.to_thread(parser.parse, ...)
    with logger.contextualize(stage="tables"):
        raw = await asyncio.to_thread(table_ext.extract, raw)
        raw = await asyncio.to_thread(stitch_ext.extract, raw)
    with logger.contextualize(stage="icons"):
        raw = await asyncio.to_thread(icon_ext.extract, raw, document_id=document_id)
        raw = await asyncio.to_thread(caption_ext.extract, raw)
    with logger.contextualize(stage="ast"):
        ast = await asyncio.to_thread(ast_builder.build, raw)
    with logger.contextualize(stage="chunk"):
        chunks = await asyncio.to_thread(hierarchical_chunker.chunk, ast)
        chunks = await asyncio.to_thread(semantic_chunker.chunk, chunks)
    with logger.contextualize(stage="export"):
        migration_output = MigrationExporter.export(...)
```

Every log from any nested service inherits `job_id` / `document_id` / `user_id` / current `stage`.

**End-to-end after login**

1. User logs in → row in **`auth.db`** `audit_events` (`LOGIN_SUCCEEDED`).
2. Same request → row in **`logs.db`** with `stage=http` (or `auth`), `correlation_id=…`.
3. User uploads a batch → HTTP log with `user_id` + `job_id`.
4. Worker extracts → `stage=parse|tables|icons|ast|chunk|export` with the **same** `user_id` and `job_id`.

**Tracing a run**

```sql
-- Full timeline for one document
SELECT timestamp, level, stage, user_id, message
FROM logs WHERE document_id = ? ORDER BY id;

-- What did this user extract?
SELECT timestamp, stage, document_id, message
FROM logs WHERE user_id = ? ORDER BY id;

-- Support: operational logs for one correlation id
SELECT * FROM logs WHERE correlation_id = ? ORDER BY id;

-- Only problems
SELECT * FROM logs WHERE level = 'ERROR' ORDER BY id DESC LIMIT 50;
```

Security events for the same support id stay in `auth.db`:

```sql
SELECT * FROM audit_events WHERE correlation_id = ?;
```

## Feature / function-specific tracking

No extra work needed — loguru records the source of every log, and the schema stores it:

| Column        | Meaning                                    | Example filter                     |
| ------------- | ------------------------------------------ | ---------------------------------- |
| `logger_name` | Module = **feature/component**             | `WHERE logger_name LIKE '%icons%'` |
| `function`    | **Function** that logged                   | `WHERE function = 'extract'`       |
| `line`        | Line number                                | debugging                          |
| `stage`       | Pipeline phase (bound via `contextualize`) | `WHERE stage = 'tables'`           |
| `user_id`     | Logged-in actor                            | `WHERE user_id = ?`                |

```sql
-- Everything the icon extractor did for one document
SELECT timestamp, function, line, message
FROM logs WHERE document_id = ? AND logger_name LIKE '%icons%' ORDER BY id;
```

For an explicit label that is independent of the module path, bind a custom field
(`logger.bind(feature="table_stitching").info(...)`) — it lands in `extra_json`.

## How to verify (after implementation)

1. Restart uvicorn.
2. Log in, then upload/extract one SOP.
3. Check `data/logs/app.log` and `data/logs/error.log`.
4. Query `data/logs/logs.db` for that `document_id` — expect a timeline: `http` (upload) then `parse` → `tables` → `icons` → `ast` → `chunk` → `export`, with `user_id` set on worker rows.
5. Trigger a known 404 and a pipeline crash: client JSON has `error.code` + `meta.correlationId`; `logs.db` has the traceback; 500 body does **not** contain the exception string.

Frontend can later send `X-Correlation-ID` (login errors already display `meta.correlationId`). Not required for MVP.

## Retention

- **File:** handled by loguru — `rotation="10 MB"`, `retention="14 days"` (`error.log` retention 30 days).
- **SQLite:** one-line cleanup on startup — `DELETE FROM logs WHERE timestamp < date('now','-14 days')`.

## Errors + logging

Centralized HTTP exception handling is the outer layer. It is **not** enough by itself: auth, SOP APIs, and the background job worker fail in three different ways. Pair handlers with domain errors and a job-worker boundary. Wire every failure to the same log context (`correlation_id`, `user_id`, `job_id`, `stage`).

### Why the current handling is weak

The only global hook is `@app.exception_handler(Exception)` in `app/main.py`. It logs then returns `str(exc)` to the client.

| Problem                      | What happens today                                                                                                                                 |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Leaks internals              | File paths and parser traces appear in the browser.                                                                                                |
| Two JSON shapes              | Auth: `{ success, error: { code, message, fieldErrors }, meta }`. SOP routes: FastAPI `{ detail: "..." }`. Frontend guesses `detail` or `message`. |
| Duplicated auth mapping      | Every `/login`, `/signup`, `/refresh` maps `LoginError` / `SignupError` by hand.                                                                   |
| Broad API `except Exception` | `extract.py` / `migration.py` turn any failure into HTTP 500 with the exception text.                                                              |
| Jobs are not HTTP            | `JobManager._process_document` runs after the upload request returns. FastAPI handlers never see those errors.                                     |
| Local recovery               | Bare `except Exception` in parsers/icon embed is often “skip this asset.” A global handler must not replace those.                                 |

Auth already has the better pattern (`LoginError` / `SignupError` + `ApiErrorResponse` in `app/schemas/auth.py`). **Reuse that envelope** for all APIs. Do not invent a third format (and do not switch to RFC 7807 unless you are willing to rewrite login).

### Three layers

```
Service raises AppError (safe code + message)
        │
        ▼
┌──────────────────────────────────────────┐
│ HTTP request                              │
│   FastAPI exception handlers              │  ← map to ApiErrorResponse + log
│   AppError, HTTPException, 422, catch-all │
└──────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────┐
│ Background job (JobManager)               │
│   catch once → logger.exception           │  ← not HTTP
│   set doc_job.status = FAILED             │
└──────────────────────────────────────────┘
        │
        ▼
Local try/except only for recoverable steps
(missing icon file, one bad table cell)
```

#### Layer 1 — Domain exceptions

One base type (same idea as `LoginError`). Services raise these; they do **not** import `HTTPException`.

```python
class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, field_errors=None):
        self.status_code = status_code
        self.code = code          # DOCUMENT_NOT_FOUND, EXTRACTION_FAILED, ...
        self.message = message    # safe for the client
        self.field_errors = field_errors or []
```

Subclasses: `NotFoundError`, domain validation errors. Make `LoginError` and `SignupError` subclasses of `AppError` so one handler covers auth and SOP routes.

Examples:

- missing upload → `NotFoundError("DOCUMENT_NOT_FOUND", "No uploaded file found.")` (404)
- bad file type → `AppError(400, "UNSUPPORTED_FILE_TYPE", "...")`
- extraction crash in **sync** `/documents/extract` → let it bubble; catch-all returns `500 EXTRACTION_FAILED` (generic)

#### Layer 2 — Central FastAPI handlers

Register in `app/main.py` (handlers live in `app/core/exception_handlers.py`) **after** `setup_logging` so `logger.exception` hits file + SQLite sinks.

| Handler                         | Status            | Log                                                  | Client body                                                     |
| ------------------------------- | ----------------- | ---------------------------------------------------- | --------------------------------------------------------------- |
| `AppError` (incl. Login/Signup) | `exc.status_code` | `logger.warning` for 4xx; `logger.exception` for 5xx | `ApiErrorResponse`                                              |
| `RequestValidationError`        | 422               | `logger.warning`                                     | `code=VALIDATION_ERROR` + field list                            |
| `HTTPException`                 | as raised         | `logger.warning`                                     | Map leftover `detail` into the same envelope (during migration) |
| `Exception` (catch-all)         | 500               | `logger.exception`                                   | Generic message only — **never** `str(exc)`                     |

Every response includes `meta.correlationId` from logging middleware (`request.state.correlation_id` or header).

Then delete the per-endpoint `except SignupError` / `except Exception` JSON blocks in `app/api/auth.py` — let them propagate.

**FastAPI gotcha:** a bare `Exception` handler can swallow `HTTPException` / validation errors if you do not register the more specific handlers first (or re-raise those types). Register specific handlers, then the catch-all.

Do **not** use middleware `try/except` instead of FastAPI handlers — it misses validation errors and fights Starlette.

#### Layer 3 — Job worker boundary

Keep a single `except Exception` in `_process_document` (already there). Change it to:

- `logger.exception(...)` so traceback lands in `error.log` / `logs.exception`
- `doc_job.error` = safe text (`e.message` if `AppError`, else `"Extraction failed"`)
- real traceback **only** in logs, not in the job poll JSON if it would leak internals

Do not convert job failures into HTTP 500 after the fact; the client already polls `GET /jobs/{id}`.

### Client envelope (one shape)

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "No uploaded file found."
  },
  "meta": { "correlationId": "…" }
}
```

Frontend (`frontend/src/lib/api.ts`) should prefer `error.message` / `error.code` over `detail || message`. Login already understands `meta.correlationId`.

### Local catches stay local

Leave `except Exception` in icon embed, table cell image, watermark cleanup, instruction cleaner. Those mean “best effort — skip this piece.” Log `logger.warning` and continue. A central handler cannot express that.

### Approaches considered (and rejected as the _only_ strategy)

| Approach                                     | Verdict                                                                        |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| **Only** `@app.exception_handler(Exception)` | Too coarse; already exists; leaks errors; skips jobs.                          |
| **HTTPException everywhere**                 | Current SOP style. No `code`, no `correlationId`, services coupled to FastAPI. |
| **RFC 7807 Problem Details**                 | Clean standard, but would replace `ApiErrorResponse` that login already uses.  |
| **Result / Ok/Err instead of exceptions**    | Heavy pipeline refactor; not worth it for this POC.                            |
| **Middleware try/except**                    | Worse than FastAPI exception handlers.                                         |
| **Per-router handlers**                      | Same mapping copied on auth vs sops vs migration — what you have now.          |

**Chosen:** Layer 1 + 2 + 3, reuse `ApiErrorResponse`, same `correlation_id` as logging.

### How errors show up in logs

| Failure               | `stage`                | What to query                                   |
| --------------------- | ---------------------- | ----------------------------------------------- |
| Login 401             | `http` or `auth`       | `logs` by `correlation_id`; also `audit_events` |
| Upload 400            | `http`                 | `logs` WHERE `level` IN ('WARNING','ERROR')     |
| Sync `/extract` crash | `http` (request)       | catch-all `logger.exception`                    |
| Batch job crash       | `parse` / `tables` / … | `logs` WHERE `job_id` AND `level` = 'ERROR'     |

```sql
-- Support: HTTP error + pipeline error for one id
SELECT timestamp, level, stage, user_id, message, exception
FROM logs WHERE correlation_id = ? ORDER BY id;
```

### What not to do

- Put `str(exc)` in the 500 JSON body.
- Swallow `HTTPException` inside the `Exception` handler.
- Make parsers raise `AppError` for every skipped drawing.
- Log passwords, secret answers, cookies, or access tokens in error JSON (same rule as logging).
- Replace `auth.db` `audit_events` with these HTTP error logs.

## Optional (not required for MVP)

- Read-only API endpoints: `GET /jobs/{job_id}/logs`, `GET /documents/{document_id}/logs?level=ERROR` (use a separate read connection; WAL keeps reads non-blocking).
- `InterceptHandler` to funnel uvicorn/stdlib logs into the same sinks.
- A `pipeline_runs` summary table (one row per document: status, duration, error) for dashboard-style queries.
- FastAPI `Depends` that **requires** a JWT on upload/migrate so `user_id` is never null. Logging does not need that to ship.
- Frontend always sending `X-Correlation-ID`.
- Teach `frontend/src/lib/api.ts` to read `error.code` / `error.message` once the envelope is uniform.

## Explicitly out of scope

- External aggregators (Datadog/ELK/Loki), OTLP, dead-letter queues, per-log async batching — unnecessary for a local POC. loguru's `serialize=True` leaves a clean upgrade path to JSON export if needed later.
- Replacing `auth.db` `audit_events` with application logs.
- Logging passwords, secret answers, cookies, or access tokens.
- Adding `job_id` / `user_id` arguments to every `logger.info` in extractors.
- Forcing authentication on all `/documents` routes as a prerequisite for logging.
- RFC 7807 Problem Details as a second error format alongside `ApiErrorResponse`.
- Result/Either types or middleware `try/except` instead of FastAPI exception handlers.
