"""
LECTIO — BGE Embedder (BAAI/bge-large-en-v1.5)

Why BGE over OpenAI embeddings?
  - Runs 100% locally — zero API cost, zero data leaving your server
  - BEIR benchmark: comparable to text-embedding-ada-002, better than ada on
    several retrieval tasks
  - BGE requires an instruction prefix for retrieval tasks:
      "Represent this sentence for retrieval: {text}"
    This prefix is added automatically here.
  - 1024-dimensional vectors with cosine similarity

Batching:
  Embedding is CPU-bound and the most expensive step in ingestion.
  We process in batches of 32 and log throughput.
"""

import logging
import time
from typing import List

from rag.chunking.chunk_models import EmbeddedChunk, RawChunk

logger = logging.getLogger(__name__)

BGE_MODEL_NAME   = "BAAI/bge-large-en-v1.5"
BGE_PREFIX       = "Represent this sentence for retrieval: "
DEFAULT_BATCH    = 32


class BGEEmbedder:
    """
    Singleton-style embedder: model is loaded once and reused.
    Call embed_chunks() to get EmbeddedChunks.
    """

    _instance = None

    def __init__(self, model_name: str = BGE_MODEL_NAME, device: str = "cpu"):
        self.model_name = model_name
        self.device     = device
        self._model     = None   # lazy load

    @classmethod
    def get_instance(cls, device: str = "cpu") -> "BGEEmbedder":
        """Return singleton instance (model loaded once per process)."""
        if cls._instance is None:
            cls._instance = cls(device=device)
        return cls._instance

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name} on {self.device}")
            t0           = time.time()
            self._model  = SentenceTransformer(self.model_name, device=self.device)
            logger.info(f"Model loaded in {time.time() - t0:.1f}s")
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def embed_chunks(
        self,
        chunks: List[RawChunk],
        batch_size: int = DEFAULT_BATCH,
    ) -> List[EmbeddedChunk]:
        """
        Embed a list of RawChunks.
        Returns EmbeddedChunks in the same order.
        """
        if not chunks:
            return []

        self._load()

        # BGE instruction prefix boosts retrieval performance
        texts = [f"{BGE_PREFIX}{c.text}" for c in chunks]

        t0 = time.time()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,   # cosine similarity works correctly
            show_progress_bar=False,
        )
        elapsed = time.time() - t0
        logger.info(
            f"Embedded {len(chunks)} chunks in {elapsed:.2f}s "
            f"({len(chunks)/elapsed:.1f} chunks/s)"
        )

        return [
            EmbeddedChunk(chunk=chunk, embedding=emb.tolist())
            for chunk, emb in zip(chunks, embeddings)
        ]

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single retrieval query.
        Uses the same BGE prefix for consistent similarity space.
        """
        self._load()
        vec = self._model.encode(
            f"{BGE_PREFIX}{query}",
            normalize_embeddings=True,
        )
        return vec.tolist()

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        self._load()
        return self._model.get_sentence_embedding_dimension()
