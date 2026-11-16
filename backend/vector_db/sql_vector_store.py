"""Course-isolated dense vector retrieval using the existing transactional database.

Vectors are stored with Chunk.metadata_ in the same transaction as their source
text. No separate unauthenticated collection/embedding-function API is exposed.
Exact cosine search is appropriate for this bounded research prototype.
"""
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
        import numpy as np
        from rag import course_cache
        from rag.local_service import matches
        corpus=course_cache.get(course_id)
        if len(corpus.passages)>10000:raise ValueError('Exact-vector prototype supports at most 10,000 chunks per course. Reduce the corpus or provision an indexed vector store.')
        neural=settings.runtime_mode=='live' and settings.retrieval_backend=='neural'
        query=np.asarray(query_embedding,dtype=np.float32)
        qnorm=float(np.linalg.norm(query))
        if qnorm==0 or len(query)!=corpus.dimension or not len(corpus.rows):return []
        scores=np.clip(corpus.matrix@(query/qnorm),0.,1.)
        results=[]
        for position in np.argsort(-scores,kind='stable'):
            score=float(scores[position])
            if score<.2:break
            index=int(corpus.rows[position]);model=corpus.models[index]
            if neural and model and model!=settings.embedding_model:continue  # stale vector space; re-embed
            passage=corpus.passages[index]
            if not matches(passage,where):continue
            results.append(RetrievedChunk(passage.chunk_id,passage.text,score,passage.artifact_id,passage.artifact_type,passage.course_id,
                passage.page_number,passage.slide_number,passage.section_title,passage.week_number,dict(passage.metadata)))
            if len(results)>=min(top_k,80):break
        return results
    def heartbeat(self):return True
