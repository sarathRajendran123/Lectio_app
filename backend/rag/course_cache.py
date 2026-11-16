"""Each course's passages and vectors, read from the database once and reused by every search.

Before this cache every search read all passages of the course twice and decoded every stored vector from JSON:
on a 13-lecture course (3,407 passages) that was about 3.3 of the 3.5 seconds a search took. Now one small query
(count, newest creation and embedding time, embedding models of the processed passages) checks whether the course
changed; only then are the passages read again. Similarities are computed with numpy on a normalised matrix.

Callers get fresh copies of the passages, because several of them set `score` on what they receive.
"""
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from uuid import UUID

import numpy as np
from sqlalchemy import func, select

from db.models.artifact import Chunk, CourseArtifact
from db.session import AsyncSessionLocal
from rag.chunking.chunk_models import RetrievedChunk

MAX_COURSES = 8                     # about 14 MB per 3,400 passages of 1,024-dimensional vectors
_lock = threading.Lock()
_cache: "OrderedDict[str, Corpus]" = OrderedDict()


@dataclass
class Corpus:
    fingerprint: tuple
    passages: list                  # RetrievedChunk, score 0, metadata with the vector and the file name
    models: list                    # embedding model per passage
    matrix: np.ndarray              # rows: unit vectors of the passages that have one of dimension `dimension`
    rows: np.ndarray                # passage index of each matrix row
    dimension: int

    def copies(self) -> list:
        return [replace(p, metadata=dict(p.metadata)) for p in self.passages]


def _course_filter(course_id):
    return (Chunk.course_id == UUID(str(course_id)), CourseArtifact.processing_status == "done")


async def _fingerprint(db, course_id) -> tuple:
    row = (await db.execute(select(func.count(Chunk.id), func.max(Chunk.created_at), func.max(Chunk.embedded_at),
                                   func.min(Chunk.embedding_model), func.max(Chunk.embedding_model))
                            .join(CourseArtifact, Chunk.artifact_id == CourseArtifact.id).where(*_course_filter(course_id)))).one()
    return tuple(str(value) for value in row)


async def _load(db, course_id, fingerprint) -> Corpus:
    rows = (await db.execute(select(Chunk, CourseArtifact).join(CourseArtifact, Chunk.artifact_id == CourseArtifact.id)
                             .where(*_course_filter(course_id)).order_by(Chunk.chunk_index, Chunk.id).limit(10001))).all()
    passages, models, vectors = [], [], []
    for chunk, artifact in rows:
        metadata = dict(chunk.metadata_ or {}, filename=artifact.original_filename)
        passages.append(RetrievedChunk(str(chunk.id), chunk.text, 0., str(artifact.id), artifact.artifact_type, str(chunk.course_id),
                                       chunk.page_number, chunk.slide_number, chunk.section_title, chunk.week_number, metadata))
        models.append(chunk.embedding_model)
        vectors.append(metadata.get("vector") or [])
    lengths = [len(v) for v in vectors if v]
    dimension = max(set(lengths), key=lengths.count) if lengths else 0
    index = [i for i, v in enumerate(vectors) if dimension and len(v) == dimension]
    matrix = np.asarray([vectors[i] for i in index], dtype=np.float32).reshape(len(index), dimension)
    norms = np.linalg.norm(matrix, axis=1) if len(index) else np.zeros(0, dtype=np.float32)
    keep = norms > 0
    matrix = matrix[keep] / norms[keep][:, None] if len(index) else matrix
    return Corpus(fingerprint, passages, models, matrix, np.asarray(index, dtype=np.int64)[keep] if len(index) else np.zeros(0, dtype=np.int64), dimension)


async def aget(course_id) -> Corpus:
    key = str(course_id)
    async with AsyncSessionLocal() as db:
        fingerprint = await _fingerprint(db, key)
        with _lock:
            corpus = _cache.get(key)
            if corpus is not None and corpus.fingerprint == fingerprint:
                _cache.move_to_end(key)
                return corpus
        corpus = await _load(db, key, fingerprint)
    with _lock:
        _cache[key] = corpus
        _cache.move_to_end(key)
        while len(_cache) > MAX_COURSES:
            _cache.popitem(last=False)
    return corpus


def get(course_id) -> Corpus:
    from agents.base_agent import BaseAgent
    return BaseAgent._run_async(aget(course_id))


def invalidate(course_id=None) -> None:
    """Drop one course (or all). The fingerprint check alone already notices changes; this is for explicit callers."""
    with _lock:
        if course_id is None:
            _cache.clear()
        else:
            _cache.pop(str(course_id), None)
