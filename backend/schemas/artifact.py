"""
LECTIO — Artifact Pydantic Schemas
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

VALID_ARTIFACT_TYPES = [
    "syllabus", "slides", "assignment",
    "transcript", "module_manual", "other",
]


class ArtifactResponse(BaseModel):
    id:                UUID
    course_id:         UUID
    uploaded_by:       Optional[UUID]
    filename:          str
    original_filename: Optional[str]
    file_type:         str
    artifact_type:     Optional[str]
    file_size_bytes:   Optional[int]
    processing_status: str
    processing_error:  Optional[str]
    page_count:        Optional[int]
    slide_count:       Optional[int]
    word_count:        Optional[int]
    uploaded_at:       datetime
    processed_at:      Optional[datetime]
    chunk_count:       int = 0

    class Config:
        from_attributes = True


class ArtifactListResponse(BaseModel):
    total:     int
    artifacts: list[ArtifactResponse]


class ArtifactStatusResponse(BaseModel):
    id:                UUID
    processing_status: str
    processing_error:  Optional[str]
    chunk_count:       int
