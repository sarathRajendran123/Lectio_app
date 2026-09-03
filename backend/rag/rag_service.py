"""
LECTIO — RAG Service
Single facade that agents call. Hides all pipeline complexity.

Usage (from any agent):
    rag = RAGService.get_instance()

    # Ingest an uploaded artifact
    await rag.ingest_artifact(artifact_id, course_id, file_path, file_type, artifact_type, db)

    # Retrieve context for alignment auditing
    chunks = rag.retrieve(query="implement sorting algorithm", course_id=course_id)

    # Generate grounded content
    result = rag.generate(task_prompt="Generate 3 CLOs for Module 2", course_id=course_id)
"""

import asyncio
import logging
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.repositories.artifact_repository import ArtifactRepository
from rag.chunking.chunk_models import RetrievedChunk
from rag.chunking.semantic_chunker import SemanticChunker
from rag.embedding.bge_embedder import BGEEmbedder
from rag.generation.grounded_generator import GeneratedItem, GroundedGenerator
from rag.parsers import get_parser
from rag.retrieval.bm25_retriever import bm25_retriever
from rag.retrieval.hybrid_retriever import HybridRetriever
from rag.retrieval.reranker import CrossEncoderReranker
from vector_db.chroma_client import ChromaCollectionManager

logger = logging.getLogger(__name__)


