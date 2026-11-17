from types import SimpleNamespace

import pytest

from config import settings
from rag.chunking.chunk_models import RetrievedChunk
from rag.retrieval.hybrid_retriever import HybridRetriever, _cosine


def _chunk(cid, score, metadata):
    return RetrievedChunk(cid, 'text', score, 'artifact', 'slides', 'course', 1, None, None, None, metadata)


def test_sparse_only_hits_use_cosine_not_bm25_for_audit_score(monkeypatch):
    monkeypatch.setattr(settings, 'embedding_model', 'test-model')
    dense = _chunk('dense', .8, {})
    sparse = _chunk('sparse', .99, {'vector': [0., 1.], 'embedding_model': 'test-model'})
    wrong = _chunk('wrong-model', .98, {'vector': [1., 0.], 'embedding_model': 'different-model'})
    retriever = HybridRetriever(SimpleNamespace(embed_query=lambda q: [1., 0.]),
        SimpleNamespace(query=lambda **kwargs: [dense]),
        SimpleNamespace(search=lambda **kwargs: [sparse, wrong]), final_top_k=3)
    results = {c.chunk_id: c for c in retriever.retrieve('query', 'course')}
    assert results['dense'].score == .8
    assert results['sparse'].score == 0.0
    assert results['sparse'].metadata['similarity_available'] is True
    assert results['wrong-model'].score == 0.0
    assert results['wrong-model'].metadata['similarity_available'] is False


@pytest.mark.parametrize('vector', [None, [], [1], [float('nan'), 1], ['bad', 1]])
def test_invalid_vectors_do_not_become_similarity_scores(vector):
    assert _cosine([1., 0.], vector) is None
