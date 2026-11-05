"""Explicit offline test retrieval. Hash vectors are lexical, NOT semantic AI embeddings."""
import asyncio
import hashlib
import math
import re
from uuid import UUID
from sqlalchemy import select
from db.models.artifact import Chunk, CourseArtifact
from db.session import AsyncSessionLocal
from rag.chunking.chunk_models import RetrievedChunk
from rag.chunking.semantic_chunker import SemanticChunker
from rag.generation.grounded_generator import GroundedGenerator
from db.repositories.artifact_repository import ArtifactRepository
from services.safe_parser import parse_document

STOP = {'the','and','for','with','that','this','from','will','able','students','learning','outcome','explain','describe','apply','understand','analyse','analyze','evaluate','create','lecture','slides','covering'}
STOP |= {'der','die','das','und','ist','nicht','mit','von','den','für','auf','ein','eine','wird','sich','als','sie','werden','können','studierenden','studierende','wie','auch','oder','dem','des','zur','zum','bei','nach','über'}
def terms(text):
    return [w for w in re.findall(r'\b\w{3,}\b',text.lower()) if w not in STOP]
def vector(text):
    values = [0.] * 256
    for word in terms(text):
        index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], 'big') % 256
        values[index] += 1
    length = math.sqrt(sum(v*v for v in values)) or 1
    return [v/length for v in values]

def matches(chunk, where):
    for key, expected in (where or {}).items():
        value = getattr(chunk, key, chunk.metadata.get(key))
        if isinstance(expected, dict):
            if '$in' in expected and value not in expected['$in']: return False
            if '$eq' in expected and value != expected['$eq']: return False
        elif value != expected: return False
    return True

class LocalRAGService:
    async def ingest_artifact(self, artifact_id, course_id, file_path, file_type, artifact_type, db):
        artifact_id, course_id = UUID(str(artifact_id)), UUID(str(course_id))
        repo = ArtifactRepository(db)
        await repo.set_status(artifact_id, 'parsing'); await db.commit()
        parsed = await parse_document(file_path, file_type, artifact_type)
        await repo.set_status(artifact_id, 'chunking'); await db.commit()
        chunks = SemanticChunker(min_tokens=1).chunk(parsed, str(artifact_id), str(course_id))
        if not chunks: raise ValueError('No usable text chunks found.')
        for c in chunks:
            db.add(Chunk(id=UUID(c.chunk_id),artifact_id=artifact_id,course_id=course_id,text=c.text,
                chunk_index=c.chunk_index,page_number=c.page_number,slide_number=c.slide_number,
                section_title=c.section_title,week_number=c.week_number,token_count=c.token_count,
                char_count=c.char_count,embedding_model='local-test-hash-256',
                metadata_={'artifact_type':artifact_type,'vector':vector(c.text)}))
        artifact = await db.get(CourseArtifact, artifact_id)
        artifact.metadata_ = {'parse_warnings': parsed.parse_warnings, 'extraction_mode': 'deterministic', 'review_required': True}
        await repo.update_counts(artifact_id, parsed.total_pages, parsed.total_slides, parsed.word_count)
        await repo.set_status(artifact_id, 'done'); await db.commit()
        return len(chunks)

    async def load(self, course_id):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Chunk, CourseArtifact).join(CourseArtifact, Chunk.artifact_id == CourseArtifact.id)
                .where(Chunk.course_id == UUID(str(course_id)), CourseArtifact.processing_status == 'done'))).all()
            return [RetrievedChunk(str(c.id),c.text,0.,str(c.artifact_id),a.artifact_type,str(c.course_id),
                c.page_number,c.slide_number,c.section_title,c.week_number,dict(c.metadata_ or {},filename=a.original_filename)) for c,a in rows]

    def retrieve(self, query, course_id, top_k=10, where=None, **kwargs):
        from agents.base_agent import BaseAgent
        chunks = BaseAgent._run_async(self.load(course_id))
        qterms=set(terms(query)); qvec=vector(query)
        found=[]
        for c in chunks:
            if not matches(c,where): continue
            overlap = qterms & set(terms(c.text))
            if not overlap: continue
            v=c.metadata.get('vector') or vector(c.text)
            cosine=sum(a*b for a,b in zip(v,qvec))
            c.score=round(0.65*len(overlap)/max(1,len(qterms))+0.35*max(0,cosine),4)
            if c.score >= .12: found.append(c)
        return sorted(found,key=lambda c:c.score,reverse=True)[:min(top_k,40)]

    def generate(self, task_prompt, course_id, top_k=10, where=None, extra_instructions=None):
        return GroundedGenerator().generate(task_prompt, self.retrieve(task_prompt,course_id,top_k,where),extra_instructions)
