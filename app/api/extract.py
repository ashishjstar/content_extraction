"""Extract endpoint — triggers the extraction pipeline for an uploaded document."""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.core.exceptions import AppError, NotFoundError
from app.services.parser import ParserFactory
from app.services.extraction import TableExtractor, CrossPageTableStitcher, IconExtractor, CaptionExtractor
from app.services.hierarchy.ast_builder import ASTBuilder

router = APIRouter(prefix="/documents", tags=["Documents"])


class ExtractRequest(BaseModel):
    """Payload for the extraction trigger."""
    document_id: str


class ExtractResponse(BaseModel):
    """Structured response after extraction completes."""
    document_id: str
    status: str
    title: str
    file_type: str
    page_count: int
    total_elements: int
    element_summary: dict[str, int]
    message: str


@router.post("/extract", response_model=ExtractResponse)
async def extract_document(
    request: ExtractRequest,
    settings: Settings = Depends(get_settings),
):
    """Run the parser on a previously uploaded document and return
    a summary of extracted elements.
    """

    # ── Locate the uploaded file ────────────────────────────────────
    upload_path: Path | None = None
    for ext in settings.allowed_extensions:
        candidate = settings.upload_dir / f"{request.document_id}{ext}"
        if candidate.exists():
            upload_path = candidate
            break

    if upload_path is None:
        raise NotFoundError(
            f"No uploaded file found for document_id '{request.document_id}'.",
            code="DOCUMENT_NOT_FOUND",
        )

    # ── Parse ───────────────────────────────────────────────────────
    try:
        factory = ParserFactory(settings=settings)
        parser = factory.get_parser(str(upload_path))
        raw_document = parser.parse(str(upload_path))
        
        # ── Advanced Extraction Pipeline ────────────────────────────────
        extractors = [
            TableExtractor(settings=settings),
            CrossPageTableStitcher(settings=settings),
            IconExtractor(settings=settings),
            CaptionExtractor(settings=settings),
        ]
        
        for extractor in extractors:
            raw_document = extractor.extract(raw_document)
            
        # ── AST Generation ─────────────────────────────────────
        ast_builder = ASTBuilder(settings=settings)
        document_node = ast_builder.build(raw_document)
            
    except ValueError as e:
        raise AppError(status_code=400, code="BAD_REQUEST", message=str(e)) from e
    except AppError:
        raise
    except Exception:
        raise AppError(
            status_code=500,
            code="EXTRACTION_FAILED",
            message="Extraction failed.",
        )

    # ── Build summary ───────────────────────────────────────────────
    element_counts: dict[str, int] = {}
    total_elements = 0
    total_sections = 0
    
    # Helper to count sections and elements recursively
    def _traverse(node):
        nonlocal total_elements, total_sections
        
        if node.node_type == "section":
            total_sections += 1
            if hasattr(node, "heading") and node.heading:
                key = "heading"
                element_counts[key] = element_counts.get(key, 0) + 1
                total_elements += 1
                
        # Count node if it is not just a container (like document/section)
        if node.node_type not in ["document", "section", "heading"]:
            element_counts[node.node_type] = element_counts.get(node.node_type, 0) + 1
            total_elements += 1
            
        if hasattr(node, "children"):
            for child in getattr(node, "children", []):
                _traverse(child)
                
    _traverse(document_node)

    return ExtractResponse(
        document_id=request.document_id,
        status="completed",
        title=document_node.doc_metadata.title or upload_path.stem,
        file_type=document_node.doc_metadata.file_type,
        page_count=document_node.doc_metadata.page_count or len(raw_document.pages),
        total_elements=total_elements,
        element_summary=element_counts,
        message=f"Extraction completed successfully. Built {total_sections} structural sections.",
    )
