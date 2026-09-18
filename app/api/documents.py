"""Document detail endpoints — retrieve parsed content by document_id."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.config.settings import Settings, get_settings
from app.core.exceptions import AppError, NotFoundError
from app.services.parser import ParserFactory
from app.services.extraction import TableExtractor, CrossPageTableStitcher, IconExtractor, CaptionExtractor
from app.services.hierarchy.ast_builder import ASTBuilder
from app.services.chunking.hierarchical import HierarchicalChunker
from app.services.chunking.semantic import SemanticChunker
from app.services.chunking.validator import ChunkValidator
from app.services.export.json_export import JSONExporter
from app.schemas.document import DocumentOutput

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the full parsed RawDocument as JSON for inspection."""

    upload_path = _find_upload(document_id, settings)

    factory = ParserFactory(settings=settings)
    parser = factory.get_parser(str(upload_path))
    raw_document = parser.parse(str(upload_path))

    return raw_document.model_dump()


@router.get("/{document_id}/elements")
async def get_document_elements(
    document_id: str,
    page: int | None = None,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return a flat list of all extracted elements, optionally filtered
    by page number.
    """

    upload_path = _find_upload(document_id, settings)

    factory = ParserFactory(settings=settings)
    parser = factory.get_parser(str(upload_path))
    raw_document = parser.parse(str(upload_path))

    elements = []
    for pg in raw_document.pages:
        if page is not None and pg.page_number != page:
            continue
        for el in pg.elements:
            elements.append(el.model_dump())

    return {
        "document_id": document_id,
        "total_elements": len(elements),
        "page_filter": page,
        "elements": elements,
    }


@router.get("/{document_id}/tree")
async def get_document_tree(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the nested hierarchical structure of the document."""

    upload_path = _find_upload(document_id, settings)

    factory = ParserFactory(settings=settings)
    parser = factory.get_parser(str(upload_path))
    raw_document = parser.parse(str(upload_path))

    extractors = [
        TableExtractor(settings=settings),
        CrossPageTableStitcher(settings=settings),
        IconExtractor(settings=settings),
        CaptionExtractor(settings=settings),
    ]
    
    for extractor in extractors:
        raw_document = extractor.extract(raw_document)

    ast_builder = ASTBuilder(settings=settings)
    document_node = ast_builder.build(raw_document)

    return document_node.model_dump()


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the document split into refined chunks."""
    
    upload_path = _find_upload(document_id, settings)

    factory = ParserFactory(settings=settings)
    parser = factory.get_parser(str(upload_path))
    raw_document = parser.parse(str(upload_path))

    extractors = [
        TableExtractor(settings=settings),
        CrossPageTableStitcher(settings=settings),
        IconExtractor(settings=settings),
        CaptionExtractor(settings=settings),
    ]
    for extractor in extractors:
        raw_document = extractor.extract(raw_document)

    ast_builder = ASTBuilder(settings=settings)
    document_node = ast_builder.build(raw_document)

    # Chunking pipeline
    hierarchical_chunker = HierarchicalChunker(settings=settings)
    chunks = hierarchical_chunker.chunk(document_node)

    semantic_chunker = SemanticChunker(settings=settings)
    refined_chunks = semantic_chunker.chunk(chunks)

    # 5. Validation
    validator = ChunkValidator(settings=settings)
    is_valid, warnings = validator.validate(refined_chunks)

    doc_output = DocumentOutput(
        document_id=document_id,
        title=document_node.doc_metadata.title or upload_path.stem,
        chunks=refined_chunks,
        validation_passed=is_valid,
        validation_warnings=warnings,
    )

    return doc_output.model_dump()


@router.get("/{document_id}/json")
async def export_document_json(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Export the fully processed document chunks as JSON."""

    upload_path = _find_upload(document_id, settings)

    # 1. Parse
    factory = ParserFactory(settings=settings)
    parser = factory.get_parser(str(upload_path))
    raw_document = parser.parse(str(upload_path))

    # 2. Extractors
    extractors = [
        TableExtractor(settings=settings),
        CrossPageTableStitcher(settings=settings),
        IconExtractor(settings=settings),
        CaptionExtractor(settings=settings),
    ]
    for extractor in extractors:
        raw_document = extractor.extract(raw_document)

    # 3. AST Generation
    ast_builder = ASTBuilder(settings=settings)
    document_node = ast_builder.build(raw_document)

    # 4. Chunking
    hierarchical_chunker = HierarchicalChunker(settings=settings)
    chunks = hierarchical_chunker.chunk(document_node)

    semantic_chunker = SemanticChunker(settings=settings)
    refined_chunks = semantic_chunker.chunk(chunks)

    # 5. Validation
    validator = ChunkValidator(settings=settings)
    is_valid, warnings = validator.validate(refined_chunks)

    doc_output = DocumentOutput(
        document_id=document_id,
        title=document_node.doc_metadata.title or upload_path.stem,
        chunks=refined_chunks,
        validation_passed=is_valid,
        validation_warnings=warnings,
    )

    # 6. Export to disk using JSONExporter
    output_dir = Path("data/output")
    output_path = str(output_dir / f"{document_id}.json")
    
    exporter = JSONExporter(settings=settings)
    exporter.export(doc_output, output_path)

    return doc_output.model_dump()


@router.get("/v2/{document_id}/json")
async def get_document_json_v2(
    document_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Export the fully processed document AST as JSON (v2).
    
    This retrieves the completed extraction from the background job queue's
    saved disk output.
    """
    output_dir = settings.output_dir
    output_path = output_dir / f"{document_id}_v2.json"
    
    if not output_path.exists():
        raise NotFoundError(
            f"v2 JSON for document '{document_id}' not found. Did the job complete?",
            code="DOCUMENT_JSON_NOT_FOUND",
        )

    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AppError(
            status_code=422,
            code="INVALID_EXTRACTED_JSON",
            message="Stored v2 JSON could not be read.",
        )

    return _rewrite_asset_paths(data, document_id)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: str,
    settings: Settings = Depends(get_settings),
):
    """Serve the original uploaded PDF or DOCX file."""
    upload_path = _find_upload(document_id, settings)
    media_type = "application/pdf" if upload_path.suffix.lower() == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    from fastapi.responses import FileResponse
    return FileResponse(path=str(upload_path), media_type=media_type, filename=upload_path.name)


@router.get("/{document_id}/assets/{filename}")
async def get_document_asset(
    document_id: str,
    filename: str,
    settings: Settings = Depends(get_settings),
):
    """Serve extracted image or icon assets with path traversal protection."""
    from fastapi.responses import FileResponse
    safe_name = Path(filename).name

    # Check images directory first
    img_path = settings.get_document_image_dir(document_id) / safe_name
    if img_path.exists() and img_path.is_file():
        return FileResponse(path=str(img_path), media_type="image/png")

    # Check icons directory next
    icon_path = settings.get_document_icon_dir(document_id) / safe_name
    if icon_path.exists() and icon_path.is_file():
        return FileResponse(path=str(icon_path), media_type="image/png")

    raise NotFoundError(
        f"Asset '{safe_name}' not found for document '{document_id}'",
        code="ASSET_NOT_FOUND",
    )


# ── Helper ──────────────────────────────────────────────────────────────

_ASSET_PATH_KEYS = ("image_path", "icon_path", "path")


def _rewrite_asset_paths(node: Any, document_id: str) -> Any:
    """Rewrite absolute on-disk asset paths into servable URLs.

    Walks the v2 JSON in place and replaces ``image_path`` / ``icon_path`` /
    ``path`` string values with ``/documents/{document_id}/assets/{basename}``.
    """
    if isinstance(node, dict):
        for key in _ASSET_PATH_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value:
                node[key] = f"/documents/{document_id}/assets/{Path(value).name}"
        for value in node.values():
            _rewrite_asset_paths(value, document_id)
    elif isinstance(node, list):
        for item in node:
            _rewrite_asset_paths(item, document_id)
    return node


def _find_upload(document_id: str, settings: Settings) -> Path:
    """Locate the uploaded file for *document_id* or raise 404."""
    for ext in settings.allowed_extensions:
        candidate = settings.upload_dir / f"{document_id}{ext}"
        if candidate.exists():
            return candidate

    raise NotFoundError(
        f"No uploaded file found for document_id '{document_id}'.",
        code="DOCUMENT_NOT_FOUND",
    )
