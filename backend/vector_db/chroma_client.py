"""
LECTIO — ChromaDB Client & Collection Manager

One ChromaDB collection per course:  course_{course_id}
This gives us:
  - Per-course metadata filtering (artifact_type, week_number, slide_number)
  - Zero cross-course contamination in retrieval
  - Simple collection deletion when a course is removed

Collection naming: course_{uuid_hex_no_dashes}
"""

import logging
from typing import List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings
from rag.chunking.chunk_models import EmbeddedChunk, RetrievedChunk

logger = logging.getLogger(__name__)


def _collection_name(course_id: str) -> str:
    """Stable, ChromaDB-safe collection name for a course."""
    safe = course_id.replace("-", "")
    return f"course_{safe}"


class ChromaCollectionManager:
    """
    Manages ChromaDB collections for LECTIO courses.
    One instance per application (singleton via get_instance()).
    """

    _instance: Optional["ChromaCollectionManager"] = None

    def __init__(self):
        self._client: Optional[chromadb.HttpClient] = None

    @classmethod
    def get_instance(cls) -> "ChromaCollectionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Connection ────────────────────────────────────────────────────────────

    def _get_client(self) -> chromadb.HttpClient:
        if self._client is None:
            logger.info(f"Connecting to ChromaDB at {settings.chroma_url}")
            self._client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=ChromaSettings(
                    chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
                    chroma_client_auth_credentials=settings.chroma_auth_token,
                ),
            )
        return self._client

    # ── Collection management ─────────────────────────────────────────────────

    def get_or_create_collection(self, course_id: str):
        """Get or create the ChromaDB collection for a course."""
        client = self._get_client()
        name   = _collection_name(course_id)
        return client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def delete_collection(self, course_id: str) -> None:
        """Delete all vectors for a course (called on course deletion)."""
        client = self._get_client()
        name   = _collection_name(course_id)
        try:
            client.delete_collection(name)
            logger.info(f"Deleted ChromaDB collection: {name}")
        except Exception as e:
            logger.warning(f"Could not delete collection {name}: {e}")

    # ── Upsert ────────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        course_id: str,
        embedded_chunks: List[EmbeddedChunk],
    ) -> None:
        """
        Insert or update embedded chunks into the course collection.
        Uses upsert so re-processing an artifact is idempotent.
        """
        if not embedded_chunks:
            return

        collection = self.get_or_create_collection(course_id)

        ids        = [ec.chunk_id for ec in embedded_chunks]
        embeddings = [ec.embedding for ec in embedded_chunks]
        documents  = [ec.text for ec in embedded_chunks]
        metadatas  = [ec.chunk.to_chroma_metadata() for ec in embedded_chunks]

        # ChromaDB upsert in batches of 500
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            collection.upsert(
                ids=ids[i:i+batch_size],
                embeddings=embeddings[i:i+batch_size],
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size],
            )

        logger.info(
            f"Upserted {len(embedded_chunks)} vectors into "
            f"collection '{_collection_name(course_id)}'"
        )

    def delete_artifact_chunks(self, course_id: str, artifact_id: str) -> None:
        """Remove all chunks belonging to a specific artifact."""
        collection = self.get_or_create_collection(course_id)
        collection.delete(where={"artifact_id": artifact_id})
        logger.info(f"Deleted chunks for artifact {artifact_id} from course {course_id}")

    # ── Dense Retrieval ───────────────────────────────────────────────────────

    def query(
        self,
        course_id: str,
        query_embedding: List[float],
        top_k: int = 20,
        where: Optional[dict] = None,
    ) -> List[RetrievedChunk]:
        """
        Dense vector search against a course collection.
        Returns top_k results ordered by cosine similarity (descending).
        """
        collection = self.get_or_create_collection(course_id)

        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        try:
            results = collection.query(**kwargs)
        except Exception as e:
            logger.warning(f"ChromaDB query failed: {e}")
            return []

        retrieved = []
        docs      = results.get("documents",  [[]])[0]
        metas     = results.get("metadatas",  [[]])[0]
        dists     = results.get("distances",  [[]])[0]
        ids_      = results.get("ids",        [[]])[0]

        for doc, meta, dist, cid in zip(docs, metas, dists, ids_):
            # ChromaDB returns cosine distance (0=identical, 2=opposite)
            # Convert to similarity score 0–1
            score = max(0.0, 1.0 - (dist / 2.0))
            retrieved.append(RetrievedChunk(
                chunk_id=cid,
                text=doc,
                score=score,
                artifact_id=meta.get("artifact_id", ""),
                artifact_type=meta.get("artifact_type", ""),
                course_id=meta.get("course_id", ""),
                page_number=meta.get("page_number") if meta.get("page_number", -1) > 0 else None,
                slide_number=meta.get("slide_number") if meta.get("slide_number", -1) > 0 else None,
                section_title=meta.get("section_title") or None,
                week_number=meta.get("week_number") if meta.get("week_number", -1) > 0 else None,
                metadata=meta,
            ))

        return retrieved

    def collection_count(self, course_id: str) -> int:
        """Number of vectors stored for a course."""
        try:
            return self.get_or_create_collection(course_id).count()
        except Exception:
            return 0
