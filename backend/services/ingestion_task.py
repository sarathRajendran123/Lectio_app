"""
LECTIO — Background Ingestion Task
Called by FastAPI BackgroundTasks immediately after a successful upload.
Runs the full RAG pipeline asynchronously so the upload response is instant.

Flow:
  POST /artifacts  →  file saved to disk (sync, fast)
                   →  HTTP 201 returned to client
                   →  [background] ingest_artifact() runs RAG pipeline
                   →  artifact.processing_status updated to 'done'

Client polls GET /artifacts/{id}/status to track progress.
"""

import logging

from db.session import AsyncSessionLocal
from rag.rag_service import RAGService

logger = logging.getLogger(__name__)


import asyncio
INGESTION_SLOTS=asyncio.Semaphore(2)

async def _run_ingestion_pipeline(
    artifact_id:   str,
    course_id:     str,
    file_path:     str,
    file_type:     str,
    artifact_type: str,
) -> None:
    """
    Entry point for FastAPI BackgroundTasks.
    Opens its own DB session (background tasks don't share the request session).
    """
    logger.info(f"[BG] Starting ingestion for artifact {artifact_id}")

    async with AsyncSessionLocal() as db:
        try:
            rag = RAGService.get_instance()
            n = await rag.ingest_artifact(
                artifact_id=artifact_id,
                course_id=course_id,
                file_path=file_path,
                file_type=file_type,
                artifact_type=artifact_type,
                db=db,
            )
            await db.commit()
            logger.info(f"[BG] Ingestion complete: {n} chunks | artifact {artifact_id}")

        except Exception as e:
            await db.rollback()
            from uuid import UUID
            from db.repositories.artifact_repository import ArtifactRepository
            await ArtifactRepository(db).set_status(UUID(artifact_id), "error", error=str(e)[:500])
            await db.commit()
            logger.error(
                f"[BG] Ingestion FAILED for artifact {artifact_id}: {e}",
                exc_info=True,
            )

async def run_ingestion_pipeline(artifact_id,course_id,file_path,file_type,artifact_type):
    async with INGESTION_SLOTS:
        await _run_ingestion_pipeline(artifact_id,course_id,file_path,file_type,artifact_type)