class RAGService:
    """
    Orchestrates the full RAG pipeline:
      ingest → chunk → embed → store
      retrieve (hybrid) → rerank → generate (grounded)
    """

    _instance: Optional["RAGService"] = None

    def __init__(self):
        self._embedder  = BGEEmbedder.get_instance(device=settings.embedding_device)
        self._chroma    = ChromaCollectionManager.get_instance()
        self._chunker   = SemanticChunker()
        self._reranker  = CrossEncoderReranker.get_instance()
        self._generator = GroundedGenerator()
        self._hybrid    = HybridRetriever(
            embedder=self._embedder,
            chroma=self._chroma,
            bm25=bm25_retriever,
        )

    @classmethod
    def get_instance(cls) -> "RAGService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Ingestion ─────────────────────────────────────────────────────────────

    async def ingest_artifact(
        self,
        artifact_id: str,
        course_id:   str,
        file_path:   str,
        file_type:   str,
        artifact_type: str,
        db: AsyncSession,
    ) -> int:
        """
        Full ingestion pipeline for one artifact.
        Returns number of chunks stored.

        Steps:
          1. Parse   → ParsedDocument
          2. Chunk   → List[RawChunk]
          3. Embed   → List[EmbeddedChunk]
          4. Store   → ChromaDB + PostgreSQL chunks table
          5. BM25    → Invalidate + rebuild index
        """
        repo = ArtifactRepository(db)

        try:
            await repo.set_status(artifact_id, "parsing")
            await db.commit()  # make status visible to polling clients immediately

            # 1. Parse
            # Run on a worker thread — parsing (and every other step below) is
            # synchronous/blocking. Called directly, it would freeze this
            # process's single event loop for the whole pipeline duration,
            # so ALL other requests (including the frontend's status polling)
            # would hang until the step finished. asyncio.to_thread() keeps
            # the loop free to keep serving other requests concurrently.
            logger.info(f"Parsing artifact {artifact_id} ({file_type})")
            parser = get_parser(file_type)
            parsed = await asyncio.to_thread(parser.parse, file_path, artifact_type)

            # Update counts from parsing
            await repo.update_counts(
                artifact_id=artifact_id,
                page_count=parsed.total_pages,
                slide_count=parsed.total_slides,
                word_count=parsed.word_count,
            )
            await db.commit()

            # 2. Chunk
            await repo.set_status(artifact_id, "chunking")
            await db.commit()
            logger.info(f"Chunking artifact {artifact_id}")
            raw_chunks = await asyncio.to_thread(
                self._chunker.chunk,
                doc=parsed,
                artifact_id=artifact_id,
                course_id=course_id,
            )

            if not raw_chunks:
                logger.warning(f"No chunks produced for artifact {artifact_id}")
                await repo.set_status(artifact_id, "done")
                await db.commit()
                return 0

            # 3. Embed — the slowest, most CPU-heavy step (local model
            # inference on CPU, plus a one-off model load on first use).
            await repo.set_status(artifact_id, "embedding")
            await db.commit()
            logger.info(f"Embedding {len(raw_chunks)} chunks for artifact {artifact_id}")
            embedded = await asyncio.to_thread(self._embedder.embed_chunks, raw_chunks)

            # 4a. Store in ChromaDB (synchronous HTTP client — also offloaded)
            await repo.set_status(artifact_id, "storing")
            await db.commit()
            await asyncio.to_thread(self._chroma.upsert_chunks, course_id, embedded)

            # 4b. Store chunk records in PostgreSQL
            await self._store_chunks_in_db(embedded, db)

            # 5. Rebuild BM25 index
            bm25_retriever.invalidate(course_id)
            # Lazy rebuild happens on next retrieval query

            await repo.set_status(artifact_id, "done")
            await db.commit()
            logger.info(f"Ingestion complete: {len(embedded)} chunks for artifact {artifact_id}")
            return len(embedded)

        except Exception as e:
            error_msg = str(e)[:500]
            logger.error(f"Ingestion failed for artifact {artifact_id}: {e}", exc_info=True)
            # Roll back any half-finished work from this transaction BEFORE
            # writing the error status. Otherwise the outer except block in
            # ingestion_task.py calls db.rollback() again, which would wipe
            # out the "error" status too and leave the artifact stuck at its
            # last status forever with no visible error.
            await db.rollback()
            await repo.set_status(artifact_id, "error", error=error_msg)
            await db.commit()
            raise

    async def _store_chunks_in_db(self, embedded_chunks, db: AsyncSession) -> None:
        """Persist chunk records to PostgreSQL chunks table."""
        from db.models.artifact import Chunk
        import uuid

        for ec in embedded_chunks:
            c = ec.chunk
            chunk_record = Chunk(
                id=uuid.UUID(c.chunk_id),
                artifact_id=uuid.UUID(c.artifact_id),
                course_id=uuid.UUID(c.course_id),
                text=c.text,
                token_count=c.token_count,
                char_count=c.char_count,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                slide_number=c.slide_number,
                section_title=c.section_title,
                week_number=c.week_number,
                document_position=c.document_position,
                chroma_id=ec.chunk_id,
                embedding_model=settings.embedding_model,
            )
            db.add(chunk_record)

        await db.flush()

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query:     str,
        course_id: str,
        top_k:     int = 10,
        where:     Optional[dict] = None,
        rerank:    bool = True,
        db_sync=None,     # synchronous DB session for BM25 loader (optional)
    ) -> List[RetrievedChunk]:
        """
        Retrieve grounded context chunks for a query.

        Args:
            query:     the alignment check question or generation prompt
            course_id: target course
            top_k:     final number of chunks to return
            where:     optional ChromaDB filter (e.g. {"artifact_type": "slides"})
            rerank:    whether to apply cross-encoder reranking

        Returns:
            Ordered list of RetrievedChunk (best first)
        """
        # Hybrid retrieval (dense + BM25)
        candidates = self._hybrid.retrieve(
            query=query,
            course_id=course_id,
            top_k=top_k * 4,   # over-retrieve for reranker
            where=where,
        )

        if not candidates:
            logger.warning(f"No candidates retrieved for query: '{query[:80]}'")
            return []

        # Cross-encoder reranking
        if rerank and len(candidates) > top_k:
            candidates = self._reranker.rerank(
                query=query,
                chunks=candidates,
                top_k=top_k,
            )
        else:
            candidates = candidates[:top_k]

        return candidates

    # ── Generation ────────────────────────────────────────────────────────────

    def generate(
        self,
        task_prompt: str,
        course_id:   str,
        top_k:       int = 10,
        where:       Optional[dict] = None,
        extra_instructions: Optional[str] = None,
    ) -> GeneratedItem:
        """
        Retrieve context then generate grounded content.

        Args:
            task_prompt:        What to generate (e.g. "Write 3 CLOs for Module 2")
            course_id:          Target course
            top_k:              Context chunks to retrieve
            where:              ChromaDB filter
            extra_instructions: Reviewer preferences from episodic memory

        Returns:
            GeneratedItem with content and resolved citations
        """
        context = self.retrieve(
            query=task_prompt,
            course_id=course_id,
            top_k=top_k,
            where=where,
            rerank=True,
        )

        return self._generator.generate(
            task_prompt=task_prompt,
            context_chunks=context,
            extra_instructions=extra_instructions,
        )
