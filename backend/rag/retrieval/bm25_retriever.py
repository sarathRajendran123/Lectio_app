"""
LECTIO — BM25 Sparse Retriever

BM25 complements dense retrieval in two important ways:
  1. Exact keyword matches (course codes, CLO verbs, technical terms)
     that are rare in the corpus score very high in BM25 but may be
     missed by semantic search (BGE has never seen "CS301" as meaningful).
  2. BM25 is fast and runs entirely in memory — no GPU/network needed.

Index lifecycle:
  - Built lazily when first query arrives for a course
  - Rebuilt after any ingestion (artifact added or deleted)
  - Stored as a dict[course_id → BM25Okapi] in process memory

For production (multi-worker), move index to Redis or a shared store.
For the prototype, one worker suffices.
"""

import logging
import re
from typing import Dict, List

from rag.chunking.chunk_models import RetrievedChunk

logger = logging.getLogger(__name__)


def _tokenise(text: str) -> List[str]:
    """
    Simple whitespace + punctuation tokeniser.
    Lowercases and strips punctuation — consistent with BM25 expectations.
    """
    text = text.lower()
    tokens = re.findall(r"\b[a-z0-9]+\b", text)
    return tokens


class BM25Index:
    """
    Wraps rank-bm25's BM25Okapi with our RetrievedChunk interface.
    One index per course.
    """

    def __init__(self, chunks: List[dict]):
        """
        Args:
            chunks: list of dicts with keys: chunk_id, text, metadata
        """
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("rank-bm25 not installed. Run: pip install rank-bm25")

        self._chunks   = chunks
        corpus         = [_tokenise(c["text"]) for c in chunks]
        self._bm25     = BM25Okapi(corpus)
        logger.debug(f"BM25 index built: {len(chunks)} documents")

    def search(self, query: str, top_k: int = 20) -> List[RetrievedChunk]:
        if not self._chunks:
            return []

        tokens  = _tokenise(query)
        scores  = self._bm25.get_scores(tokens)

        # Get top-k indices
        import numpy as np
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        max_score = float(scores[top_indices[0]]) if len(top_indices) > 0 else 1.0

        for idx in top_indices:
            raw_score = float(scores[idx])
            if raw_score <= 0:
                continue
            norm_score = raw_score / max_score if max_score > 0 else 0.0

            c    = self._chunks[idx]
            meta = c.get("metadata", {})

            results.append(RetrievedChunk(
                chunk_id=c["chunk_id"],
                text=c["text"],
                score=norm_score,
                artifact_id=meta.get("artifact_id", ""),
                artifact_type=meta.get("artifact_type", ""),
                course_id=meta.get("course_id", ""),
                page_number=meta.get("page_number") if meta.get("page_number", -1) > 0 else None,
                slide_number=meta.get("slide_number") if meta.get("slide_number", -1) > 0 else None,
                section_title=meta.get("section_title") or None,
                week_number=meta.get("week_number") if meta.get("week_number", -1) > 0 else None,
                metadata=meta,
            ))

        return results


class BM25Retriever:
    """
    Manages BM25 indices for all courses.
    Index is rebuilt when invalidated (new artifact ingested).
    """

    def __init__(self):
        self._indices:    Dict[str, BM25Index] = {}
        self._invalidated: set                  = set()

    def build_index(self, course_id: str, chunks: List[dict]) -> None:
        """
        (Re)build BM25 index for a course.
        chunks: list of {"chunk_id": str, "text": str, "metadata": dict}
        """
        self._indices[course_id]   = BM25Index(chunks)
        self._invalidated.discard(course_id)
        logger.info(f"BM25 index built for course {course_id}: {len(chunks)} docs")

    def invalidate(self, course_id: str) -> None:
        """Mark index as stale — will be rebuilt on next query."""
        self._invalidated.add(course_id)
        if course_id in self._indices:
            del self._indices[course_id]

    def search(
        self,
        course_id: str,
        query: str,
        top_k: int = 20,
        chunks_loader=None,    # callable() → List[dict], used for lazy rebuild
    ) -> List[RetrievedChunk]:
        """
        Search BM25 index.
        If index is missing or stale and chunks_loader is provided, rebuilds first.
        """
        if course_id not in self._indices or course_id in self._invalidated:
            if chunks_loader:
                chunks = chunks_loader()
                if chunks:
                    self.build_index(course_id, chunks)
                else:
                    logger.debug(f"No chunks to build BM25 index for course {course_id}")
                    return []
            else:
                logger.debug(f"No BM25 index for course {course_id} and no loader provided")
                return []

        return self._indices[course_id].search(query, top_k=top_k)

    def is_indexed(self, course_id: str) -> bool:
        return course_id in self._indices and course_id not in self._invalidated


# ── Module-level singleton ─────────────────────────────────────────────────────
bm25_retriever = BM25Retriever()
