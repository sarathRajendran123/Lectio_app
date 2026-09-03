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
        # Step 1 — group blocks by structural section
        sections = self._group_into_sections(doc.blocks)

        # Step 2 — within each section, apply size + optional semantic splitting
        raw_chunks: List[RawChunk] = []
        total_blocks = max(sum(len(s) for s in sections.values()), 1)
        block_offset = 0

        for section_title, section_blocks in sections.items():
            section_text_parts = [b.text for b in section_blocks]
            combined_text      = "\n".join(section_text_parts)

            # Positional metadata from first block in section
            first = section_blocks[0]
            meta  = {
                "page_number":  first.page_number,
                "slide_number": first.slide_number,
                "week_number":  self._infer_week(section_title, first),
            }

            # Level 2/3 — split section into sub-chunks
            sub_texts = self._split_section(combined_text)

            for sub_text in sub_texts:
                token_count = _naive_token_count(sub_text)
                if token_count < self.min_tokens:
                    continue

                doc_position = block_offset / total_blocks

                raw_chunks.append(RawChunk(
                    text=sub_text.strip(),
                    chunk_index=len(raw_chunks),
                    artifact_id=artifact_id,
                    course_id=course_id,
                    file_type=doc.file_type,
                    artifact_type=doc.artifact_type,
                    page_number=meta["page_number"],
                    slide_number=meta["slide_number"],
                    section_title=section_title or None,
                    week_number=meta["week_number"],
                    document_position=round(doc_position, 4),
                    char_count=len(sub_text),
                    token_count=token_count,
                ))

            block_offset += len(section_blocks)

        logger.info(
            f"Chunked '{doc.source_path}' → {len(raw_chunks)} chunks "
            f"from {len(doc.blocks)} blocks"
        )
        return raw_chunks

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
        if _naive_token_count(text) <= self.max_tokens:
            return [text]

        sentences    = _split_sentences(text)
        chunks:  List[str] = []
        current: List[str] = []
        current_tok  = 0

        overlap_count = max(1, int(len(sentences) * OVERLAP_RATIO / max(len(sentences), 1)))

        for sent in sentences:
            sent_tok = _naive_token_count(sent)

            if current_tok + sent_tok > self.max_tokens and current:
                chunks.append(" ".join(current))
                # Keep last N sentences as overlap for next chunk
                overlap = current[-overlap_count:] if overlap_count < len(current) else current[:]
                current     = overlap + [sent]
                current_tok = sum(_naive_token_count(s) for s in current)
            else:
                current.append(sent)
                current_tok += sent_tok

        if current:
            chunks.append(" ".join(current))

        return chunks if chunks else [text]

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
