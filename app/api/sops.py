"""SOP Repository endpoints — CRUD and status management for SOP records."""

from typing import Optional, Any
from pydantic import BaseModel
from fastapi import APIRouter, Request, Query

from app.core.exceptions import AppError, NotFoundError

router = APIRouter(prefix="/sops", tags=["SOPs"])


class StatusUpdateRequest(BaseModel):
    status: str


@router.get("")
async def list_sops(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status: in_review, approved, rejected"),
    document_uid: Optional[str] = Query(None, description="Filter by document UID"),
    limit: int = Query(1000, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List all SOP records with optional filters."""
    sop_store = getattr(request.app.state, "sop_store", None)
    if not sop_store:
        return []
    return sop_store.get_records(status=status, document_uid=document_uid, limit=limit, offset=offset)


@router.get("/{record_id}")
async def get_sop_record(
    record_id: int,
    request: Request,
) -> dict[str, Any]:
    """Retrieve a single SOP record by its ID."""
    sop_store = getattr(request.app.state, "sop_store", None)
    if not sop_store:
        raise NotFoundError("SOP store not initialized", code="SOP_STORE_UNAVAILABLE")
    record = sop_store.get_record_by_id(record_id)
    if not record:
        raise NotFoundError(f"SOP record {record_id} not found", code="SOP_NOT_FOUND")
    return record


@router.patch("/{record_id}/status")
async def update_sop_status(
    record_id: int,
    body: StatusUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    """Update the review status of an SOP record."""
    if body.status not in ("in_review", "approved", "rejected"):
        raise AppError(
            status_code=400,
            code="INVALID_STATUS",
            message="Invalid status. Must be in_review, approved, or rejected.",
        )

    sop_store = getattr(request.app.state, "sop_store", None)
    if not sop_store:
        raise NotFoundError("SOP store not initialized", code="SOP_STORE_UNAVAILABLE")

    updated = sop_store.update_status(record_id, body.status)
    if not updated:
        raise NotFoundError(f"SOP record {record_id} not found", code="SOP_NOT_FOUND")
    return updated


@router.delete("/{record_id}")
async def delete_sop_record(
    record_id: int,
    request: Request,
) -> dict[str, Any]:
    """Delete an SOP record with smart cleanup of underlying files."""
    sop_store = getattr(request.app.state, "sop_store", None)
    if not sop_store:
        raise NotFoundError("SOP store not initialized", code="SOP_STORE_UNAVAILABLE")

    deleted = sop_store.delete_record(record_id)
    if not deleted:
        raise NotFoundError(f"SOP record {record_id} not found", code="SOP_NOT_FOUND")
    return {"message": f"SOP record {record_id} deleted successfully."}
