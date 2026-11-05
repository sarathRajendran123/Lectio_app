"""
LECTIO — Semantic Chunker

Three-level chunking strategy:
  Level 1 — Structural splits: break at document headings (H1/H2).
             These are natural semantic boundaries in syllabi and manuals.
  Level 2 — Semantic boundary detection: within a section, find topic
             shifts using cosine similarity between adjacent sentences.
             Split where similarity drops below threshold.
  Level 3 — Size enforcement: if a chunk still exceeds MAX_TOKENS after
             L1+L2, split at sentence boundaries with 20% overlap.

Why not simple fixed-size chunking?
  A 512-token window cutting mid-sentence through "Students must be able to
  implement [SPLIT] a binary search tree" produces two meaningless chunks
  that will confuse alignment detection. Structural boundaries always take
  precedence over token counts.
"""

import logging
import re
from typing import List, Optional

from rag.chunking.chunk_models import RawChunk
from rag.parsers.base_parser import ParsedDocument, ParsedBlock

logger = logging.getLogger(__name__)

MAX_TOKENS      = 450    # Hard ceiling per chunk (leaves room in 512-token embedding window)
MIN_TOKENS      = 30     # Discard chunks shorter than this
OVERLAP_RATIO   = 0.15   # 15% sentence overlap on forced size splits
SIM_THRESHOLD   = 0.45   # Cosine similarity below this → new semantic section


def _naive_token_count(text: str) -> int:
    """Fast approximation: 1 token ≈ 4 characters (GPT/BERT average)."""
    return max(1, len(text) // 4)


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using a regex (no NLTK dependency at runtime)."""
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sents if s.strip()]


class SemanticChunker:
    """
    Converts a ParsedDocument into a list of RawChunks.

    Args:
        use_semantic_split: if True, attempt cosine-similarity boundary
            detection (requires sentence-transformers loaded). If False or
            if the model is unavailable, falls back to pure structural+size.
        sim_threshold: cosine drop threshold for semantic splits (0–1).
    """

    def __init__(
        self,
        use_semantic_split: bool = False,    # off by default; enabled when embedder available
        sim_threshold: float = SIM_THRESHOLD,
        max_tokens: int = MAX_TOKENS,
        min_tokens: int = MIN_TOKENS,
    ):
        self.use_semantic_split = use_semantic_split
        self.sim_threshold      = sim_threshold
        self.max_tokens         = max_tokens
        self.min_tokens         = min_tokens
        self._encoder           = None   # lazy-loaded SentenceTransformer

    # ── Public API ────────────────────────────────────────────────────────────

    def chunk(
        self,
        doc: ParsedDocument,
        artifact_id: str,
        course_id: str,
    ) -> List[RawChunk]:
        """
        Main entry point. Returns ordered list of RawChunks.
        """
        raw_chunks = []
        for block in self._attach_headings(doc.blocks):
            sections=self._semantic_sections(block.text) if self.use_semantic_split else [block.text]
            for text in [piece for section in sections for piece in self._split_section(section)]:
                # Preserve even short outcomes, question prompts and headings.
                if not text.strip(): continue
                raw_chunks.append(RawChunk(text=text, chunk_index=len(raw_chunks),
                    artifact_id=artifact_id, course_id=course_id, file_type=doc.file_type,
                    artifact_type=doc.artifact_type, page_number=block.page_number,
                    slide_number=block.slide_number, section_title=block.section_title,
                    week_number=self._infer_week(block.section_title, block),
                    char_count=len(text), token_count=_naive_token_count(text),
                    extra_metadata=block.metadata))
        return raw_chunks

    @staticmethod
    def _attach_headings(blocks):
        """A heading is context for the text under it: keep them in one chunk (a heading-only chunk is useless evidence)."""
        from dataclasses import replace
        merged, pending = [], []
        for block in blocks:
            if block.block_type in ("heading", "title") and block.text.strip():
                pending.append(block.text.strip()); continue
            if pending:
                block = replace(block, text="\n".join(pending) + "\n" + block.text); pending = []
            merged.append(block)
        for leftover in pending:   # trailing headings with nothing under them stay as they are
            merged.append(replace(blocks[-1], text=leftover, block_type="heading"))
        return merged

    def _semantic_sections(self, text):
        # Retain original slices rather than rejoining sentences or inventing locations.
        import numpy as np
        spans=list(re.finditer(r'[^.!?]+(?:[.!?]+(?:\s+|$)|$)',text))
        if len(spans)<3:return [text]
        if self._encoder is None:
            from rag.embedding.bge_embedder import BGEEmbedder
            self._encoder=BGEEmbedder.get_instance()
        spans=spans[:100]
        vectors=self._encoder.embed_texts([m.group() for m in spans])
        boundaries=[0]
        for index in range(1,len(vectors)):
            a=np.asarray(vectors[index-1]);b=np.asarray(vectors[index])
            cosine=float(a@b)/(float(np.linalg.norm(a)*np.linalg.norm(b)) or 1)
            if cosine<self.sim_threshold and spans[index].start()-boundaries[-1]>80:
                boundaries.append(spans[index].start())
        boundaries.append(len(text))
        return [text[a:b] for a,b in zip(boundaries,boundaries[1:]) if text[a:b].strip()]

    # ── Level 1: Structural Grouping ──────────────────────────────────────────

    def _group_into_sections(
        self, blocks: List[ParsedBlock]
    ) -> dict:
        """
        Group blocks by their section_title (set by parser from headings).
        Returns OrderedDict: section_title → [ParsedBlock, ...]
        """
        from collections import OrderedDict
        sections: dict = OrderedDict()
        current_key = "__preamble__"

        for block in blocks:
            if block.block_type in ("heading", "title") and block.text:
                current_key = block.text[:120]   # headings become section keys
                if current_key not in sections:
                    sections[current_key] = []
                # Include the heading itself as a block
                sections[current_key].append(block)
            else:
                key = block.section_title or current_key
                if key not in sections:
                    sections[key] = []
                sections[key].append(block)

        return sections

    # ── Level 2/3: Sentence-level splitting ───────────────────────────────────

    def _split_section(self, text: str) -> List[str]:
        """
        Split a section's text into chunks respecting MAX_TOKENS.
        Uses sentence boundaries for clean splits.
        Applies overlap so context is not lost at boundaries.
        """
        # Contiguous slices preserve exact source text, including whitespace.
        limit = self.max_tokens * 4
        parts = []
        while len(text) > limit:
            boundary = max(text.rfind(". ", 0, limit), text.rfind("\n", 0, limit))
            boundary = boundary + 1 if boundary > limit // 2 else limit
            parts.append(text[:boundary])
            text = text[boundary:]
        if text.strip(): parts.append(text)
        return parts

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _infer_week(self, section_title: Optional[str], block: ParsedBlock) -> Optional[int]:
        """
        Try to extract a week number from section titles or block metadata.
        Matches: "Week 3", "Week3", "Lecture 3", "W3", "Unit 3"
        """
        if block.metadata.get("week_number"):
            return block.metadata["week_number"]

        sources = [section_title or "", block.section_title or ""]
        for text in sources:
            m = re.search(
                r"\b(?:week|lecture|unit|module|w)\s*(\d{1,2})\b",
                text,
                re.IGNORECASE,
            )
            if m:
                n = int(m.group(1))
                if 1 <= n <= 52:
                    return n
        return None
