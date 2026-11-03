"""
LECTIO — Cross-Encoder Reranker

The retrieval stage (bi-encoder) optimises for speed by comparing
pre-computed embeddings. The reranker uses a cross-encoder that sees
query + document together — much slower but significantly more accurate.

Model: cross-encoder/ms-marco-MiniLM-L-12-v2
  - Trained on MS MARCO passage ranking
  - 33M parameters — fast enough for CPU inference on 40 candidates
  - Outputs a raw logit score (higher = more relevant)

When to rerank:
  - Always: for agent alignment queries (accuracy critical)
  - Skip:   for real-time autocomplete/search (latency critical)

Threshold filtering:
  Chunks scoring below MIN_RERANK_SCORE are dropped.
  This prevents low-quality chunks padding the context window.
"""

import logging
import math
from typing import List, Optional

from rag.chunking.chunk_models import RetrievedChunk

logger        = logging.getLogger(__name__)
RERANK_MODEL  = "cross-encoder/ms-marco-MiniLM-L-12-v2"
MIN_SCORE     = -5.0   # raw logit threshold (very permissive; tune upwards if noise)


class CrossEncoderReranker:
    """
    Reranks a list of RetrievedChunks using a cross-encoder model.
    Lazy-loads the model on first use.
    """

    _instance: Optional["CrossEncoderReranker"] = None

    def __init__(self, model_name: str = RERANK_MODEL):
        self.model_name = model_name
        self._model     = None

    @classmethod
    def get_instance(cls) -> "CrossEncoderReranker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading cross-encoder: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
            logger.info("Cross-encoder loaded.")
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )

    def rerank(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        top_k: int = 10,
        min_score: float = MIN_SCORE,
    ) -> List[RetrievedChunk]:
        """
        Rerank candidates and return top_k above min_score.

        Args:
            query:     the retrieval query
            chunks:    candidates from hybrid retrieval
            top_k:     max results to return
            min_score: raw logit minimum threshold

        Returns:
            Reranked list (best first), filtered by min_score.
        """
        if not chunks:
            return []

        self._load()

        pairs  = [(query, c.text) for c in chunks]
        scores = self._model.predict(pairs)

        scored = sorted(
            zip(chunks, scores.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )

        results = []
        for chunk, raw_score in scored[:top_k]:
            if raw_score < min_score:
                continue
            # Cross-encoder output is a raw, UNBOUNDED logit (can be negative,
            # can be 8+, etc) — not a 0-1 similarity fraction. Every alignment
            # agent downstream treats chunk.score as a 0-1 fraction (feeds it
            # directly into percentage displays and compares it against
            # thresholds like 0.5 / 0.6 / 0.75), so we normalize it here with
            # a sigmoid before it ever leaves this module. Without this, a
            # strong match (e.g. raw logit 4.24) was being displayed as
            # "424%" and used as-is in weighted score formulas elsewhere.
            normalized_score = 1.0 / (1.0 + math.exp(-raw_score))
            # Replace bi-encoder score with cross-encoder score
            results.append(RetrievedChunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                score=normalized_score,
                artifact_id=chunk.artifact_id,
                artifact_type=chunk.artifact_type,
                course_id=chunk.course_id,
                page_number=chunk.page_number,
                slide_number=chunk.slide_number,
                section_title=chunk.section_title,
                week_number=chunk.week_number,
                metadata=chunk.metadata,
            ))

        logger.debug(
            f"Reranker: {len(chunks)} -> {len(results)} chunks "
            f"(top normalized score: {results[0].score:.3f})" if results else
            f"Reranker: {len(chunks)} -> 0 chunks"
        )
        return results
