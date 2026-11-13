"""Retrieval recall and ranking on a labelled English and German set.

The keyword tests always run. The tests with the real embedding and reranker models follow the same switch
as test_german_retrieval.py (LECTIO_SKIP_MODEL_TESTS=1 skips them offline).
"""
import os
import re

import pytest

from knowledge import quality_eval as q

DATA = q.load_retrieval()
PASSAGES, QUERIES = DATA["passages"], DATA["queries"]
neural = pytest.mark.skipif(os.environ.get("LECTIO_SKIP_MODEL_TESTS") == "1", reason="model tests disabled")


def test_labelled_set_is_well_formed():
    ids = {p["id"] for p in PASSAGES}
    assert len(PASSAGES) == 24 and len(QUERIES) == 34 and len(ids) == 24
    assert all(set(query["relevant"]) <= ids and query["relevant"] for query in QUERIES)
    assert {query["pair"] for query in QUERIES} == {"en-en", "de-de", "de-en", "en-de"}
    text = {p["id"]: p["text"].lower() for p in PASSAGES}
    assert not any(query["text"].lower() in text[r] for query in QUERIES for r in query["relevant"])   # queries are paraphrases


def test_metrics_on_a_hand_computed_ranking():
    queries = [{"id": "a", "pair": "en-en", "text": "a", "relevant": ["p1"]}, {"id": "b", "pair": "en-en", "text": "b", "relevant": ["p9"]},
               {"id": "c", "pair": "de-de", "text": "c", "relevant": ["p3", "p4"]}]
    ranking = {"a": ["p1", "p2"], "b": ["p2", "p3"], "c": ["p2", "p4", "p3"]}
    result = q.retrieval_metrics(queries, ranking.get)
    assert result["all"] == {"queries": 3, "mrr": 0.5, "recall@1": 0.333, "recall@3": 0.667, "recall@5": 0.667}
    assert result["en-en"]["mrr"] == 0.5 and result["de-de"]["mrr"] == 0.5 and result["missed_in_top_5"] == ["b"]


def test_keyword_tokeniser_keeps_german_words_whole():
    from rag.retrieval.bm25_retriever import _tokenise
    assert _tokenise("Schlüssel für die Größe, Straße 12!") == ["schlüssel", "für", "die", "größe", "straße", "12"]


def test_keyword_retrieval_same_language_and_the_effect_of_the_tokeniser_fix():
    new = q.retrieval_metrics(QUERIES, q.bm25_ranker(PASSAGES))
    old = q.retrieval_metrics(QUERIES, q.bm25_ranker(PASSAGES, lambda t: re.findall(r"\b[a-z0-9]+\b", t.lower())))
    assert new["en-en"]["recall@3"] == 1.0 and new["de-de"]["recall@5"] >= 0.9
    assert new["de-de"]["mrr"] > old["de-de"]["mrr"] + 0.1 and new["de-de"]["recall@1"] > old["de-de"]["recall@1"]
    assert new["en-en"] == old["en-en"]                                    # English is unaffected


def test_offline_test_backend_finds_same_language_passages():
    result = q.retrieval_metrics(QUERIES, q.lexical_ranker(PASSAGES))
    assert result["en-en"]["recall@3"] == 1.0 and result["de-de"]["recall@3"] >= 0.9


def test_keyword_methods_cannot_cross_languages_and_this_is_measured():
    """Known limit, not a defect to hide: without embeddings a German query does not find an English passage."""
    for ranker in (q.bm25_ranker(PASSAGES), q.lexical_ranker(PASSAGES)):
        result = q.retrieval_metrics(QUERIES, ranker)
        assert result["de-en"]["recall@5"] == 0.0 and result["en-de"]["recall@5"] <= 0.2


def test_fusion_constant_matches_the_application():
    from rag.retrieval.hybrid_retriever import RRF_K
    assert q.RRF_K == RRF_K
    fused = q.hybrid_ranker(lambda query: ["a", "b", "c"], lambda query: ["c", "a"])("x")
    assert fused == ["a", "c", "b"]                                         # in both lists beats in one


@pytest.fixture(scope="module")
def dense():
    pytest.importorskip("sentence_transformers")
    return q.dense_ranker(PASSAGES)


@neural
def test_embedding_retrieval_recall_and_ranking_in_both_languages_and_across_them(dense):
    result = q.retrieval_metrics(QUERIES, dense)
    assert result["all"]["recall@5"] == 1.0 and result["all"]["mrr"] >= 0.85
    for pair in ("en-en", "de-de", "de-en", "en-de"):
        assert result[pair]["recall@3"] >= 0.8 and result[pair]["mrr"] >= 0.8, (pair, result[pair])


@neural
def test_equal_weight_fusion_loses_cross_language_matches_that_embeddings_find(dense):
    """Measured finding (docs/EVALUATION.md): on this set, fusing keyword and embedding ranks equally pushes
    same-language keyword hits above the right cross-language passage. Same-language queries do not suffer."""
    hybrid = q.retrieval_metrics(QUERIES, q.hybrid_ranker(dense, q.bm25_ranker(PASSAGES)))
    alone = q.retrieval_metrics(QUERIES, dense)
    assert hybrid["en-en"]["mrr"] >= alone["en-en"]["mrr"] and hybrid["de-de"]["mrr"] >= alone["de-de"]["mrr"]
    assert hybrid["de-en"]["mrr"] < alone["de-en"]["mrr"] - 0.3 and hybrid["en-de"]["mrr"] < alone["en-de"]["mrr"] - 0.3


@neural
def test_reranking_enough_candidates_recovers_cross_language_matches(dense):
    pytest.importorskip("sentence_transformers")
    hybrid = q.hybrid_ranker(dense, q.bm25_ranker(PASSAGES))
    result = q.retrieval_metrics(QUERIES, q.reranked(hybrid, PASSAGES, candidates=20))
    assert result["all"]["recall@5"] >= 0.9 and result["de-en"]["recall@1"] == 1.0 and result["en-de"]["recall@3"] >= 0.8
