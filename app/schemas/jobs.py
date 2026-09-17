"""Pydantic schemas for background jobs and progress tracking."""

from enum import Enum
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentJob(BaseModel):
    """Tracks the progress of a single document in a batch job."""
    document_id: str
    filename: str
    status: JobStatus = JobStatus.QUEUED
    progress_percentage: int = 0
    message: str = "Queued for processing"
    result: Optional[dict[str, Any]] = None  # Could hold DocumentExtractionOutput
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class BatchJob(BaseModel):
    """Tracks a complete batch upload job."""
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    documents: list[DocumentJob] = Field(default_factory=list)
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    correlation_id: Optional[str] = None
    
    @property
    def total_documents(self) -> int:
        return len(self.documents)
        
    @property
    def completed_documents(self) -> int:
        return sum(1 for d in self.documents if d.status == JobStatus.COMPLETED)
        
    @property
    def failed_documents(self) -> int:
        return sum(1 for d in self.documents if d.status == JobStatus.FAILED)
        
    @property
    def progress_percentage(self) -> int:
        if not self.documents:
            return 100
        total_progress = sum(d.progress_percentage for d in self.documents)
        return int(total_progress / len(self.documents))
