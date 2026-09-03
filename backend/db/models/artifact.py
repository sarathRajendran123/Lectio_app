"""
LECTIO — Artifact & Chunk ORM Models
CourseArtifact: uploaded files (PDF, DOCX, PPTX, etc.)
Chunk: text segments extracted during RAG ingestion
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Integer,
    Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


VALID_FILE_TYPES     = {"pdf", "docx", "pptx", "txt", "vtt"}
VALID_ARTIFACT_TYPES = {
    "syllabus", "slides", "assignment",
    "transcript", "module_manual", "other",
}
VALID_STATUSES = {"pending", "parsing", "chunking", "embedding", "storing", "done", "error"}


class CourseArtifact(Base):
    __tablename__ = "course_artifacts"

    id:                Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id:         Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    uploaded_by:       Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    filename:          Mapped[str]                 = mapped_column(String(500), nullable=False)   # sanitised name on disk
    original_filename: Mapped[Optional[str]]       = mapped_column(String(500))                   # user's original name
    file_type:         Mapped[str]                 = mapped_column(String(50), nullable=False)    # pdf|docx|pptx|txt|vtt
    artifact_type:     Mapped[Optional[str]]       = mapped_column(String(100))                   # syllabus|slides|…
    file_size_bytes:   Mapped[Optional[int]]       = mapped_column(BigInteger)
    storage_path:      Mapped[Optional[str]]       = mapped_column(String(1000))
    processing_status: Mapped[str]                 = mapped_column(String(50), nullable=False, default="pending")
    processing_error:  Mapped[Optional[str]]       = mapped_column(Text)
    page_count:        Mapped[Optional[int]]       = mapped_column(Integer)
    slide_count:       Mapped[Optional[int]]       = mapped_column(Integer)
    word_count:        Mapped[Optional[int]]       = mapped_column(Integer)
    checksum:          Mapped[Optional[str]]       = mapped_column(String(64))    # SHA-256 of file bytes
    uploaded_at:       Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at:      Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))
    metadata_:         Mapped[dict]                = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    course:  Mapped["Course"]        = relationship(back_populates="artifacts")   # type: ignore[name-defined]
    chunks:  Mapped[List["Chunk"]]   = relationship(back_populates="artifact", cascade="all, delete-orphan")


class Chunk(Base):
    """
    A text segment extracted from a CourseArtifact.
    Populated by the RAG ingestion pipeline (Phase 2).
    """
    __tablename__ = "chunks"

    id:                Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id:       Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("course_artifacts.id", ondelete="CASCADE"), nullable=False)
    course_id:         Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    text:              Mapped[str]                 = mapped_column(Text, nullable=False)
    token_count:       Mapped[Optional[int]]       = mapped_column(Integer)
    char_count:        Mapped[Optional[int]]       = mapped_column(Integer)
    chunk_index:       Mapped[Optional[int]]       = mapped_column(Integer)
    page_number:       Mapped[Optional[int]]       = mapped_column(Integer)
    slide_number:      Mapped[Optional[int]]       = mapped_column(Integer)
    section_title:     Mapped[Optional[str]]       = mapped_column(String(500))
    week_number:       Mapped[Optional[int]]       = mapped_column(Integer)
    document_position: Mapped[Optional[float]]     = mapped_column(Numeric(5, 4))
    chroma_id:         Mapped[Optional[str]]       = mapped_column(String(255))   # ID in ChromaDB
    embedding_model:   Mapped[Optional[str]]       = mapped_column(String(100))
    embedded_at:       Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))
    created_at:        Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_:         Mapped[dict]                = mapped_column("metadata", JSONB, nullable=False, default=dict)

    artifact: Mapped["CourseArtifact"] = relationship(back_populates="chunks")


# Resolve forward reference in course.py
