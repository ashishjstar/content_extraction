"""Review bootstrap and configuration endpoint for Common Review Page."""

from typing import Optional, Any
from fastapi import APIRouter, Depends, Request, Query

from app.config.settings import Settings, get_settings
from app.core.exceptions import NotFoundError

router = APIRouter(prefix="/review", tags=["Review"])


@router.get("/{record_id}")
async def get_review_bootstrap(
    record_id: int,
    request: Request,
    mode: str = Query("review", description="Review mode: review | translation | migration"),
    workflow_id: Optional[str] = Query(None, alias="workflowId"),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the configuration, layout, and metadata bootstrap for the Common Review Page."""
    sop_store = getattr(request.app.state, "sop_store", None)
    if not sop_store:
        raise NotFoundError("SOP store not initialized", code="SOP_STORE_UNAVAILABLE")

    record = sop_store.get_record_by_id(record_id)
    if not record:
        raise NotFoundError(f"SOP record {record_id} not found", code="SOP_NOT_FOUND")

    w_id = workflow_id or f"{mode[:3]}_{record_id:02d}"

    # Determine layout based on mode
    if mode == "translation":
        layout = {
            "leftPanel": "SOURCE_CONTENT",
            "rightPanel": "TRANSLATED_CONTENT",
            "showOriginalViewer": True,
            "showAiSuggestions": True,
            "showCompareView": True,
            "showVersionHistory": True,
            "showIssuePanel": True,
        }
        actions = [
            "AI_TRANSLATE",
            "ACCEPT_SUGGESTION",
            "EDIT",
            "SAVE",
            "RUN_QA",
            "APPROVE",
        ]
        links = {
            "content": f"/translations/{w_id}/segments",
            "versions": f"/workflows/{w_id}/versions",
            "issues": f"/issues?workflow_id={w_id}",
            "websocket": f"/workflows/{w_id}/progress",
        }
    elif mode == "migration":
        layout = {
            "leftPanel": "CURRENT_FORMAT",
            "rightPanel": "MIGRATED_FORMAT",
            "showOriginalViewer": True,
            "showAiSuggestions": True,
            "showCompareView": True,
            "showVersionHistory": True,
            "showIssuePanel": True,
        }
        actions = [
            "AI_MIGRATE",
            "ACCEPT_SUGGESTION",
            "EDIT",
            "APPLY_TEMPLATE",
            "VALIDATE",
            "SAVE",
            "RENDER_PREVIEW",
            "APPROVE",
        ]
        links = {
            "content": f"/migrations/{w_id}/sections",
            "versions": f"/workflows/{w_id}/versions",
            "issues": f"/issues?workflow_id={w_id}",
            "websocket": f"/workflows/{w_id}/progress",
        }
    else:  # Extraction review mode
        layout = {
            "leftPanel": "ORIGINAL_DOCUMENT",
            "rightPanel": "EXTRACTED_CONTENT",
            "showOriginalViewer": True,
            "showAiSuggestions": True,
            "showCompareView": True,
            "showVersionHistory": True,
            "showIssuePanel": True,
        }
        actions = [
            "EDIT",
            "SAVE",
            "REPORT_ISSUE",
            "REQUEST_REPROCESSING",
            "RESOLVE_WARNING",
            "APPROVE",
        ]
        links = {
            "content": f"/documents/v2/{record['document_Uid']}/json",
            "versions": f"/workflows/{w_id}/versions",
            "issues": f"/issues?workflow_id={w_id}",
            "websocket": f"/workflows/{w_id}/progress",
        }

    return {
        "document": {
            "recordId": record["id"],
            "documentUid": record["document_Uid"],
            "title": record.get("document_title") or record.get("document_name") or record["document_Uid"],
            "sopNumber": record.get("document_number"),
            "version": record.get("document_version") or "1.0",
            "fileType": record.get("file_type") or "pdf",
            "pageCount": record.get("page_count", 0),
        },
        "reviewContext": {
            "mode": mode,
            "workflowId": w_id,
            "workflowVersion": 1,
            "status": record.get("status", "in_review"),
            "sourceLocale": record.get("language", "en"),
            "targetLocale": "fr" if mode == "translation" else None,
            "rowVersion": 1,
        },
        "layout": layout,
        "availableActions": actions,
        "links": links,
    }
