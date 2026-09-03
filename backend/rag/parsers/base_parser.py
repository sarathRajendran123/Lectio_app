"""
LECTIO — Base Parser Interface & ParsedDocument Model
Every parser (PDF, DOCX, PPTX, TXT) returns a ParsedDocument.
This normalises heterogeneous formats into one structure the chunker consumes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ParsedBlock:
    """
    A single logical block of text from a document.
    May be a paragraph, slide body, heading, table row, speaker note, etc.
    """
    text:           str
    block_type:     str                 # paragraph|heading|table|caption|note|title
    page_number:    Optional[int] = None
    slide_number:   Optional[int] = None
    section_title:  Optional[str] = None
    heading_level:  Optional[int] = None   # 1–6 for headings
    is_bold:        bool = False
    is_table:       bool = False
    metadata:       dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """
    Normalised output from any parser.
    Downstream: SemanticChunker consumes this.
    """
    source_path:     str
    file_type:       str                # pdf|docx|pptx|txt|vtt
    artifact_type:   str                # syllabus|slides|assignment|…
    blocks:          List[ParsedBlock]
    total_pages:     Optional[int] = None
    total_slides:    Optional[int] = None
    title:           Optional[str] = None
    author:          Optional[str] = None
    word_count:      int = 0
    parse_warnings:  List[str] = field(default_factory=list)

    def all_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text.strip())


class BaseParser(ABC):
    """
    Abstract base for all document parsers.
    Subclasses implement parse() and return a ParsedDocument.
    """

    @abstractmethod
    def parse(self, file_path: str, artifact_type: str = "other") -> ParsedDocument:
        """Parse a file and return a normalised ParsedDocument."""
        ...

    def _count_words(self, text: str) -> int:
        return len(text.split())

    def _safe_text(self, raw: str) -> str:
        """Strip null bytes and normalise whitespace."""
        if not raw:
            return ""
        text = raw.replace("\x00", "")
        # Collapse excessive blank lines (>2 consecutive)
        import re
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
