"""
LECTIO — Local multilingual embedder (default: BAAI/bge-m3, German + English)

  - Runs locally: no API cost, no document text leaves the server.
  - BGE-M3 needs no instruction prefix; English-only BGE v1.5 models and E5
    models get their documented prefixes via _prefixes().
  - 1024-dimensional, L2-normalised vectors (cosine similarity).
  - Embedding is CPU-bound: texts are encoded in batches of 32.
"""

import hashlib
import logging
import os
import time
from typing import List

import numpy as np

from rag.chunking.chunk_models import EmbeddedChunk, RawChunk

logger = logging.getLogger(__name__)

BGE_MODEL_NAME   = "BAAI/bge-m3"
DEFAULT_BATCH    = 32


def _prefixes(model_name: str) -> tuple[str, str]:
    """(query_prefix, passage_prefix) documented for the model family."""
    name = model_name.lower()
    if "e5" in name:
        return "query: ", "passage: "
    if "bge" in name and "m3" not in name:
        return "Represent this sentence for retrieval: ", ""
    return "", ""


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
        self._query_cache: dict = {}

    @classmethod
    def get_instance(cls, device: str = "cpu") -> "BGEEmbedder":
        """Return singleton instance (model loaded once per process)."""
        if cls._instance is None:
            from config import settings
            cls._instance = cls(model_name=settings.embedding_model, device=device)
        return cls._instance

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name} on {self.device}")
            t0           = time.time()
            self._model  = SentenceTransformer(self.model_name, device=self.device, trust_remote_code=False)
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

        # Content-addressed cache: identical text under the same model is never re-embedded
        # (re-uploads, ingestion retries, unchanged slides after an edit).
        prefix = _prefixes(self.model_name)[1]
        paths  = [self._cache_path(prefix + c.text) for c in chunks]
        vecs   = [self._cache_load(p) for p in paths]
        todo   = [i for i, v in enumerate(vecs) if v is None]
        if todo:
            self._load()
            t0  = time.time()
            new = self._model.encode(
                [prefix + chunks[i].text for i in todo],
                batch_size=batch_size,
                normalize_embeddings=True,   # cosine similarity works correctly
                show_progress_bar=False,
            )
            for i, emb in zip(todo, new):
                vecs[i] = emb.tolist()
                self._cache_store(paths[i], emb)
            logger.info(f"Embedded {len(todo)}/{len(chunks)} chunks in {time.time() - t0:.2f}s (rest from cache)")

        return [EmbeddedChunk(chunk=chunk, embedding=v) for chunk, v in zip(chunks, vecs)]

    def _cache_path(self, text: str) -> str:
        from config import settings
        key  = hashlib.sha256((self.model_name + "|" + text).encode("utf-8")).hexdigest()
        slug = self.model_name.replace("/", "_")
        return os.path.join(settings.artifact_storage_path, ".embed_cache", slug, key + ".npy")

    @staticmethod
    def _cache_load(path: str):
        try:
            return np.load(path).tolist()
        except (OSError, ValueError):
            return None

    @staticmethod
    def _cache_store(path: str, vec) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp.npy"
            np.save(tmp, np.asarray(vec, dtype=np.float32))
            os.replace(tmp, path)
        except OSError:
            logger.warning("Embedding cache write failed; continuing without cache.")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Batch passage embeddings for topic boundaries and clustering."""
        if not texts: return []
        self._load()
        prefix = _prefixes(self.model_name)[1]
        return self._model.encode([prefix + t for t in texts], batch_size=32, normalize_embeddings=True,
            show_progress_bar=False, convert_to_numpy=True).tolist()

    def embed_query(self, query: str) -> List[float]:
        if query not in self._query_cache:
            if len(self._query_cache) >= 512:
                self._query_cache.pop(next(iter(self._query_cache)))
            self._query_cache[query] = self._embed_query(query)
        return self._query_cache[query]

    def _embed_query(self, query: str) -> List[float]:
        """
        Embed a single retrieval query.
        Applies the model family's query prefix, if any.
        """
        self._load()
        vec = self._model.encode(
            f"{_prefixes(self.model_name)[0]}{query}",
            normalize_embeddings=True,
        )
        return vec.tolist()

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        self._load()
        return self._model.get_sentence_embedding_dimension()
