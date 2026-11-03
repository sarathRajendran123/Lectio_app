"""
LECTIO — Artifact Repository
All DB operations for CourseArtifact and Chunk records.
"""

import hashlib
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.artifact import Chunk, CourseArtifact


class ArtifactRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── CourseArtifact ────────────────────────────────────────────────────────

    async def create(
        self,
        course_id: UUID,
        uploaded_by: UUID,
        filename: str,
        original_filename: str,
        file_type: str,
        artifact_type: str,
        file_size_bytes: int,
        storage_path: str,
        checksum: str,
    ) -> CourseArtifact:
        artifact = CourseArtifact(
            course_id=course_id,
            uploaded_by=uploaded_by,
            filename=filename,
            original_filename=original_filename,
            file_type=file_type,
            artifact_type=artifact_type,
            file_size_bytes=file_size_bytes,
            storage_path=storage_path,
            checksum=checksum,
            processing_status="pending",
        )
        self.db.add(artifact)
        await self.db.flush()
        return artifact

    async def get_by_id(self, artifact_id: UUID) -> Optional[CourseArtifact]:
        result = await self.db.execute(
            select(CourseArtifact).where(CourseArtifact.id == artifact_id)
        )
        return result.scalar_one_or_none()

    async def list_for_course(
        self,
        course_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[int, List[CourseArtifact]]:
        total_q = await self.db.execute(
            select(func.count(CourseArtifact.id))
            .where(CourseArtifact.course_id == course_id)
        )
        total = total_q.scalar_one()

        result = await self.db.execute(
            select(CourseArtifact)
            .where(CourseArtifact.course_id == course_id)
            .order_by(CourseArtifact.uploaded_at.desc())
            .offset(skip).limit(limit)
        )
        return total, list(result.scalars().all())

    async def set_status(
        self,
        artifact_id: UUID,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        from datetime import datetime, timezone
        values: dict = {"processing_status": status}
        if error:
            values["processing_error"] = error
        if status == "done":
            values["processed_at"] = datetime.now(timezone.utc)
        await self.db.execute(
            update(CourseArtifact)
            .where(CourseArtifact.id == artifact_id)
            .values(**values)
        )

    async def update_counts(
        self,
        artifact_id: UUID,
        page_count: Optional[int] = None,
        slide_count: Optional[int] = None,
        word_count: Optional[int] = None,
    ) -> None:
        values = {}
        if page_count  is not None: values["page_count"]  = page_count
        if slide_count is not None: values["slide_count"] = slide_count
        if word_count  is not None: values["word_count"]  = word_count
        if values:
            await self.db.execute(
                update(CourseArtifact)
                .where(CourseArtifact.id == artifact_id)
                .values(**values)
            )

    async def delete(self, artifact_id: UUID) -> bool:
        artifact = await self.get_by_id(artifact_id)
        if not artifact:
            return False
        await self.db.delete(artifact)
        await self.db.flush()
        return True

    async def find_duplicate(self, course_id: UUID, checksum: str) -> Optional[CourseArtifact]:
        """Detect duplicate uploads by SHA-256 checksum."""
        result = await self.db.execute(
            select(CourseArtifact).where(
                CourseArtifact.course_id == course_id,
                CourseArtifact.checksum == checksum,
            )
        )
        return result.scalar_one_or_none()

    # ── Chunks ────────────────────────────────────────────────────────────────

    async def count_chunks(self, artifact_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Chunk.id)).where(Chunk.artifact_id == artifact_id)
        )
        return result.scalar_one()

    async def count_chunks_for_course(self, course_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Chunk.id)).where(Chunk.course_id == course_id)
        )
        return result.scalar_one()


def compute_checksum(data: bytes) -> str:
    """SHA-256 checksum of file bytes."""
    return hashlib.sha256(data).hexdigest()
