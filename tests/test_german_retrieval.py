"""Real-model German/English retrieval check (downloads BAAI/bge-m3 + the multilingual reranker on first run).

Skipped only when sentence-transformers is not installed. Set LECTIO_SKIP_MODEL_TESTS=1 to skip offline.
"""
import os

import pytest

pytest.importorskip("sentence_transformers")
pytestmark = pytest.mark.skipif(os.environ.get("LECTIO_SKIP_MODEL_TESTS") == "1", reason="model tests disabled")

PASSAGES = [
    "Die binäre Suche halbiert in jedem Schritt den Suchraum eines sortierten Arrays; die Laufzeit ist logarithmisch.",
    "Ein Hashverfahren bildet Schlüssel über eine Hashfunktion auf Tabellenplätze ab und löst Kollisionen durch Verkettung.",
    "Die Tiefensuche durchläuft einen Graphen entlang eines Pfades bis zum Ende und kehrt dann mit Backtracking zurück.",
    "Binary search halves the search space of a sorted array in every step; its running time is logarithmic.",
    "Normalization removes redundancy from relational database schemas by decomposing tables.",
]


@pytest.fixture(scope="module")
def ranked():
    from rag.chunking.chunk_models import RawChunk
    from rag.embedding.bge_embedder import BGEEmbedder
    emb = BGEEmbedder("BAAI/bge-m3")
    chunks = [RawChunk(text=t, chunk_index=i, artifact_id="a", course_id="c", file_type="txt", artifact_type="slides")
              for i, t in enumerate(PASSAGES)]
    vecs = [e.embedding for e in emb.embed_chunks(chunks)]

    def rank(query):
        q = emb.embed_query(query)
        scores = [sum(a * b for a, b in zip(q, v)) for v in vecs]
        return sorted(range(len(PASSAGES)), key=lambda i: scores[i], reverse=True)
    return rank


def test_german_query_finds_german_passage(ranked):
    assert ranked("Wie funktioniert die Suche in einem sortierten Feld mit logarithmischer Laufzeit?")[0] == 0
    assert ranked("Wie werden Kollisionen in Hashtabellen behandelt?")[0] == 1
    assert ranked("Graphendurchlauf mit Backtracking")[0] == 2


def test_cross_lingual_german_query_matches_english_passage(ranked):
    assert ranked("Wie normalisiert man relationale Datenbankschemata?")[0] == 4
    assert set(ranked("Binärsuche")[:2]) == {0, 3}


def test_multilingual_reranker_prefers_relevant_german_passage():
    from config import settings
    from sentence_transformers import CrossEncoder
    ce = CrossEncoder(settings.rerank_model)
    q = "Wie behandelt eine Hashtabelle Kollisionen?"
    scores = ce.predict([(q, p) for p in PASSAGES])
    assert int(scores.argmax()) == 1
