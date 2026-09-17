"""Upload endpoint — receives PDF / DOCX files and stores them."""

import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.schemas.jobs import BatchJob
from app.services.extraction.metadata_extractor import SOPMetadataExtractor

router = APIRouter(prefix="/documents", tags=["Documents"])


def _preview_gpdat_version(settings: Settings, document_id: str) -> int:
    """Return the gpdat_version this upload will become once processed."""
    try:
        from app.stores.sop_store import SopStore

        sop_store = getattr(settings, "_sop_store", None)
        if sop_store is None:
            db_path = settings.project_root / "data" / "sop_records.db"
            sop_store = SopStore(db_path, settings)
        return sop_store.get_next_version(document_id)
    except Exception:
        return 1


class UploadResponse(BaseModel):
    """Schema returned after a successful upload."""
    document_id: str
    filename: str
    file_type: str
    size_bytes: int
    message: str
    already_uploaded: bool = False
    duplicate_upload_count: int = 0


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    """Accept a PDF or DOCX file upload, validate, and persist to disk."""

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    extension = Path(file.filename).suffix.lower()
    if extension not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{extension}'. Allowed: {settings.allowed_extensions}",
        )

    contents = await file.read()
    size_bytes = len(contents)
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    if size_bytes > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_size_mb} MB limit.")

    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Write to a temporary file to extract first-page metadata
    temp_path = settings.temp_dir / f"temp_{uuid.uuid4()}{extension}"
    with open(temp_path, "wb") as f:
        f.write(contents)

    doc_title, doc_name, doc_num, doc_ver, _ = SOPMetadataExtractor.extract_from_file(
        str(temp_path), fallback_filename=file.filename
    )
    document_id = SOPMetadataExtractor.generate_document_id(
        doc_name or doc_title, doc_num, doc_ver, fallback_filename=file.filename
    )
    upload_count = _preview_gpdat_version(settings, document_id)
    already_uploaded = upload_count > 1

    dest = settings.upload_dir / f"{document_id}{extension}"
    with open(dest, "wb") as f:
        f.write(contents)

    temp_path.unlink(missing_ok=True)

    msg = "Upload successful. Use POST /documents/extract to process."
    if already_uploaded:
        msg = f"Document '{document_id}' was previously uploaded (upload count: {upload_count}). Re-extracting."

    return UploadResponse(
        document_id=document_id,
        filename=file.filename,
        file_type=extension.lstrip("."),
        size_bytes=size_bytes,
        message=msg,
        already_uploaded=already_uploaded,
        duplicate_upload_count=upload_count,
    )


@router.post("/upload/batch", response_model=BatchJob)
async def upload_documents_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    settings: Settings = Depends(get_settings),
):
    """Accept multiple PDF or DOCX file uploads, validate, and enqueue a batch job."""
    document_ids = []
    
    for file in files:
        if not file.filename:
            continue

        extension = Path(file.filename).suffix.lower()
        if extension not in settings.allowed_extensions:
            continue

        contents = await file.read()
        size_bytes = len(contents)
        max_bytes = settings.max_upload_size_mb * 1024 * 1024

        if size_bytes > max_bytes or size_bytes == 0:
            continue

        temp_path = settings.temp_dir / f"temp_{uuid.uuid4()}{extension}"
        with open(temp_path, "wb") as f:
            f.write(contents)

        doc_title, doc_name, doc_num, doc_ver, _ = SOPMetadataExtractor.extract_from_file(
            str(temp_path), fallback_filename=file.filename
        )
        document_id = SOPMetadataExtractor.generate_document_id(
            doc_name or doc_title, doc_num, doc_ver, fallback_filename=file.filename
        )

        dest = settings.upload_dir / f"{document_id}{extension}"
        with open(dest, "wb") as f:
            f.write(contents)

        temp_path.unlink(missing_ok=True)
        document_ids.append(document_id)
        
    if not document_ids:
        raise HTTPException(
            status_code=400,
            detail="No valid files were uploaded in the batch."
        )

    job_manager = request.app.state.job_manager
    job = job_manager.create_batch_job(
        document_ids,
        user_id=getattr(request.state, "user_id", None),
        user_email=getattr(request.state, "user_email", None),
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    
    return job
