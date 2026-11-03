"""Bounded cosine clustering over existing source chunks, with transparent labels."""
from collections import Counter
from uuid import UUID,uuid5,NAMESPACE_URL
import math
from config import settings
from rag.local_service import vector,terms

def cluster(chunks):
    # Semantic vectors in live mode; lexical hash vectors only in explicit test mode.
    if settings.runtime_mode=='live' and settings.retrieval_backend=='neural':
        from rag.embedding.bge_embedder import BGEEmbedder
        embedder=BGEEmbedder.get_instance()
        vectors=[embedder.embed_query(c.text) for c in chunks]
    else:vectors=[vector(c.text) for c in chunks]
    groups=[]
    for source,v in zip(chunks,vectors):
        best=None;score=.65
        for group in groups:
            similarity=sum(x*y for x,y in zip(v,group['centroid']))
            if similarity>score:best=group;score=similarity
        if best is None:
            best={'chunks':[],'vectors':[],'centroid':v};groups.append(best)
        best['chunks'].append(source);best['vectors'].append(v)
        sums=[sum(column) for column in zip(*best['vectors'])]
        length=math.sqrt(sum(x*x for x in sums)) or 1
        best['centroid']=[x/length for x in sums]
    output=[]
    for g in groups:
        ids=sorted(str(c.id) for c in g['chunks'])
        label=', '.join(word for word,_ in Counter(w for c in g['chunks'] for w in terms(c.text)).most_common(4)) or 'Unlabelled source group'
        output.append({'id':str(uuid5(NAMESPACE_URL,':'.join(ids))),'label':label,'chunk_ids':ids,
            'method':'BGE cosine' if settings.runtime_mode=='live' and settings.retrieval_backend=='neural' else 'local-test lexical hash cosine','review_required':True})
    return output
