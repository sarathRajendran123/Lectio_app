"""
LECTIO — Hybrid Retriever
Combines dense (ChromaDB) + sparse (BM25) results using
Reciprocal Rank Fusion (RRF).

Why RRF over weighted score combination?
  - Dense and BM25 scores live in different spaces (cosine similarity 0–1
    vs BM25 normalised 0–1) — direct addition is misleading.
  - RRF uses rank positions, which are scale-invariant.
  - RRF(k=60) consistently outperforms individual retrievers on BEIR.
  - No hyperparameter tuning needed per corpus.

RRF formula:
    score(d) = Σ  1 / (k + rank_i(d))
               i

where rank_i(d) is the rank of document d in retrieval system i (1-indexed),
and k=60 is a smoothing constant that reduces the impact of very high ranks.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from rag.chunking.chunk_models import RetrievedChunk
from rag.embedding.bge_embedder import BGEEmbedder
from rag.retrieval.bm25_retriever import BM25Retriever
from vector_db.chroma_client import ChromaCollectionManager

logger = logging.getLogger(__name__)

RRF_K = 60    # RRF smoothing constant (standard value from literature)


class HybridRetriever:
    """
    Retrieves relevant chunks using dense + BM25 and merges via RRF.

    Args:
        embedder:   BGEEmbedder instance
        chroma:     ChromaCollectionManager instance
        bm25:       BM25Retriever instance
        dense_top_k: candidates from dense retrieval
        bm25_top_k:  candidates from BM25 retrieval
        final_top_k: result set size after fusion
    """

    def __init__(
        self,
        embedder:    BGEEmbedder,
        chroma:      ChromaCollectionManager,
        bm25:        BM25Retriever,
        dense_top_k: int = 20,
        bm25_top_k:  int = 20,
        final_top_k: int = 40,
    ):
        self.embedder    = embedder
        self.chroma      = chroma
        self.bm25        = bm25
        self.dense_top_k = dense_top_k
        self.bm25_top_k  = bm25_top_k
        self.final_top_k = final_top_k

    def retrieve(
        self,
        query: str,
        course_id: str,
        top_k: Optional[int] = None,
        where: Optional[dict] = None,          # ChromaDB metadata filter
        bm25_chunks_loader=None,               # callable for lazy BM25 rebuild
    ) -> List[RetrievedChunk]:
        """
        Run hybrid retrieval for a query against a course's documents.

        Args:
            query:       natural language query
            course_id:   target course UUID (str)
            top_k:       override final result count
            where:       optional ChromaDB metadata filter
                         e.g. {"artifact_type": "slides", "week_number": 3}
            bm25_chunks_loader: callable() → List[dict] for lazy BM25 index build

        Returns:
            List[RetrievedChunk] ordered by RRF score (descending)
        """
        final_k = top_k or self.final_top_k

        # ── Dense retrieval ────────────────────────────────────────────────────
        query_vec     = self.embedder.embed_query(query)
        dense_results = self.chroma.query(
            course_id=course_id,
            query_embedding=query_vec,
            top_k=self.dense_top_k,
            where=where,
        )
        logger.debug(f"Dense: {len(dense_results)} candidates")

        # ── Sparse retrieval (BM25) ────────────────────────────────────────────
        bm25_results = self.bm25.search(
            course_id=course_id,
            query=query,
            top_k=self.bm25_top_k,
            chunks_loader=bm25_chunks_loader,
        )
        logger.debug(f"BM25:  {len(bm25_results)} candidates")

        # ── Reciprocal Rank Fusion ─────────────────────────────────────────────
        fused = self._rrf(dense_results, bm25_results, k=RRF_K)

        # Build a lookup for full chunk data (dense results carry metadata)
        chunk_map: Dict[str, RetrievedChunk] = {}
        for r in dense_results + bm25_results:
            if r.chunk_id not in chunk_map:
                chunk_map[r.chunk_id] = r

        # Assemble final results with fused scores
        fused_results: List[RetrievedChunk] = []
        for chunk_id, rrf_score in sorted(fused.items(), key=lambda x: x[1], reverse=True)[:final_k]:
            if chunk_id in chunk_map:
                r = chunk_map[chunk_id]
                fused_results.append(RetrievedChunk(
                    chunk_id=r.chunk_id,
                    text=r.text,
                    score=rrf_score,
                    artifact_id=r.artifact_id,
                    artifact_type=r.artifact_type,
                    course_id=r.course_id,
                    page_number=r.page_number,
                    slide_number=r.slide_number,
                    section_title=r.section_title,
                    week_number=r.week_number,
                    metadata=r.metadata,
                ))

        logger.info(
            f"Hybrid retrieve: query='{query[:60]}...' | "
            f"dense={len(dense_results)} bm25={len(bm25_results)} "
            f"fused={len(fused_results)}"
        )
        return fused_results

    # ── RRF Implementation ────────────────────────────────────────────────────

    @staticmethod
    def _rrf(
        *ranked_lists: List[RetrievedChunk],
        k: int = RRF_K,
    ) -> Dict[str, float]:
        """
        Reciprocal Rank Fusion across multiple ranked lists.
        Returns dict[chunk_id → rrf_score].
        """
        scores: Dict[str, float] = defaultdict(float)
        for ranked in ranked_lists:
            for rank, result in enumerate(ranked, start=1):
                scores[result.chunk_id] += 1.0 / (k + rank)
        return dict(scores)
