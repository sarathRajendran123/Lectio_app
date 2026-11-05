"""Course-isolated dense vector retrieval using the existing transactional database.

Vectors are stored with Chunk.metadata_ in the same transaction as their source
text. No separate unauthenticated collection/embedding-function API is exposed.
Exact cosine search is appropriate for this bounded research prototype.
"""
import math
from uuid import UUID
from config import settings
from sqlalchemy import select
from db.session import AsyncSessionLocal
from db.models.artifact import Chunk,CourseArtifact
from rag.chunking.chunk_models import RetrievedChunk

class SQLVectorStore:
    def upsert_chunks(self,course_id,chunks):
        # RAGService stores source text and vectors together in its existing transaction.
        for item in chunks:
            if item.chunk.course_id!=str(course_id):raise ValueError('Cross-course vector insertion refused.')
    async def _rows(self,course_id):
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Chunk,CourseArtifact).join(CourseArtifact,Chunk.artifact_id==CourseArtifact.id)
                .where(Chunk.course_id==UUID(str(course_id)),CourseArtifact.processing_status=='done').limit(10001))).all()
    def query(self,course_id,query_embedding,top_k=10,where=None):
        from agents.base_agent import BaseAgent
        from rag.local_service import matches
        rows=BaseAgent._run_async(self._rows(course_id))
        if len(rows)>10000:raise ValueError('Exact-vector prototype supports at most 10,000 chunks per course. Reduce the corpus or provision an indexed vector store.')
        neural=settings.runtime_mode=='live' and settings.retrieval_backend=='neural'
        qnorm=math.sqrt(sum(x*x for x in query_embedding))
        if qnorm==0:return []
        results=[]
        for chunk,artifact in rows:
            metadata=chunk.metadata_ or {};vec=metadata.get('vector')
            if not vec or len(vec)!=len(query_embedding):continue
            if neural and chunk.embedding_model and chunk.embedding_model!=settings.embedding_model:continue  # stale vector space; re-embed
            vnorm=math.sqrt(sum(x*x for x in vec))
            if vnorm==0:continue
            score=max(0.,min(1.,sum(x*y for x,y in zip(query_embedding,vec))/(qnorm*vnorm)))
            if score<.2:continue
            result=RetrievedChunk(str(chunk.id),chunk.text,score,str(artifact.id),artifact.artifact_type,str(chunk.course_id),
                chunk.page_number,chunk.slide_number,chunk.section_title,chunk.week_number,
                dict(metadata,filename=artifact.original_filename))
            if matches(result,where):results.append(result)
        return sorted(results,key=lambda c:c.score,reverse=True)[:min(top_k,80)]
    def heartbeat(self):return True
