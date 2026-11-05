"""
LECTIO — Chunk Models
The canonical data structures flowing through the RAG pipeline:
  ParsedDocument → [SemanticChunker] → List[RawChunk]
                → [Embedder]         → List[EmbeddedChunk]
                → [ChromaDB]         → stored
"""

from dataclasses import dataclass, field
from typing import List, Optional
import uuid


@dataclass
class RawChunk:
    """
    A text segment produced by the SemanticChunker.
    Not yet embedded — no vector attached.
    """
    text:             str
    chunk_index:      int
    artifact_id:      str
    course_id:        str
    file_type:        str
    artifact_type:    str
    # Positional metadata
    page_number:      Optional[int]   = None
    slide_number:     Optional[int]   = None
    section_title:    Optional[str]   = None
    week_number:      Optional[int]   = None
    document_position: float          = 0.0   # 0.0 → 1.0 position in document
    # Text stats
    char_count:       int             = 0
    token_count:      int             = 0
    # Internal ID (stable across pipeline)
    chunk_id:         str             = field(default_factory=lambda: str(uuid.uuid4()))
    # Extra
    extra_metadata:   dict            = field(default_factory=dict)

    def to_chroma_metadata(self) -> dict:
        """Flat dict for ChromaDB metadata storage (no nested objects)."""
        return {
            "chunk_id":         self.chunk_id,
            "artifact_id":      self.artifact_id,
            "course_id":        self.course_id,
            "file_type":        self.file_type,
            "artifact_type":    self.artifact_type,
            "page_number":      self.page_number      or -1,
            "slide_number":     self.slide_number     or -1,
            "section_title":    self.section_title    or "",
            "week_number":      self.week_number      or -1,
            "document_position": self.document_position,
            "char_count":       self.char_count,
            "token_count":      self.token_count,
            "chunk_index":      self.chunk_index,
        }


@dataclass
class EmbeddedChunk:
    """A RawChunk that has been embedded — has a vector attached."""
    chunk:     RawChunk
    embedding: List[float]

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def text(self) -> str:
        return self.chunk.text


@dataclass
class RetrievedChunk:
    """A chunk returned from retrieval, with a relevance score."""
    chunk_id:      str
    text:          str
    score:         float
    artifact_id:   str
    artifact_type: str
    course_id:     str
    page_number:   Optional[int]
    slide_number:  Optional[int]
    section_title: Optional[str]
    week_number:   Optional[int]
    metadata:      dict = field(default_factory=dict)

    def to_citation(self) -> str:
        """Human-readable citation string."""
        parts = [f"[{self.artifact_type.replace('_', ' ').title()}"]
        if self.section_title:
            parts.append(f", {self.section_title}")
        if self.page_number and self.page_number > 0:
            parts.append(f", p.{self.page_number}")
        if self.slide_number and self.slide_number > 0:
            parts.append(f", slide {self.slide_number}")
        if self.week_number and self.week_number > 0:
            parts.append(f", week {self.week_number}")
        parts.append("]")
        return "".join(parts)
