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
        for chunk, score in scored[:top_k]:
            if score < min_score:
                continue
            # Replace bi-encoder score with cross-encoder score
            results.append(RetrievedChunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                score=float(score),
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
            f"Reranker: {len(chunks)} → {len(results)} chunks "
            f"(top score: {scored[0][1]:.3f} if scored else 'N/A')"
        )
        return results
