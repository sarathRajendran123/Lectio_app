"""Rebuild slide chunks while preserving historical evidence identifiers.

This command stages parsed text and embeddings in memory, validates the entire
batch, and switches it in one transaction. Restart the API afterward to clear
its in-memory BM25 cache. Keep a verified database backup before running.
"""
import argparse
import asyncio
import hashlib
import math
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from config import settings
from db.chunk_visibility import current_chunk
from db.models.artifact import Chunk, CourseArtifact
from db.session import AsyncSessionLocal
from rag.chunking.semantic_chunker import SemanticChunker
from rag.embedding.bge_embedder import BGEEmbedder
from services.admission import assert_idle, lock_admission
from services.safe_parser import parse_document


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


async def snapshot(db, course_id, artifact_id=None):
    query = select(CourseArtifact).where(
        CourseArtifact.course_id == course_id, CourseArtifact.file_type == 'pdf',
        CourseArtifact.artifact_type == 'slides')
    if artifact_id:
        query = query.where(CourseArtifact.id == artifact_id)
    artifacts = list((await db.scalars(query.order_by(CourseArtifact.id))).all())
    if not artifacts or any(a.processing_status != 'done' for a in artifacts):
        raise ValueError('No matching slides or some slides are still processing.')
    result = []
    for a in artifacts:
        chunks = list((await db.scalars(select(Chunk).where(
            Chunk.artifact_id == a.id, current_chunk()))).all())
        if not chunks:
            raise ValueError(f'No active chunks for {a.original_filename}; refusing replacement.')
        result.append({'id': a.id, 'name': a.original_filename or a.filename,
            'path': a.storage_path, 'checksum': a.checksum,
            'ids': {c.id for c in chunks},
            'pages': {c.page_number for c in chunks if c.page_number is not None}})
    return result


async def prepare(course_id, artifact_id=None):
    if settings.runtime_mode != 'live' or settings.retrieval_backend != 'neural':
        raise ValueError('Reindexing requires live mode and neural retrieval.')
    async with AsyncSessionLocal() as db:
        if db.bind.dialect.name != 'postgresql':
            raise ValueError('This command currently requires PostgreSQL.')
        await assert_idle(course_id, db)
        sources = await snapshot(db, course_id, artifact_id)
    embedder = BGEEmbedder.get_instance(device=settings.embedding_device)
    chunker = SemanticChunker(use_semantic_split=True)
    staged = []
    for source in sources:
        path = Path(source['path'] or '')
        if not path.is_file():
            raise ValueError(f"Source file unavailable: {source['name']}")
        source['digest'] = await asyncio.to_thread(digest, path)
        print(f"Preparing {source['name']}...", flush=True)
        parsed = await parse_document(str(path), 'pdf', 'slides')
        chunks = await asyncio.to_thread(chunker.chunk, parsed, str(source['id']), str(course_id))
        missing = source['pages'] - {c.page_number for c in chunks}
        if not chunks or missing:
            raise ValueError(f"{source['name']}: no new chunks for prior pages {sorted(missing)}")
        embedded = await asyncio.to_thread(embedder.embed_chunks, chunks, 4)
        if len(embedded) != len(chunks) or any(ec.chunk.chunk_id != c.chunk_id for ec, c in zip(embedded, chunks)):
            raise ValueError(f"Embedding count or order mismatch in {source['name']}")
        dimension = await asyncio.to_thread(lambda: embedder.dimension)
        for ec in embedded:
            v = ec.embedding
            if len(v) != dimension or not all(math.isfinite(x) for x in v) or not any(v):
                raise ValueError(f"Invalid vector in {source['name']}")
        staged.append((source, embedded))
        print(f"  {len(source['ids'])} old -> {len(embedded)} staged chunks", flush=True)
    return staged


async def promote(course_id, staged, artifact_id=None):
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await lock_admission(db)
            await assert_idle(course_id, db)
            latest = await snapshot(db, course_id, artifact_id)
            prior = {s['id']: s for s, _ in staged}
            if {s['id'] for s in latest} != set(prior):
                raise ValueError('Slide files changed while staging. No changes applied.')
            for s in latest:
                old = prior[s['id']]
                if (s['ids'] != old['ids'] or s['checksum'] != old['checksum']
                        or s['path'] != old['path'] or await asyncio.to_thread(digest, s['path']) != old['digest']):
                    raise ValueError(f"Source changed during staging: {s['name']}")
            for source, embedded in staged:
                old_chunks = (await db.scalars(select(Chunk).where(Chunk.id.in_(source['ids'])))).all()
                for old in old_chunks:
                    old.metadata_ = dict(old.metadata_ or {}, retrieval_active=False)
                for ec in embedded:
                    c = ec.chunk
                    db.add(Chunk(id=UUID(c.chunk_id), artifact_id=source['id'], course_id=course_id,
                        text=c.text, token_count=c.token_count, char_count=c.char_count,
                        chunk_index=c.chunk_index, page_number=c.page_number, slide_number=c.slide_number,
                        section_title=c.section_title, week_number=c.week_number,
                        document_position=c.document_position, chroma_id=c.chunk_id,
                        embedding_model=settings.embedding_model,
                        metadata_={'artifact_type': 'slides', 'vector': ec.embedding,
                                   'parser_metadata': c.extra_metadata, 'retrieval_active': True}))
            await db.flush()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    course = parser.add_mutually_exclusive_group(required=True)
    course.add_argument('--course-id', type=UUID)
    course.add_argument('--course-code')
    parser.add_argument('--artifact-id', type=UUID)
    parser.add_argument('--apply', action='store_true', help='apply after staging and validation')
    parser.add_argument('--backend-stopped', action='store_true',
                        help='confirm the API and other writers are stopped for the complete run')
    args = parser.parse_args()
    if args.apply and not args.backend_stopped:
        parser.error('--apply requires --backend-stopped; stop API and other database writers first')
    course_id = args.course_id
    if args.course_code:
        from db.models.course import Course
        async with AsyncSessionLocal() as db:
            course_id = await db.scalar(select(Course.id).where(Course.code == args.course_code))
        if course_id is None:
            raise ValueError('Course code was not found.')
    print(f'Course {args.course_code or course_id} ({course_id})', flush=True)
    staged = await prepare(course_id, args.artifact_id)
    if args.apply:
        await promote(course_id, staged, args.artifact_id)
        print('Committed. Restart the backend before running retrieval or an audit.')
    else:
        print('Dry run complete. Nothing was changed in the database.')


if __name__ == '__main__':
    asyncio.run(main())
