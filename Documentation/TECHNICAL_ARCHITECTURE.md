# SOP Migration System — Technical Architecture

Audience: engineers maintaining or extending this codebase. For an end-user walkthrough of the product, see [`USER_GUIDE.md`](./USER_GUIDE.md).

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Repository Layout](#3-repository-layout)
4. [High-Level Architecture](#4-high-level-architecture)
5. [Backend: Application Bootstrap](#5-backend-application-bootstrap)
6. [Backend: Configuration](#6-backend-configuration)
7. [Backend: API Layer](#7-backend-api-layer)
8. [Backend: Core Cross-Cutting Concerns](#8-backend-core-cross-cutting-concerns)
9. [Backend: Data Schemas](#9-backend-data-schemas)
10. [Backend: Extraction Pipeline Services](#10-backend-extraction-pipeline-services)
11. [Backend: Migration Engine (5-Phase)](#11-backend-migration-engine-5-phase)
12. [Backend: LLM Layer](#12-backend-llm-layer)
13. [Backend: Job Manager](#13-backend-job-manager)
14. [Backend: Authentication Services](#14-backend-authentication-services)
15. [Backend: Data Stores](#15-backend-data-stores)
16. [Frontend Architecture](#16-frontend-architecture)
17. [End-to-End Data Flow](#17-end-to-end-data-flow)
18. [Error Handling Architecture](#18-error-handling-architecture)
19. [Logging & Observability](#19-logging--observability)
20. [Security Notes](#20-security-notes)
21. [Testing](#21-testing)
22. [Configuration Reference](#22-configuration-reference)
23. [Running Locally](#23-running-locally)
24. [Known Limitations & Future Work](#24-known-limitations--future-work)

---

## 1. System Overview

The SOP Migration System is a full-stack application that:

1. Ingests SOP documents (PDF/DOCX).
2. Parses and extracts structured content (text, tables, images, icons, captions, metadata) with layout-aware reading order.
3. Builds a typed **Abstract Syntax Tree (AST)** of the document.
4. Produces hierarchical + semantic **chunks** for retrieval/review.
5. Exports a clean, DOCX-migration-ready JSON representation.
6. Runs an LLM-assisted **5-phase migration engine** that maps extracted content into a new corporate DOCX template and produces a QA report.
7. Exposes all of this through a FastAPI backend and a React/TypeScript SPA frontend, with JWT-based authentication, structured logging, and centralized error handling.

It is architected as a **local-first POC** — SQLite for all persistence, no external services beyond an LLM provider (Gemini/OpenAI/Anthropic/Azure OpenAI) for the migration planner.

---

## 2. Technology Stack

### Backend

| Concern | Technology |
|---|---|
| Web framework | FastAPI 0.115 (ASGI, Starlette), Uvicorn |
| Data validation | Pydantic v2 (`pydantic-settings` for config) |
| PDF parsing | PyMuPDF (`fitz`) for text/images/metadata, `pdfplumber` for tables |
| DOCX parsing & writing | `python-docx` |
| OCR (optional) | `pytesseract` + `Pillow` |
| NLP / similarity | `spacy`, `scikit-learn` (TF-IDF + cosine similarity for semantic chunking) |
| Icon matching | `imagehash` (perceptual hashing) |
| Hierarchy modelling | `anytree` (conceptually), typed Pydantic AST nodes |
| LLM orchestration | LangChain (`langchain`, `langchain-core`) with Google Gemini / OpenAI / Anthropic / Azure OpenAI backends |
| Auth | `argon2-cffi` (password hashing), `pyjwt` (JWT access tokens) |
| Logging | `loguru` (console + rotating file + SQLite sinks) |
| Persistence | SQLite (`sop_records.db`, `auth.db`, `logs.db`) via stdlib `sqlite3` |
| Testing | `pytest`, `pytest-asyncio`, `httpx` |

### Frontend

| Concern | Technology |
|---|---|
| Framework | React 19 + TypeScript, built with Vite |
| Routing | `react-router-dom` v7 |
| Server state | `@tanstack/react-query` v5 |
| Client/auth state | `zustand` |
| Forms & validation | `react-hook-form` + `zod` + `@hookform/resolvers` |
| Rich text editing | `@tiptap/react` + `@tiptap/starter-kit` |
| Styling | Tailwind CSS 3 (`@tailwindcss/forms`, `@tailwindcss/typography`), `tailwind-merge`, `clsx` |
| Animation | `framer-motion` |
| Icons | `lucide-react` |
| Linting | `oxlint` |

---

## 3. Repository Layout

```
app/
├── main.py                      # FastAPI entrypoint & lifespan (startup/shutdown)
├── config/settings.py           # Central Pydantic Settings (env-driven)
├── core/                        # Cross-cutting: logging, exceptions, middleware
│   ├── logging_config.py
│   ├── logging_middleware.py
│   ├── exceptions.py
│   └── exception_handlers.py
├── api/                         # FastAPI routers (one file per resource)
│   ├── health.py, upload.py, extract.py, documents.py,
│   ├── jobs.py, migration.py, sops.py, review.py, auth.py
├── schemas/                     # Pydantic models / data contracts
│   ├── document.py, ast_nodes.py, layout.py, jobs.py,
│   ├── migration.py, output.py, auth.py
├── services/
│   ├── parser/                  # PDF & DOCX → RawDocument
│   ├── layout/                  # Reading-order / column analysis (PDF only)
│   ├── extraction/               # Tables, cross-page stitching, icons, captions, metadata
│   ├── hierarchy/                # ASTBuilder: RawDocument → DocumentNode
│   ├── chunking/                 # Hierarchical + semantic chunkers, validator
│   ├── export/                   # JSON exporter (v1) & MigrationExporter (v2/v3)
│   ├── migration/                # 5-phase DOCX migration engine
│   ├── llm/                      # ChainFactory, rate limiter, prompt templates
│   ├── auth/                     # Login/Signup services, password & token services
│   └── job_manager.py             # Async background worker pool
└── stores/
    ├── sop_store.py              # SQLite: sop_records
    └── auth_store.py             # SQLite: users, sessions, roles, audit_events

frontend/
└── src/
    ├── App.tsx, main.tsx
    ├── routes/ProtectedRoute.tsx
    ├── pages/                    # SopRepository, SopContentView, ReviewPage,
    │                             # ReprocessingAdminPage, LoginPage, SignupPage
    ├── components/
    │   ├── auth/, content/, layout/, repository/, review/, ui/, ai/
    ├── features/auth/            # hooks, schemas, services, types (auth vertical slice)
    ├── lib/                      # api.ts, apiClient.ts, authStore.ts, hooks, utils
    └── types.ts                  # Shared TS contracts (mirrors backend Pydantic schemas)

data/                             # Runtime artifacts (mostly git-ignored)
├── uploads/, temp/, output/, extracted_images/, extracted_icons/
├── migrated/, templates/
├── logs/ (app.log, error.log, logs.db)
├── sop_records.db, auth.db
tests/                            # pytest suite
docs/plans/                       # Design/spec documents
Documentation/                    # This folder (USER_GUIDE.md, TECHNICAL_ARCHITECTURE.md)
```

---

## 4. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  React SPA (Vite, :5173)                                                 │
│  Zustand (auth) + React Query (server state) + fetch-based api.ts client │
└───────────────────────────────┬───────────────────────────────────────--┘
                                 │ REST + WebSocket (CORS, Bearer JWT + HttpOnly refresh cookie)
┌───────────────────────────────▼───────────────────────────────────────--┐
│  FastAPI app (Uvicorn, :8000)                                            │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Middleware: CORS → LoggingContextMiddleware (correlation_id,    │    │
│  │ optional JWT decode) → routers → exception handlers             │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  Routers: health / auth / upload / extract / documents / jobs /         │
│           migration / sops / review                                     │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ JobManager (asyncio worker pool)                                 │    │
│  │   parse → tables → icons → ast → chunk → export                  │    │
│  │   (parser/layout/extraction/hierarchy/chunking/export services)  │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  DocxMigrator (5-phase migration engine, LLM-assisted via LangChain)     │
└───────────────┬───────────────────────────┬─────────────────────────---┘
                 │                           │
        ┌────────▼────────┐         ┌────────▼─────────┐
        │ SQLite stores    │         │ Filesystem (data/) │
        │ sop_records.db   │         │ uploads, output,   │
        │ auth.db          │         │ extracted_images,  │
        │ logs.db          │         │ extracted_icons,   │
        └──────────────────┘         │ migrated, templates│
                                      └────────────────────┘
                                              │
                                      ┌───────▼────────┐
                                      │ LLM Provider     │
                                      │ Gemini / OpenAI / │
                                      │ Anthropic / Azure │
                                      └────────────────┘
```

---

## 5. Backend: Application Bootstrap

`app/main.py` wires everything together via FastAPI's `lifespan` context manager:

1. `get_settings()` — build and resolve the `Settings` singleton (paths resolved against `project_root`, directories created).
2. `setup_logging(settings)` — configure loguru sinks **first**, before any store/service that might log.
3. Instantiate `SopStore` and `AuthStore` (SQLite, auto-create schema) and attach to `app.state`.
4. Instantiate `JobManager(settings, concurrency=1, sop_store=sop_store)` and `await job_manager.start()` — spins up its asyncio worker pool.
5. Instantiate `ChainFactory(settings)` for LLM access, attach to `app.state`.
6. On shutdown: `await job_manager.stop()` (cancels worker tasks), then `reset_logging_state()` to flush and close log sinks.

Middleware/handler registration order (`app/main.py`):

```python
app.add_middleware(CORSMiddleware, ...)          # allow localhost:5173/3000, expose correlation headers
app.add_middleware(LoggingContextMiddleware)      # correlation_id + optional JWT context for every request
register_exception_handlers(app)                  # AppError → RequestValidationError → HTTPException → Exception
app.include_router(health.router)
app.include_router(upload.router)
app.include_router(extract.router)
app.include_router(documents.router)
app.include_router(jobs.router)
app.include_router(migration.router)
app.include_router(sops.router)
app.include_router(review.router)
app.include_router(auth.router)
```

`concurrency=1` on `JobManager` means the extraction pipeline currently processes **one document at a time** across the whole app (single background worker) — see [§13](#13-backend-job-manager).

---

## 6. Backend: Configuration

`app/config/settings.py` defines a single `Settings(BaseSettings)` (Pydantic v2) with `env_prefix="SOP_"` and `.env` file support (loaded via `python-dotenv` at import time). `get_settings()` is the FastAPI dependency-injection factory: it builds `Settings()`, resolves all relative paths against `project_root`, and ensures required directories exist.

Key setting groups (see [§22](#22-configuration-reference) for the full table):

- **Paths** — `upload_dir`, `extracted_images_dir`, `extracted_icons_dir`, `temp_dir`, `output_dir`, `migration_output_dir`, `migration_template_dir`.
- **Processing** — `max_upload_size_mb`, `allowed_extensions`, `ocr_enabled`/`ocr_language`.
- **Semantic chunking** — `embedding_model`, `similarity_threshold`.
- **Watermark filtering** — `watermark_keywords` list used to strip stamps like "WORKING COPY" / "DRAFT" / "CONFIDENTIAL" from extracted text.
- **Table stitching** — thresholds controlling cross-page table merge behavior.
- **Logging** — `log_level`, `log_dir`, `log_file_path`, `error_file_path`, `log_db_path`.
- **Migration** — `migration_output_dir`, `migration_template_dir`, `skip_preamble_migration`.
- **LLM (LangChain)** — `use_llm_section_summarizer` (Mode A vs B), `llm_planner_model`, `llm_summarizer_model`, temperature/token limits.
- **Azure OpenAI** — optional override of the above via Azure deployments.
- **LLM rate limiting** — `llm_max_concurrent`, `llm_min_delay_seconds`, `llm_max_retries`, `llm_base_backoff_seconds`.
- **Auth/JWT** — secret key, algorithm, token/session lifetimes, lockout & rate-limit thresholds, cookie security flag.

`Settings` is deliberately the **only** injection point services need — every service constructor takes `settings: Settings` (and an optional `logger`) rather than reading environment variables directly.

---

## 7. Backend: API Layer

All routers live in `app/api/`. None of the SOP/document/migration routes are currently JWT-gated at the dependency level (only `/api/v1/auth/*` enforces auth semantics); `LoggingContextMiddleware` opportunistically decodes a Bearer token if present so logs/jobs can still be attributed to a user without hard-blocking anonymous access. This is a deliberate POC simplification — see [§24](#24-known-limitations--future-work).

### `health.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check. |

### `auth.py` — prefix `/api/v1/auth`
| Method | Path | Purpose |
|---|---|---|
| GET | `/secret-questions` | List active secret questions for the signup form. |
| POST | `/signup` | Validate + register a new user (`REGULAR_USER` role by default), returns JWT. |
| POST | `/login` | Authenticate credentials; sets HttpOnly `refresh_token` cookie; returns short-lived access JWT. |
| POST | `/refresh` | Rotate refresh token (reads HttpOnly cookie), returns a new access JWT. |
| GET | `/me` | Validate Bearer token, return current user profile. |
| POST | `/logout` | Revoke session, clear refresh cookie. |

### `upload.py` — prefix `/documents`
| Method | Path | Purpose |
|---|---|---|
| POST | `/upload` | Single file upload; extracts preamble metadata to compute `document_id` and preview version; saves to `upload_dir`. |
| POST | `/upload/batch` | Multi-file upload; validates each file, saves valid ones, enqueues a `BatchJob` via `JobManager`, stamping `user_id`/`user_email`/`correlation_id` from `request.state`. |

### `extract.py` — prefix `/documents`
| Method | Path | Purpose |
|---|---|---|
| POST | `/extract` | **Synchronous** parse + table/icon extraction + AST build for a previously uploaded file; returns an element-count summary (does not persist v2 JSON — that only happens via the async job pipeline). |

### `documents.py` — prefix `/documents`
| Method | Path | Purpose |
|---|---|---|
| GET | `/{document_id}` | Full parsed `RawDocument` (debug/inspection). |
| GET | `/{document_id}/elements` | Flat list of extracted elements, optional `page` filter. |
| GET | `/{document_id}/tree` | Nested AST (`DocumentNode`) after all extractors run synchronously. |
| GET | `/{document_id}/chunks` | Full pipeline output as `DocumentOutput` (hierarchical + semantic chunks + validation warnings). |
| GET | `/{document_id}/json` | Same as `/chunks` but also persists to `data/output/{id}.json` via `JSONExporter` (v1 format). |
| GET | `/v2/{document_id}/json` | **Primary content endpoint** — reads the job-pipeline's persisted `{document_id}_v2.json`, rewrites all asset paths (`image_path`/`icon_path`/`path`) into `/documents/{id}/assets/{filename}` URLs, and returns it. |
| GET | `/{document_id}/file` | Serve the original uploaded PDF/DOCX (`FileResponse`). |
| GET | `/{document_id}/assets/{filename}` | Serve an extracted image/icon by basename (checks images dir then icons dir; path-traversal safe via `Path(filename).name`). |

### `jobs.py` — prefix `/jobs`
| Method | Path | Purpose |
|---|---|---|
| GET | `/{job_id}` | Poll `BatchJob` status/progress. |
| WS | `/{job_id}/progress` | Streams the full `BatchJob` JSON every second until `completed`/`failed`. |

### `migration.py` — prefix `/documents`
| Method | Path | Purpose |
|---|---|---|
| POST | `/migrate` | Run the 5-phase migration engine for a `document_id` against an optional uploaded template (else the default `.docx` in `migration_template_dir`); persists `migrated_*.docx`, `plan_*.json`, `qa_*.json`. |
| GET | `/{document_id}/migration-plan` | Retrieve the saved `MigrationPlan` JSON. |
| GET | `/{document_id}/migration-status` | Retrieve the saved `MigrationQAReport` JSON. |
| GET | `/{document_id}/download-docx` | Download the migrated `.docx`. |

`migration.py` resolves `document_id` flexibly — exact `_v2.json`/`.json` filename match, `SopStore` lookup by numeric record ID or UID, then a glob fallback — because the frontend may pass either the numeric `sop_records.id` or the string `document_Uid`.

### `sops.py` — prefix `/sops`
| Method | Path | Purpose |
|---|---|---|
| GET | `` | List SOP records (`status`, `document_uid` filters; pagination). |
| GET | `/{record_id}` | Get one record. |
| PATCH | `/{record_id}/status` | Update review status (`in_review`/`approved`/`rejected`). |
| DELETE | `/{record_id}` | Delete record + smart cleanup of on-disk artifacts. |

### `review.py` — prefix `/review`
| Method | Path | Purpose |
|---|---|---|
| GET | `/{record_id}` | Bootstrap payload for the Review Workspace: resolves `mode` (`review`/`translation`/`migration`) into a `layout` (panel assignment, feature flags), an `availableActions` list, and deep links (content/versions/issues/websocket) — all computed server-side so the frontend stays declarative. |

---

## 8. Backend: Core Cross-Cutting Concerns

`app/core/` contains everything that is *not* domain logic — logging, exceptions, and request middleware — so every service and router shares one implementation.

### 8.1 Domain Exceptions (`exceptions.py`)

```python
class AppError(Exception):
    def __init__(self, status_code, code, message, field_errors=None,
                 retry_after=None, clear_refresh_cookie=False): ...

class NotFoundError(AppError):   # status_code=404 convenience subclass
```

Services raise `AppError`/`NotFoundError` (or auth's `LoginError`/`SignupError`, which subclass `AppError`) instead of `fastapi.HTTPException`, so error semantics stay decoupled from the web framework.

### 8.2 Exception Handlers (`exception_handlers.py`)

`register_exception_handlers(app)` installs handlers in **specificity order** (FastAPI/Starlette requires the most specific first, catch-all last):

1. `AppError` → maps `status_code`/`code`/`message`/`field_errors`/`retry_after`/`clear_refresh_cookie` onto a uniform `ApiErrorResponse`. 5xx logs `logger.exception`; 4xx logs `logger.warning`.
2. `RequestValidationError` (422) → converts Pydantic field errors into `ApiFieldError[]`.
3. `StarletteHTTPException` → maps any remaining `HTTPException(status_code, detail)` call sites into the same envelope (`_http_code_for_status` maps common codes to semantic names like `NOT_FOUND`, `RATE_LIMIT_EXCEEDED`).
4. `Exception` (catch-all) → **always** returns a generic `500 INTERNAL_SERVER_ERROR` message; the real exception is only ever `logger.exception`'d, never leaked to the client.

Every response includes `meta.correlationId`, sourced from `request.state.correlation_id` (set by `LoggingContextMiddleware`) or the `X-Correlation-ID` header, and echoes it back as a response header too.

**Client envelope (uniform across the whole API):**
```json
{
  "success": false,
  "error": { "code": "DOCUMENT_NOT_FOUND", "message": "...", "fieldErrors": null },
  "meta": { "correlationId": "..." }
}
```

### 8.3 Logging Middleware (`logging_middleware.py`)

`LoggingContextMiddleware` (Starlette `BaseHTTPMiddleware`) runs on every request:

1. Resolve `correlation_id` from `X-Correlation-ID` header or generate a UUID.
2. Opportunistically decode a Bearer JWT (`_decode_bearer`) — **never raises**; on missing/invalid token, user fields stay `None` (this middleware does not enforce authentication).
3. Stash `correlation_id`, `user_id`, `user_email`, `role`, `session_id` onto `request.state` (consumed later by routers like `upload.py` when enqueuing jobs, and by `exception_handlers.py`).
4. Wrap `call_next(request)` in `logger.contextualize(...)` with `stage="http"` so every log line emitted while handling the request carries these fields.
5. Echo `X-Correlation-ID` on the response.

### 8.4 Logging Configuration (`logging_config.py`)

`setup_logging(settings)` is idempotent (guarded by a module-level `_configured` flag) and configures three loguru sinks:

| Sink | Target | Level | Rotation/Retention |
|---|---|---|---|
| Console | `sys.stderr` | `settings.log_level` | n/a |
| App log file | `data/logs/app.log` | `settings.log_level` (all) | 10 MB / 14 days |
| Error log file | `data/logs/error.log` | `WARNING`+ | 10 MB / 30 days |
| SQLite | `data/logs/logs.db` → `logs` table | `settings.log_level` | pruned to last 14 days on startup |

Both file sinks and the SQLite sink use `enqueue=True` so writes are serialized through loguru's background thread — safe for the multi-threaded worker pool (`asyncio.to_thread`) without `SQLITE_BUSY` errors. The SQLite connection is opened **lazily inside `_sqlite_sink`** (i.e., on loguru's own thread, not the FastAPI event loop), with `WAL` journal mode, `synchronous=NORMAL`, and a 5s busy timeout. `reset_logging_state()` is a test/shutdown helper that removes all sinks and closes the connection.

---

## 9. Backend: Data Schemas

All schemas are Pydantic v2 models under `app/schemas/`.

- **`document.py`** — `RawDocument`, `PageContent`, `ExtractedElement`/`ExtractedHeading`/`ExtractedImage`/`ExtractedTable`/`ExtractedIcon`, `BoundingBox`, `DocumentMetadata`, `Chunk`, `ChunkMetadata`, `DocumentOutput` (v1 export envelope).
- **`ast_nodes.py`** — the typed AST. `ASTNode` is the base (id, `node_type` discriminator, `sequence`, `source_location`, `confidence`, `metadata`). Concrete node types: `DocumentNode` (root), `SectionNode`, `HeadingNode`, `ParagraphNode` (+ `HighlightSpan`), `HighlightNode`, `ListNode`/`ListItemNode`, `TableNode`/`TableRowNode`/`TableCellNode` (supports merged cells via `row_span`/`col_span`/`is_merge_origin`/`merge_origin_ref`), `ImageNode` (+ optional OCR text/confidence), `IconNode` (+ `IconCategory` enum, semantic meaning, classification method), `CaptionNode`. `ChildNode` is a `Discriminator`-based `Union` of all node types used for every heterogeneous `children`/`content`/`items` list, so Pydantic serializes each subtype's full field set.
- **`layout.py`** — `BoundingBox`, `Column`, `ContentRegion`, `PageLayout` used by the PDF layout analyzer.
- **`output.py`** — a v2 AST envelope: `ExtractionStats` (computed by walking the AST), `AssetReference`/`AssetManifest`, `HeaderFooterEntry`, `DocumentExtractionOutput` (top-level: version, `document_id`, timestamp, `metadata`, `assets`, `headers`/`footers`, full `ast`, `chunks`, `extraction_stats`). **Note the naming collision:** this schema is *not* what ends up in `data/output/{document_id}_v2.json` — that file is written by `JobManager` using the `migration.py` schema below (`DocxMigrationOutput`, its own `version="3.1"`). `DocumentExtractionOutput` is defined and used for in-memory `ExtractionStats` computation, but is not currently persisted to disk by any endpoint or job.
- **`migration.py`** — the clean, DOCX-migration-ready format actually written to `{document_id}_v2.json` by `MigrationExporter`: `MigrationMetadata`, `MigrationIconRef`, `MigrationTableCell`, `MigrationElement` (heading/paragraph/list/table/image variants, each with a `to_clean_dict()` that omits `None`/empty fields), `MigrationSection`, `DocxMigrationOutput` (top-level envelope, `version="3.1"`, aliased `document_Uid`).
- **`jobs.py`** — `JobStatus` enum, `DocumentJob` (per-file progress), `BatchJob` (per-batch aggregate with computed `total_documents`/`completed_documents`/`failed_documents`/`progress_percentage` properties, plus `user_id`/`user_email`/`correlation_id` actor stamping).
- **`auth.py`** — request/response contracts for the auth API: `SignupRequest`/`LoginRequest` (both `extra="forbid"`), `AuthenticationResult`, `*SuccessResponse` envelopes, `ApiErrorResponse`/`ApiErrorDetail`/`ApiFieldError`/`ApiMeta` (the same envelope reused by `core/exception_handlers.py` for **all** API errors, not just auth).
- **`app/services/migration/schemas.py`** — migration-engine-internal schemas: `TemplateRawProfile`/`TemplateParagraphInfo`/`TemplateTableInfo` (Phase 1), `ContentSummary`/`ContentSectionSummary`/`ContentElementSummary` (Phase 1, shared by Mode A/B), `LLMSectionProfile`/`LLMElementDescriptor` (Mode B), `MigrationPlan`/`SectionPlan`/`ElementPlacement`/`PlaceholderTablePlan`/`CalloutStyleDef` (Phase 2 LLM output), `MigrationQAReport`/`MigrationResult` (Phase 5).

Frontend `frontend/src/types.ts` mirrors these schemas by hand (no codegen) — keep both in sync when changing backend contracts.

---

## 10. Backend: Extraction Pipeline Services

The extraction pipeline is invoked two ways: synchronously (per-endpoint, re-parses from scratch — used by `extract.py`/`documents.py` inspection endpoints) and asynchronously (`JobManager`, the canonical path that persists `{document_id}_v2.json`). Both paths run the **same** service chain.

### 10.1 Parsers (`app/services/parser/`)

- **`base_parser.py`** — `BaseParser` ABC. `parse(file_path)` is abstract; shared `_validate_file` (existence + allowed extension) and `_next_gpdat_version` helpers.
- **`pdf_parser.py`** — `PDFParser` (PyMuPDF). Extracts per-page text blocks (with font size used as a heading heuristic, `_HEADING_FONT_SIZE_THRESHOLD = 13.0`), embedded images, and document metadata (delegating SOP-specific metadata to `SOPMetadataExtractor`). **Immediately after** building the raw per-page element list, it runs `PDFLayoutAnalyzer.reorder_document()` — layout analysis is part of parsing, not a separate pipeline stage, because reading order must be correct before any downstream extractor reasons about element sequence.
- **`docx_parser.py`** — `DocxParser` (python-docx). Maps paragraph styles (`Title`, `Heading 1-6`) to heading levels and list styles (`List Bullet*`, `List Number*`, `List Paragraph`) to list detection; extracts tables and embedded images via relationship IDs.
- **`parser_factory.py`** — `ParserFactory.get_parser(file_path)` picks `PDFParser` vs `DocxParser` by file extension.

### 10.2 Layout Analysis (`app/services/layout/`)

- **`pdf_layout_analyzer.py`** (`PDFLayoutAnalyzer`) — runs after raw block extraction, before extractors:
  1. **XY-cut column detection** — finds vertical whitespace gaps to split multi-column pages, using `reading_order.py`'s `Block`/`ReadingOrderAnalyzer`.
  2. **Rail-icon exclusion** — small images (≤ `_RAIL_ICON_MAX_PT` = 90pt) are excluded from the column cut entirely; they are treated as overlays on the text, not a text column, which fixes the classic "icon strip mistaken for a second column" failure mode.
  3. **Icon-before-text binding** (`_insert_icons_before_text` / `_group_inline_icons`) — after body text ordering, each icon is placed immediately before the paragraph it vertically overlaps (preferring text to its right), matching the left-rail icon layout common in these SOPs.
  4. Header/footer zone detection and reading-order reconstruction across columns.
  - Output: a `PageLayout` per page (bounding-box based `Column`/`ContentRegion` model in `app/schemas/layout.py`), used to reorder `RawDocument.pages[*].elements`.

### 10.3 Extraction (`app/services/extraction/`)

Run in this order by both `JobManager` and the synchronous inspection endpoints:

1. **`TableExtractor`** (`tables.py`) — uses `pdfplumber` to find table grids.
   - `collapse_sparse_grid()` — drops empty columns, merges columns that never both have content in the same row (fixes pdfplumber over-segmenting fill/shading artifacts into phantom columns), joins wrapped continuation rows (`_merge_continuation_rows`), strips watermark bleed (`clean_table_cell_text`), and merges duplicate/prefix text fragments (`_merge_text_parts`).
   - `is_shaded_callout()` — detects colored callout boxes (icon + numbered list, no real grid) that pdfplumber mis-reads as a table; when true, the extractor **does not** create a table node at all, leaving the underlying text lines/icons for normal paragraph/list processing.
2. **`CrossPageTableStitcher`** (`cross_page_stitcher.py`) — walks forward across consecutive pages with no new table (stopping if the next table is a different logical table per `table_stitch_score_threshold`), drops repeated header rows on continuation pages, and appends continuation rows to the correct data row (not as a bogus new row) using `_last_row_bbox`/bottom-zone/top-zone heuristics from settings.
3. **`IconExtractor`** (`icons.py`) — perceptual-hash (`imagehash`, Hamming distance ≤ `HASH_THRESHOLD=5`) matching against a reference library (`data/config/icon_library.json`, auto-created if missing) plus size heuristics, converting `ExtractedImage` → `ExtractedIcon` with `icon_category` (`IconCategory` enum: safety/status/action/informational/regulatory/navigation/branding/unknown) and `semantic_meaning`.
4. **`CaptionExtractor`** — associates caption text with the nearest image/table.
5. **`SOPMetadataExtractor`** (`metadata_extractor.py`) — parses the first-page preamble table (or header) to extract a 5-tuple `(document_title, document_name, document_number, document_version, document_type)` using disjoint keyword sets per field (so "Title" never overwrites the short "Document Name"), whole-word version matching (avoids `"rev"` inside "Reviewer"), and watermark-bleed cleanup. `generate_document_id()` builds the stable UID from name/title + number + version (with filename fallback); this UID is what everything downstream (`sop_records`, `data/output/*_v2.json`, asset directories) keys off.

### 10.4 AST Building (`app/services/hierarchy/ast_builder.py`)

`ASTBuilder.build(raw_document)` walks the (already layout-reordered, table/icon-enriched) `RawDocument` maintaining a section stack keyed by heading level, producing a `DocumentNode` tree of the typed nodes from [§9](#9-backend-data-schemas). `_reorder_icons()` is a safety-net pass that looks forward/backward for Y-axis overlap (≥30% of the smaller bounding box) to bind any icon that slipped through sequential ordering, without ever stealing an icon onto a full-width heading.

### 10.5 Chunking (`app/services/chunking/`)

- **`HierarchicalChunker`** — walks the AST and turns each `SectionNode` (+ its direct elements) into one `Chunk`, keeping atomic elements (tables, images) intact rather than splitting them.
- **`SemanticChunker`** — refines large hierarchical chunks by splitting at points of low semantic similarity, computed via **TF-IDF + cosine similarity** (scikit-learn only — no torch/sentence-transformers dependency) against `settings.similarity_threshold`. Also merges PDF-layout-induced continuation fragments (`_merge_continuation_paragraphs`) before scoring.
- **`ChunkValidator`** — sanity-checks the final chunk list: flags completely empty chunks (no content/tables/images/icons) and excessively large chunks (>1500 words) as validation warnings, returning `(is_valid, warnings)` that surface in `DocumentOutput.validation_passed`/`validation_warnings`.

### 10.6 Export (`app/services/export/`)

- **`JSONExporter`** (`json_export.py`) — writes the v1 `DocumentOutput` (chunk-based) to disk; backs the `/documents/{id}/json` endpoint.
- **`MigrationExporter`** (`migration_exporter.py`) — the **canonical exporter** used by `JobManager`. Traverses the AST into the clean `DocxMigrationOutput`/`MigrationSection`/`MigrationElement` format ([§9](#9-backend-data-schemas)), and is the last layer with a chance to repair section/icon assignment using AST bounding boxes:
  - `_reclaim_section_continuations()` — if the last paragraph of section N doesn't end in sentence-final punctuation and a later same-page paragraph starts lowercase, moves it back into section N (fixes the classic "icon rail column mix-up split PURPOSE across two sections" bug).
  - `_rebind_icons_by_y()` — when bounding boxes are available, strips relocatable icons and reattaches each to the paragraph with the best Y-overlap (falls back to sequential pairing when no bbox exists, e.g. DOCX source).
  - `_collapse_migration_cells()` — a second, exporter-level safety net for sparse table grids (mirrors `collapse_sparse_grid` in `tables.py`).

---

## 11. Backend: Migration Engine (5-Phase)

`app/services/migration/docx_migrator.py` (`DocxMigrator.migrate()`) orchestrates the full engine, invoked from `POST /documents/migrate`. Collaborators are constructed once in `__init__`: `TemplateInspector`, `TOCBuilder`, `DocxStyler`, `TableMigrator`, `CalloutBuilder`, `InstructionCleaner`, `MigrationValidator`, a shared `LLMRateLimiter`, and either `ContentSummarizer` (Mode A) or `LLMSectionSummarizer` (Mode B) depending on `settings.use_llm_section_summarizer`, plus `SectionAligner` for planning.

### Phase 1 — Pre-process
- **`TemplateInspector.inspect(template_path)`** → `TemplateRawProfile`: every paragraph (style, heading level, blue-instruction-color detection via a curated `BLUE_HEX_VALUES` set, bold flag) and every table (dimensions, preceding heading, header text, sample cells, and flags for `is_vault_token_table` / `is_document_history_table` / `is_instructional_table`, detected via a `PLACEHOLDER_PATTERN` regex matching `${...}`, `<<...>>`, `[Insert ...]`, vault tokens, etc.).
- **Content Summarization** → `ContentSummary`:
  - **Mode A (`ContentSummarizer`, default)** — fast, zero-LLM-call, truncation-based per-element/per-section summaries.
  - **Mode B (`LLMSectionSummarizer`)** — parallel LLM calls (via `ChainFactory` + `LLMRateLimiter`) that additionally annotate each section with `semantic_purpose`, `taxonomy_category`, `key_topics`, and each element with `semantic_role`/`callout_candidate_type` (`LLMSectionProfile`/`LLMElementDescriptor`), falling back to Mode A's base summary structure.
  - `skip_preamble_migration` (default `true`) skips section `"0 ..."` (cover page) content entirely.

### Phase 2 — LLM Migration Planning
- **`SectionAligner.create_migration_plan(template_profile, content_summary)`** — one structured-output LLM call (`ChainFactory.create_structured_planner(MigrationPlan)`, system prompt in `app/services/llm/prompts/migration_planner.py`) that receives the full template profile + content summary as JSON and returns a complete `MigrationPlan`: per-section `SectionPlan`s (each with ordered `ElementPlacement`s specifying exact action — `insert_heading`/`insert_paragraph`/`insert_list`/`insert_table`/`insert_image`/`insert_callout`/`populate_placeholder`/`skip`), `PlaceholderTablePlan`s (populate vs delete specific template tables), dynamic `CalloutStyleDef`s discovered from the template, typography settings, and quality signals (`overall_confidence`, `warnings`, `reasoning_summary`).

### Phase 3 — Programmatic Execution
`DocxMigrator` opens the template as a fresh `python-docx` `Document` and, without further LLM calls, deterministically:
1. Runs `InstructionCleaner.clean(doc, plan, clean_tables=False)` first pass (blue instructional text, but table cleanup deferred).
2. Locates the real Document History table and cover-page "vault token" tables so they're protected from accidental population/deletion; redirects a misrouted Document History plan to the correct table index.
3. Populates every `PlaceholderTablePlan` with `action="populate"` via `TableMigrator.populate()`, skipping vault tables and duplicates; auto-populates Document History even if the LLM plan missed it.
4. Deletes every template table that is neither populated nor a protected vault table (`TableMigrator.delete_table`).
5. Back-fills any template heading the LLM plan left out as an empty `SectionPlan`, and auto-aligns any source section whose (numbering-stripped) title fuzzily matches an unmapped template heading (`_align_unmapped_template_sections`) — a safety net for LLM planning gaps.
6. Consolidates decimal subsection plans (e.g. `6.1`) that were mistakenly created as top-level unmapped sections back into their numeric parent.
7. For every **mapped** `SectionPlan`, `_execute_section_plan` builds a **complete** placement list per source element (`_build_complete_placements` — guarantees ~100% content coverage even for elements the LLM plan didn't explicitly mention, inferring the right `action` from `element_type` and reclassifying bullet/numbered heading-looking text as lists) and executes each via `_execute_element`, which dispatches to:
   - `DocxStyler.insert_heading/insert_paragraph/insert_list/insert_image` — low-level OXML insertion, typography (font family/size from the plan), inline icon embedding, vertical centering of icon+text lines.
   - `TableMigrator.insert_table` — brand-new Word tables with borders/padding/widths and left-aligned icons for source tables not tied to a template placeholder.
   - `CalloutBuilder.build` — single-cell shaded/bordered tables for callout-styled content, using either a plan-provided `CalloutStyleDef` or one of four built-in defaults (`executive_summary`, `explanation`, `attention`, `key_takeaway`).
   - Each created OXML element is spliced in sequentially via `addnext`, with an automatic spacer paragraph inserted whenever two `<w:tbl>` elements would otherwise become DOM-adjacent (Word auto-merges adjacent tables).
8. Any source section never claimed by a `SectionPlan` is auto-inserted as a new `is_unmapped_source` section (heading + content) positioned after a sensible anchor (default: after "PROCESS").
9. `_sanitize_shifted_icons` — a final self-healing pass that detects a common icon-extraction drift pattern (intro sentence ending `:` holds an icon, following items also hold icons, but the *last* item doesn't) and shifts icons down one position to their true semantic target.
10. A final `InstructionCleaner.clean()` pass removes any remaining scaffolding, protecting the OXML elements of tables that were actually populated.

### Phase 4 — TOC & Formatting Polish
`TOCBuilder.insert_toc()` inserts a **native Word TOC field code** (updates automatically in Word from heading styles, not a static list) after the "TABLE OF CONTENTS" heading (creating one if absent). `_separate_adjacent_tables()` runs a final DOM pass to guarantee no two `<w:tbl>` elements are directly adjacent. The document is saved to `migration_output_dir/migrated_{document_id}.docx`.

### Phase 5 — Validation
`MigrationValidator.validate(output_path, extracted, plan)` re-opens the saved `.docx` and produces a `MigrationQAReport`: content coverage percentage (placed vs. total source elements), sections mapped/unmapped/with-no-content/deleted, remaining blue instructional text count, heading style issues, low-confidence warnings, validation errors, and (when Mode B is active) LLM call/token counters. `status` is `pass` / `pass_with_warnings` / `needs_review`.

The API layer (`app/api/migration.py`) persists `plan_{document_id}.json` and `qa_{document_id}.json` alongside the `.docx`, and returns a `MigrationResult` with a `download_url`.

---

## 12. Backend: LLM Layer

`app/services/llm/`:

- **`chain_factory.py`** (`ChainFactory`) — single point of LLM provider routing, entirely settings-driven:
  - Default path: LangChain's `init_chat_model(model=settings.llm_planner_model | llm_summarizer_model, ...)`, where the model string prefix (`gemini/…`, `openai/…`, `anthropic/…`) selects the provider.
  - Azure path: when `settings.use_azure_openai=True`, builds `AzureChatOpenAI` directly from `azure_openai_endpoint`/`azure_openai_api_version`/`azure_openai_*_deployment` and an API key read from `AZURE_OPENAI_API_KEY` (intentionally **without** the `SOP_` prefix, since it's a third-party secret, not app config).
  - `create_structured_planner`/`create_structured_summarizer` wrap the chat model with `.with_structured_output(pydantic_schema)` so LangChain enforces the response shape (`MigrationPlan`, `LLMSectionProfile`) directly.
- **`rate_limiter.py`** (`LLMRateLimiter`) — `asyncio.Semaphore(max_concurrent)` to bound simultaneous calls, a min-delay gate between any two calls process-wide, and exponential backoff retries (`base_backoff_seconds` doubling per attempt, capped at `max_retries`) for 429/transient errors. Shared by `DocxMigrator` across both the summarizer and the planner.
- **`prompts/migration_planner.py`** — `PLANNER_SYSTEM_PROMPT`, the system prompt driving Phase 2's structured `MigrationPlan` generation.
- **`prompts/section_summarizer.py`** — `SECTION_SUMMARIZER_SYSTEM_PROMPT`, driving Mode B's per-section `LLMSectionProfile` generation.

---

## 13. Backend: Job Manager

`app/services/job_manager.py` (`JobManager`) is a minimal in-process async task queue — no external broker (Celery/Redis) — appropriate for a single-instance POC.

- **State**: `self.jobs: dict[str, BatchJob]` (in-memory only — jobs do not survive a process restart), `self.queue: asyncio.Queue` of `(job_id, document_id)` tuples.
- **`start()`/`stop()`** spin up/cancel `concurrency` worker coroutines (`_worker`); `main.py` uses `concurrency=1`.
- **`create_batch_job(document_ids, user_id, user_email, correlation_id)`** — builds a `BatchJob` with one `DocumentJob` per file, stores it, and pushes each `(job_id, doc_id)` onto the queue. Actor fields are stamped here because the HTTP request that enqueued the job will have returned long before a worker picks it up — request-scoped `logger.contextualize` from the middleware does not survive into the worker's task.
- **`_worker(name)`** loop: pull from queue → `_process_document(job_id, doc_id)` → repeat; `except asyncio.CancelledError: break` for clean shutdown; any other exception is `logger.exception`'d and the worker keeps running.
- **`_process_document`** re-establishes context with `logger.contextualize(job_id=..., document_id=..., user_id=job.user_id, correlation_id=job.correlation_id, stage="parse")`, then narrows `stage` per pipeline step (`tables`/`icons`/`ast`/`chunk`/`export`) using nested `contextualize` blocks. Every blocking call (`parser.parse`, extractors, `ASTBuilder.build`, chunkers, file writes) is wrapped in `asyncio.to_thread(...)` — this both keeps the event loop responsive and, critically, **copies the current contextvars (including loguru's context) into the worker thread**, so every nested log line still carries `job_id`/`document_id`/`user_id`/`correlation_id`/`stage`.
- Progress is tracked via `doc_job.progress_percentage` (20/40/65/80/90/100 milestones) and `doc_job.message` (human-readable stage description), polled by `GET /jobs/{id}` and streamed by the WebSocket.
- On success: writes `data/output/{document_id}_v2.json` (via `migration_output.to_clean_dict()`), and best-effort upserts a `sop_records` row (`SopStore.upsert_record`) — a failure here is only `logger.warning`'d, not fatal to the job.
- On failure: `logger.exception(...)`, then `doc_job.error = e.message if isinstance(e, AppError) else "Extraction failed"` — only a safe, generic message ever reaches the client; the real traceback is only in the logs.
- `_build_asset_manifest` walks the AST for image/icon metadata (`width`/`height`/`semantic_meaning`) and cross-references it with the actual files on disk under `extracted_images_dir`/`extracted_icons_dir` to build the `AssetManifest`.

---

## 14. Backend: Authentication Services

`app/services/auth/` implements a from-scratch (no external IdP) JWT + refresh-cookie auth system per `docs/plans/login_page.md`-style spec, backed by `AuthStore` (SQLite):

- **`signup_service.py`** (`SignupService`, raises `SignupError(AppError)`) — extensive field-level validation (name length/control-chars, BI email regex, password ≥12 chars and ≠ email, confirm-password match, secret question UUID + active-state check, secret answer length), duplicate-email check with an audit event, default-role lookup (`REGULAR_USER`), Argon2id password hashing + secret-answer hashing (`PasswordService`), atomic user creation, then issues an access JWT.
- **`login_service.py`** (`LoginService`, raises `LoginError(AppError)`) — the most security-hardened path:
  - **Per-IP rate limiting** — in-memory sliding window (`_ip_attempts` dict), `auth_ip_rate_limit_max_attempts` per `auth_ip_rate_limit_window_minutes`, returns `429` with `Retry-After`.
  - **Timing-attack defense** — a pre-computed dummy Argon2id hash is verified even when the email doesn't exist, so response timing doesn't leak account existence.
  - **Account lockout** — `auth_max_failed_attempts` failures locks the account for `auth_lockout_duration_minutes`; expired locks are cleared atomically on next attempt.
  - **Session creation** — a random `refresh_token` (`secrets.token_urlsafe(32)`) is only ever stored **hashed** (SHA-256) server-side; the raw token is set as an `HttpOnly`, `SameSite=Lax` cookie scoped to `/api/v1/auth`, with `max_age` driven by `rememberMe` (`auth_remember_me_expire_days` vs `auth_refresh_token_expire_days`).
  - **Refresh token rotation + reuse detection** (`refresh_session`) — every refresh issues a **new** session/token and revokes the old one (`rotate_session`); if a *revoked* token is presented again (a sign of theft/replay), the entire token family is revoked and a `REFRESH_TOKEN_REUSE_DETECTED` audit event is recorded.
  - Every security-relevant outcome (`LOGIN_SUCCEEDED`/`LOGIN_FAILED`/`ACCOUNT_LOCKED`/`TOKEN_REFRESHED`/`REFRESH_TOKEN_REUSE_DETECTED`/`LOGOUT`) is written to `AuthStore.record_audit_event` — the permanent, non-rotating security audit trail (`auth.db` → `audit_events`), intentionally separate from the operational `logs.db` described in [§19](#19-logging--observability).
- **`token_service.py`** (`TokenService`) — issues/decodes short-lived (`jwt_access_token_expire_seconds`, default 900s) HS256 JWTs with claims `sub` (user id), `email`, `role`, `sid` (session id), `iss`/`aud` from settings.
- **`password_service.py`** (`PasswordService`) — Argon2id hashing/verification wrapper (`argon2-cffi`) for both passwords and secret-question answers.

---

## 15. Backend: Data Stores

Three independent SQLite databases, each owned by one module — no cross-database joins, deliberately:

| DB | Owner | Purpose |
|---|---|---|
| `data/sop_records.db` | `app/stores/sop_store.py` (`SopStore`) | SOP document registry & review workflow state. |
| `data/auth.db` | `app/stores/auth_store.py` (`AuthStore`) | Identity, credentials, sessions, roles, security audit trail. |
| `data/logs/logs.db` | `app/core/logging_config.py` | Operational/application logs (see [§19](#19-logging--observability)). |

### `sop_records` (SopStore)

```sql
CREATE TABLE sop_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    document_uid TEXT NOT NULL,
    document_number TEXT, document_name TEXT, document_title TEXT,
    document_version TEXT, document_type TEXT, file_type TEXT,
    language TEXT DEFAULT 'en', page_count INTEGER DEFAULT 0,
    gpdat_version INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'in_review' CHECK(status IN ('in_review','approved','rejected')),
    source_filename TEXT, output_path TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(document_uid, gpdat_version)
);
```

- `get_next_version(document_uid)` → `MAX(gpdat_version)+1` (or 1) — **re-uploading the same document UID never overwrites a row**; it inserts a new version row, preserving history, while on-disk artifacts (`{uid}_v2.json`, upload file, asset directories) remain unversioned/overwritten (the repository always reads "latest by UID", not "latest by version").
- Deletion (`delete_record`) performs **smart cleanup** — removes the DB row and the corresponding upload file / output JSON / extracted image & icon directories.

### `auth.db` tables (AuthStore)

`roles`, `secret_questions` (seeded on first run), `users`, `user_security` (password hash, lockout state, failed-attempt counters), `user_sessions` (refresh-token hash, token family id, expiry, revocation reason), `audit_events` (append-style security log: actor, event type/action/outcome, correlation id, error code, resource type/id, JSON `details`, IP/user-agent, timestamp). Foreign keys enabled (`PRAGMA foreign_keys=ON`); connection opened with `check_same_thread=False` since `AuthStore` is shared across async request handlers.

---

## 16. Frontend Architecture

### 16.1 Structure & Bootstrapping

`frontend/src/main.tsx` mounts `<App />`. `App.tsx` sets up `BrowserRouter` with two route groups:

- **Public**: `/login` (`LoginPage`), `/signup` (`SignupPage`).
- **Protected** (wrapped in `<ProtectedRoute><Layout>...</Layout></ProtectedRoute>`): `/` (`SopRepository`), `/sops/:recordId` (`SopContentView`), `/review/:recordId` (`ReviewPage`), `/admin/reprocessing` (`ReprocessingAdminPage`), with a catch-all redirect to `/`.

On mount, `App` calls `useAuthStore().initializeAuth()` once — this attempts a **silent refresh** using the HttpOnly cookie (no credentials needed) so a returning user with a valid session skips the login screen entirely.

### 16.2 Auth State & API Client

- **`lib/authStore.ts`** (Zustand) — holds `isAuthenticated`, `isInitializing`, `user`, `accessToken`, `expiresAt`. `initializeAuth()` calls `authApi.refresh()`; on success populates the session, on failure leaves the user logged out (no error surfaced — this is the expected "no session" path). `logout()` calls the API best-effort, then always clears local state.
- **`lib/api.ts`** — a thin `fetch` wrapper (`request<T>()`) used for all non-auth-vertical calls:
  - **Proactive token refresh** (`_ensureFreshToken`) — before every request, if the access token is missing or expiring within 60 seconds, it awaits a **deduplicated** (single in-flight promise) call to `/api/v1/auth/refresh` before proceeding, so concurrent requests near expiry don't each trigger their own refresh race.
  - Injects `Authorization: Bearer <token>` and always sends `credentials: 'include'` (so the HttpOnly refresh cookie travels automatically).
  - On any non-2xx response: parses the JSON error envelope and prefers `error.message` / `error.code` (the new uniform backend envelope) over legacy `detail`/`message` fields — see [§18](#18-error-handling-architecture). A `401` additionally force-clears the local session (triggers redirect via `ProtectedRoute`).
  - Exposes typed methods for every backend endpoint: SOP CRUD, batch upload, job polling, `getV2Json`, asset URL helpers (`getAssetUrl`, `assetFileName` — normalizes Windows/POSIX paths or `{path}` objects into a bare filename), review bootstrap, workflow actions (several of these — `approveWorkflow`, `saveDraft`, issues, reprocessing requests — degrade gracefully with an in-memory mock fallback on request failure, since those sub-features are not fully backed by dedicated endpoints yet), migration trigger/status/plan/download.
- **`features/auth/`** — a self-contained vertical slice for the auth pages: `services/authApi.ts` (login/signup/refresh/logout calls), `hooks/useLogin.ts`/`useSignup.ts`/`useSecretQuestions.ts`/`useAuth.ts`, `schemas/loginSchema.ts`/`signupSchema.ts` (Zod, paired with `react-hook-form` via `@hookform/resolvers`), `types/auth.types.ts`.
- **`routes/ProtectedRoute.tsx`** — reads `useAuthStore`; while `isInitializing` shows a loading state, once resolved redirects unauthenticated users to `/login`, otherwise renders children.

### 16.3 Server State

All server data fetching/mutation goes through `@tanstack/react-query` (`useQuery`/`useMutation` + `queryClient.invalidateQueries`) layered on top of `api.ts` — no separate global server-state store; React Query's cache is the source of truth for lists (`['sops']`), individual records (`['sop', id]`), extracted content (`['v2Content', uid]`), and review bootstraps.

### 16.4 Pages

| Page | Route | Responsibility |
|---|---|---|
| `LoginPage` / `SignupPage` | `/login`, `/signup` | Credential forms (react-hook-form + zod), call `features/auth` hooks. |
| `SopRepository` | `/` | Landing dashboard: search/filter/sort SOPs (`SearchBar`, `FilterBar`), table/grid toggle (`SopTable`/`SopGrid`), `UploadSops` dialog, `JobProgressBanner` driven by `useJobPolling`, delete confirmation (`ConfirmDialog`), stats (`StatCards` + `lib/stats.ts`). |
| `SopContentView` | `/sops/:recordId` | Fetches the SOP record + its v2 JSON, renders it via `SectionNav` + `ElementRenderer`, exposes status change actions. |
| `ReviewPage` | `/review/:recordId` | Fetches `ReviewBootstrap` (drives layout/actions/links) + v2 content; renders `ReviewHeader`, one of `ExtractionReviewMode`/`MigrationReviewMode`/`TranslationReviewMode` based on the `?mode=` query param, `ActionFooter`, `ReprocessingRequestDialog`. Mode switches update the URL so state is shareable/bookmarkable. |
| `ReprocessingAdminPage` | `/admin/reprocessing` | Lists reprocessing requests (server data with a local sample fallback), approve/reject actions with required rejection comments. |

### 16.5 Key Component Groups

- **`components/content/`** — `ElementRenderer.tsx` (renders any AST/migration element type: heading/paragraph/list/table/image/icon; accepts icon values as a raw string **or** `{path}` object; per-element error boundary so one malformed element can't blank the page; icon-left/text-right flex layout matching the source SOP's rail layout), `SectionNav.tsx` (sidebar section jump-list).
- **`components/repository/`** — `UploadSops.tsx` (drag-and-drop multi-file picker → `api.uploadBatch`), `JobProgressBanner.tsx` (renders `BatchJob` progress from `useJobPolling`), `SopTable.tsx`/`SopGrid.tsx` (two renderings of the same filtered SOP list).
- **`components/review/`** — `ExtractionReviewMode.tsx`, `MigrationReviewMode.tsx`, `TranslationReviewMode.tsx` (per-mode 3-column panel layouts), `ContentEditor.tsx` (currently a plain textarea editor with a static save-status indicator — `@tiptap/react`/`@tiptap/starter-kit` are installed dependencies but not yet wired into it), `OriginalDocumentViewer.tsx` (PDF iframe with zoom + bbox highlight; DOCX shows a download prompt instead of inline rendering), `IssuePanel.tsx`, `GlossaryPanel.tsx` (static demo glossary data), `MigrationValidationPanel.tsx` (renders `MigrationQAReport`), `TranslationQaPanel.tsx` (static demo QA checklist), `ReprocessingRequestDialog.tsx`, `ActionFooter.tsx`, `ReviewHeader.tsx`. Two components exist but are **not currently mounted** in any review mode: `CompareView.tsx` (side-by-side diff view) and `VersionHistory.tsx` (workflow version timeline/restore) — both are built ahead of their integration point.
- **`components/ai/AISuggestionPanel.tsx`** — accept/reject UI for AI-proposed content patches.
- **`components/ui/`** — design-system primitives (`Button`, `ConfirmDialog`, `FileTypeIcon`, `FilterBar`, `SearchBar`, `StatCards`, `StatusBadge`, `ThemeToggle`, `ToastStack`).
- **`components/layout/`** — `AppHeader`, `Layout`, `Sidebar` (the authenticated app shell).

### 16.6 Utility Hooks

- **`lib/useJobPolling.ts`** — polls `GET /jobs/{id}` at a 1.5s interval (backs off to 2× on error) until terminal state, invoking `onComplete`/`onError`; used by `SopRepository` after a batch upload. **Batch job progress is HTTP-polled, not WebSocket-driven**, even though the backend exposes `WS /jobs/{job_id}/progress`.
- **`lib/useWorkflowSocket.ts`** — a WebSocket client for `WorkflowProgressEnvelope` events at `/workflows/{workflowId}/progress` (the review bootstrap's `links.websocket`). Implemented but **not currently used** by any page — a ready-made integration point for real-time review/workflow progress that hasn't been wired up yet.
- **`lib/useAutosave.ts`** — a debounced (800ms) autosave hook with a full status state machine (idle/unsaved/saving/saved/error/conflict-409). Its types are imported by `ContentEditor.tsx`, but the hook itself is **not yet wired in** — the editor currently shows a static "saved" indicator.
- **`lib/sopDisplay.ts`** — `getDisplayTitle`/`getDisplaySubline` — consistent title/subtitle formatting across list/detail views given the multiple possibly-null title fields (`document_title`/`document_name`/`document_Uid`).
- **`lib/stats.ts`** — `calculateRepositoryStats(sops, activeJob)` for the `StatCards`.
- **`lib/format.ts`** — date/number formatting helpers.
- **`lib/theme.ts`** — light/dark theme handling for `ThemeToggle`.

---

## 17. End-to-End Data Flow

### 17.1 Upload → Extraction

```
Browser: select files → POST /documents/upload/batch (multipart)
  → upload.py validates each file, extracts preamble metadata (SOPMetadataExtractor)
    to compute a stable document_id, saves valid files to upload_dir
  → JobManager.create_batch_job(document_ids, user_id, user_email, correlation_id)
    stamped from request.state (set by LoggingContextMiddleware)
  → returns BatchJob immediately (202-style async pattern, though modeled as 200)

Browser: useJobPolling polls GET /jobs/{job_id} (or opens WS /jobs/{job_id}/progress)

Background (JobManager worker, one at a time):
  parse (ParserFactory → PDFParser/DocxParser, includes PDFLayoutAnalyzer)
    → tables (TableExtractor → CrossPageTableStitcher)
    → icons (IconExtractor → CaptionExtractor)
    → ast (ASTBuilder.build)
    → chunk (HierarchicalChunker → SemanticChunker)
    → export (MigrationExporter.export → write {document_id}_v2.json,
              SopStore.upsert_record)

Browser: on job completion → invalidate ['sops'] query → repository refreshes
```

### 17.2 Viewing Content

```
GET /documents/v2/{document_id}/json
  → read {document_id}_v2.json from output_dir
  → _rewrite_asset_paths(): image_path/icon_path/path → /documents/{id}/assets/{filename}
  → returned DocxMigrationOutput JSON
Browser: SopContentView / ReviewPage render via ElementRenderer,
  images/icons fetched from GET /documents/{id}/assets/{filename}
```

### 17.3 Migration

```
Browser: POST /documents/migrate (document_id [+ optional template_file])
  → migration.py resolves the extracted JSON (exact match → sop_store lookup → glob)
  → DocxMigrator.migrate():
      Phase 1: TemplateInspector + ContentSummarizer/LLMSectionSummarizer
      Phase 2: SectionAligner → LLM → MigrationPlan
      Phase 3: InstructionCleaner + TableMigrator + DocxStyler + CalloutBuilder
               execute plan into a python-docx Document
      Phase 4: TOCBuilder inserts native TOC field; save .docx
      Phase 5: MigrationValidator → MigrationQAReport
  → persist plan_*.json, qa_*.json, migrated_*.docx
  → return MigrationResult { output_path, plan, qa_report, download_url }
Browser: MigrationValidationPanel shows QA report; download via
  GET /documents/{id}/download-docx
```

---

## 18. Error Handling Architecture

Three layers, matched to where a failure can occur (see also [§8.1–8.2](#8-backend-core-cross-cutting-concerns)):

1. **Domain exceptions** — services raise `AppError`/`NotFoundError`/`LoginError`/`SignupError`, never `HTTPException`, so error semantics don't leak the web framework into service code.
2. **Central FastAPI handlers** (`app/core/exception_handlers.py`) — the only place that converts an exception into an HTTP response, in specificity order (`AppError` → `RequestValidationError` → `HTTPException` → catch-all `Exception`). All 5xx paths log a full traceback; only a generic message ever reaches the client.
3. **Job worker boundary** (`JobManager._process_document`) — background job failures are *not* HTTP; they're caught once, logged with `logger.exception`, and surfaced through the polled `DocumentJob.error`/`status=FAILED` fields instead of an HTTP error response, since the original upload request has long since returned.

Local, best-effort `except Exception` blocks remain **inside** extractors (e.g., skip one unreadable icon, one malformed table cell) — those are intentionally not promoted to `AppError`; they represent "best effort — continue," which a global handler cannot express.

Frontend (`frontend/src/lib/api.ts`) consumes the uniform `ApiErrorResponse` envelope, preferring `error.message`/`error.code` over legacy `detail`/`message` fields for backward compatibility during the transition.

---

## 19. Logging & Observability

Two **intentionally separate** logging stores:

| Store | Table | Captures | Owner |
|---|---|---|---|
| `data/auth.db` | `audit_events` | Security-relevant identity/session events (login/logout/lockout/token reuse) — permanent audit trail | `AuthStore` |
| `data/logs/logs.db` | `logs` | HTTP request + extraction-pipeline operational logs, pruned after 14 days | `app/core/logging_config.py` |

Both can be joined by `correlation_id` for support/debugging without merging their retention or purpose. See [§8.3–8.4](#8-backend-core-cross-cutting-concerns) for sink configuration and [§13](#13-backend-job-manager) for how pipeline stages are contextualized.

Representative diagnostic queries:

```sql
-- Full timeline for one document across parse→export
SELECT timestamp, level, stage, user_id, message FROM logs WHERE document_id = ? ORDER BY id;

-- Everything a given user triggered
SELECT timestamp, stage, document_id, message FROM logs WHERE user_id = ? ORDER BY id;

-- Cross-store trace for a support ticket (same correlation_id in both DBs)
SELECT * FROM logs WHERE correlation_id = ? ORDER BY id;
SELECT * FROM audit_events WHERE correlation_id = ?;
```

`logger_name` (module) + `function` + `line` columns mean **no extra instrumentation is needed per-feature** — e.g. `WHERE logger_name LIKE '%icons%'` isolates all icon-extractor activity for a document without any code changes.

---

## 20. Security Notes

- Passwords and secret-question answers are hashed with **Argon2id** (`argon2-cffi`), never stored or logged in plaintext.
- Refresh tokens are random 256-bit values; only their **SHA-256 hash** is persisted server-side; the raw value only ever exists in the `HttpOnly` cookie.
- Refresh token **rotation with family-based reuse detection** — presenting an already-rotated (revoked) token revokes the whole family and forces re-login, mitigating stolen-cookie replay.
- Login has both per-account lockout and per-IP rate limiting, plus timing-attack defense (dummy hash verify on unknown email) to avoid user-enumeration via response latency.
- JWT access tokens are short-lived (15 minutes default) and carry minimal claims (`sub`, `email`, `role`, `sid`); they are **not** stored in `localStorage` by the frontend's design intent — they're kept in memory (Zustand store) and silently refreshed via the HttpOnly cookie.
- CORS is locked to explicit local dev origins; `allow_credentials=True` is required for the refresh cookie to flow cross-origin during local development (frontend `:5173` / backend `:8000`).
- The SOP/document/migration API surface is **not** currently JWT-enforced (see [§24](#24-known-limitations--future-work)) — only `/api/v1/auth/*` performs authentication/authorization checks; other routes optionally attribute activity to a user if a valid Bearer token happens to be present.
- No secrets (passwords, tokens, cookies) are ever written to `logs.db`/`app.log`/`error.log` or to API error bodies — enforced by convention in the logging/exception-handling design (see `LOGGING_IMPLEMENTATION.md` "What not to do").

---

## 21. Testing

Backend tests live in `tests/` (pytest + `pytest-asyncio` + `httpx`), run inside the `extraction-env` conda environment referenced throughout `CHANGES.md`. Notable suites:

| Test file | Covers |
|---|---|
| `test_api.py` | End-to-end API endpoint behavior, including the `ApiErrorResponse` shape. |
| `test_auth.py` / `test_auth_login.py` | Signup/login/refresh/logout flows, lockout, rate limiting. |
| `test_exception_handlers.py` | `AppError`/`HTTPException`/catch-all → `ApiErrorResponse` mapping, no internal leakage. |
| `test_logging_config.py` | `setup_logging` sinks write rows, context fields populate correctly, idempotency. |
| `test_ast_phase1.py` | AST building, rail-icon Y-binding correctness. |
| `test_asset_management.py` | Asset path serving and asset manifest building. |
| `test_chunking.py` | Hierarchical + semantic chunking. |
| `test_validation.py` | `ChunkValidator` rules (empty chunk, oversized chunk). |
| `test_metadata_extractor.py` | SOP preamble metadata parsing. |
| `test_cross_page_stitcher.py` | Multi-page table stitching. |
| `test_table_cleanup.py` | Sparse-grid collapsing, callout detection. |
| `test_migration_exporter.py` | Section reclaim, icon Y-rebind logic. |
| `test_content_summarizer.py` | Mode A summarization. |
| `test_llm_section_summarizer.py` | Mode B summarization (mocked LLM). |
| `test_template_inspector.py` | Template profiling (blue text, placeholder tables). |
| `test_section_aligner.py` | Migration planning (mocked LLM). |
| `test_instruction_cleaner_and_tables.py` | Template scaffolding cleanup + table helper functions. |
| `test_docx_migrator.py` / `test_docx_styler.py` / `test_table_migrator.py` | Migration execution / styling / table construction. |
| `test_job_manager.py` | Background job lifecycle. |

Run with:
```powershell
conda run -n extraction-env pytest
conda run -n extraction-env pytest -v tests/test_logging_config.py tests/test_exception_handlers.py
```

Frontend currently has no automated test suite configured (`npm run lint` via `oxlint` only) — see [§24](#24-known-limitations--future-work).

---

## 22. Configuration Reference

All settings are defined in `app/config/settings.py`, prefixed `SOP_` in the environment (e.g. `SOP_LOG_LEVEL`), loaded from `.env` via `pydantic-settings`. See `.env.example` for the maintained list of commonly-overridden keys.

| Category | Setting | Default |
|---|---|---|
| Paths | `upload_dir` | `data/uploads` |
| | `extracted_images_dir` | `data/extracted_images` |
| | `extracted_icons_dir` | `data/extracted_icons` |
| | `temp_dir` | `data/temp` |
| | `output_dir` | `data/output` |
| Processing | `max_upload_size_mb` | `50` |
| | `allowed_extensions` | `[".pdf", ".docx"]` |
| | `ocr_enabled` / `ocr_language` | `False` / `"eng"` |
| Semantic chunking | `embedding_model` | `"all-MiniLM-L6-v2"` |
| | `similarity_threshold` | `0.4` |
| Watermark filtering | `watermark_keywords` | `WORKING COPY, DRAFT, CONFIDENTIAL, DO NOT DISTRIBUTE, WATERMARK` |
| Table stitching | `table_stitch_enabled` | `True` |
| | `table_stitch_score_threshold` | `0.7` |
| | `table_stitch_column_tolerance_pt` | `15.0` |
| | `table_stitch_bottom_zone_pct` | `0.75` |
| | `table_stitch_top_zone_pct` | `0.20` |
| Logging | `log_level` | `"INFO"` |
| | `log_dir` / `log_file_path` / `error_file_path` / `log_db_path` | `data/logs/...` |
| Migration | `migration_output_dir` / `migration_template_dir` | `data/migrated` / `data/templates` |
| | `skip_preamble_migration` | `True` |
| LLM | `use_llm_section_summarizer` | `False` (Mode A) |
| | `llm_planner_model` / `llm_summarizer_model` | `"gemini/gemini-2.5-flash"` |
| | `llm_temperature` | `0.1` |
| | `llm_planner_max_tokens` / `llm_summarizer_max_tokens` | `16384` / `4096` |
| Azure OpenAI | `use_azure_openai` | `False` |
| | `azure_openai_endpoint` / `azure_openai_api_version` | `None` / `"2024-12-01-preview"` |
| | `azure_openai_planner_deployment` / `azure_openai_summarizer_deployment` | `"gpt-4o"` / `"gpt-4o-mini"` |
| | `azure_openai_api_key` | via `AZURE_OPENAI_API_KEY` env (no `SOP_` prefix) |
| LLM rate limiting | `llm_max_concurrent` | `3` |
| | `llm_min_delay_seconds` | `0.5` |
| | `llm_max_retries` | `5` |
| | `llm_base_backoff_seconds` | `2.0` |
| Auth/JWT | `jwt_secret_key` | dev default (**change in production**) |
| | `jwt_algorithm` | `"HS256"` |
| | `jwt_access_token_expire_seconds` | `900` |
| | `jwt_issuer` / `jwt_audience` | `"governance-sop-api"` / `"governance-sop-web"` |
| | `auth_refresh_token_expire_days` / `auth_remember_me_expire_days` | `1` / `30` |
| | `auth_max_failed_attempts` / `auth_lockout_duration_minutes` | `5` / `15` |
| | `auth_ip_rate_limit_max_attempts` / `_window_minutes` | `10` / `15` |
| | `auth_cookie_secure` | `False` (set `True` behind HTTPS) |

---

## 23. Running Locally

### Backend
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
- Swagger UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### Frontend
```powershell
cd frontend
npm install
npm run dev
```
- App: `http://localhost:5173`

### Tests
```powershell
conda run -n extraction-env pytest -v
```

---

## 24. Known Limitations & Future Work

These are deliberate POC trade-offs, documented so they're not mistaken for oversights:

- **No auth enforcement on document/SOP/migration routes** — only `/api/v1/auth/*` is authenticated; other routes optionally attribute activity via `LoggingContextMiddleware`'s best-effort JWT decode. Adding a `Depends()` that *requires* a valid JWT on upload/migrate is called out as a natural next step in `LOGGING_IMPLEMENTATION.md`.
- **In-memory job state** — `JobManager.jobs` and `BatchJob` progress are lost on process restart; there is no persistence or resume for in-flight batches.
- **Single-worker concurrency** (`concurrency=1`) — extraction jobs process strictly one at a time; increasing this is possible but untested against SQLite write contention in `SopStore`.
- **No external log aggregation** — SQLite + rotating files only, by design for a local POC; `loguru`'s `serialize=True` is called out as a clean upgrade path to structured JSON export if a future aggregator (Datadog/ELK/Loki) is introduced.
- **Frontend has several endpoints with mock/fallback behavior** (`getIssues`, `createIssue`, `getReprocessingRequests`, `approveWorkflow`, `saveDraft`) — these degrade to client-side mock data when the corresponding backend endpoint isn't implemented yet (workflow/issue-tracking persistence is not yet built out server-side). Similarly, `ReprocessingAdminPage`'s Approve/Reject buttons currently only update local React state and show a toast — `api.decideReprocessingRequest()` exists in `lib/api.ts` but is not yet called from the page, so admin decisions are not yet persisted or wired to actually re-queue a job.
- **No frontend automated test suite** — only `oxlint` is configured; component/integration tests are not yet in place.
- **Translation Review mode UI exists but has no dedicated backend** — it reuses the same review bootstrap/content endpoints as extraction review; a real translation pipeline is not implemented, and the source/target panes use partially static/demo content.
- **No role-based route guards** — `UserRole` (`ADMIN`/`POWER_USER`/`REGULAR_USER`) is modeled in the frontend types, but every role currently lands on the same `/` landing route; there is no per-role UI restriction (e.g., `/admin/reprocessing` is reachable by any authenticated user).
- **`LoginForm` links to `/forgot-password`**, but no corresponding page/route or backend password-reset flow is implemented yet.
- **OCR is not wired into the PDF parser** — `settings.ocr_enabled`/`ocr_language` exist and `ImageNode` has `ocr_text`/`ocr_confidence` fields, but `PDFParser` does not currently invoke `pytesseract`.
- **`settings.embedding_model` (`all-MiniLM-L6-v2`) is currently vestigial** — `SemanticChunker` uses TF-IDF + cosine similarity (scikit-learn) rather than a sentence-transformer embedding model, so this setting has no effect on chunking behavior today.
- **`frontend/src/lib/apiClient.ts`** is a second, parallel authenticated-fetch implementation (with its own 401-retry-after-refresh logic) that exists alongside `lib/api.ts` but is not the one actually used by the app's pages — a candidate for consolidation.
- **RFC 7807 Problem Details was considered and rejected** in favor of reusing the existing auth `ApiErrorResponse` envelope for all APIs, to avoid maintaining two error formats (see `LOGGING_IMPLEMENTATION.md`).
