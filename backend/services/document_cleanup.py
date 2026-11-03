"""Source-linked SQL vectors are removed by the source transaction, not a remote service."""
async def invalidate_artifact(course_id,artifact_id):
    from rag.retrieval.bm25_retriever import bm25_retriever
    bm25_retriever.invalidate(str(course_id))
