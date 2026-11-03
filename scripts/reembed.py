"""Re-embed stored chunks whose vectors came from a different embedding model (e.g. after switching to bge-m3).

Uses the stored chunk text; documents are not re-parsed or re-uploaded. Chunks already on the
current model are skipped, so the script is safe to re-run. Back up the database first.
"""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1];load_dotenv(root/'.env');sys.path.insert(0,str(root/'backend'))
from sqlalchemy import select
from config import settings
from db.models.artifact import Chunk
from db.session import AsyncSessionLocal
from rag.embedding.bge_embedder import BGEEmbedder

BATCH=64

async def main():
    embedder=BGEEmbedder.get_instance(device=settings.embedding_device);done=0
    async with AsyncSessionLocal() as db:
        rows=list((await db.scalars(select(Chunk).where((Chunk.embedding_model.is_(None))|(Chunk.embedding_model!=settings.embedding_model)))).all())
        for i in range(0,len(rows),BATCH):
            batch=rows[i:i+BATCH]
            vectors=await asyncio.to_thread(embedder.embed_texts,[c.text for c in batch])
            for chunk,vector in zip(batch,vectors):
                chunk.metadata_={**(chunk.metadata_ or {}),'vector':vector};chunk.embedding_model=settings.embedding_model
            await db.commit();done+=len(batch)
    print(f'Re-embedded {done} chunk(s) with {settings.embedding_model}.')

if __name__=='__main__':asyncio.run(main())
