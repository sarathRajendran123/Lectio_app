import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.chunk_visibility import current_chunk
from db.models.artifact import Chunk, CourseArtifact
from db.models.course import Course
from db.session import AsyncSessionLocal
from rag.chunking.chunk_models import EmbeddedChunk, RawChunk
from services import reindex_slides


def test_promote_preserves_citations_and_rolls_back_stale_batch(client, tmp_path, monkeypatch):
    async def no_lock(db):
        pass
    monkeypatch.setattr(reindex_slides, 'lock_admission', no_lock)

    async def run():
        course_id, artifact_id, old_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        path = tmp_path / 'slides.pdf'
        path.write_bytes(b'fixture')
        async with AsyncSessionLocal() as db:
            db.add(Course(id=course_id, code=str(course_id), title='Test'))
            await db.flush()
            db.add(CourseArtifact(id=artifact_id, course_id=course_id, filename='slides.pdf',
                original_filename='slides.pdf', file_type='pdf', artifact_type='slides',
                storage_path=str(path), processing_status='done', metadata_={}))
            await db.flush()
            db.add(Chunk(id=old_id, artifact_id=artifact_id, course_id=course_id,
                text='old source', page_number=1, metadata_={'vector': [1.0]}))
            await db.commit()
        async with AsyncSessionLocal() as db:
            source = (await reindex_slides.snapshot(db, course_id))[0]
        source['digest'] = reindex_slides.digest(path)
        chunk = RawChunk(text='new full slide', chunk_index=0, artifact_id=str(artifact_id),
            course_id=str(course_id), file_type='pdf', artifact_type='slides', page_number=1,
            slide_number=None, section_title=None, week_number=None)
        stage = [(source, [EmbeddedChunk(chunk=chunk, embedding=[1.0, 0.0])])]

        path.write_bytes(b'changed')
        with pytest.raises(ValueError, match='changed'):
            await reindex_slides.promote(course_id, stage)
        async with AsyncSessionLocal() as db:
            assert (await db.get(Chunk, old_id)).metadata_.get('retrieval_active') is None
            assert await db.get(Chunk, uuid.UUID(chunk.chunk_id)) is None

        path.write_bytes(b'fixture')
        with pytest.raises(IntegrityError):
            await reindex_slides.promote(course_id, [(source, [stage[0][1][0], stage[0][1][0]])])
        async with AsyncSessionLocal() as db:
            assert (await db.get(Chunk, old_id)).metadata_.get('retrieval_active') is None
            assert await db.get(Chunk, uuid.UUID(chunk.chunk_id)) is None

        await reindex_slides.promote(course_id, stage)
        async with AsyncSessionLocal() as db:
            old = await db.get(Chunk, old_id)
            assert old.text == 'old source'
            assert old.metadata_['retrieval_active'] is False
            active = (await db.scalars(select(Chunk).where(
                Chunk.course_id == course_id, current_chunk()))).all()
            assert [c.text for c in active] == ['new full slide']

    asyncio.run(run())
