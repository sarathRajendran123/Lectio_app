"""Measure extraction and retrieval against small labelled sets (datasets/extraction, datasets/retrieval).

The bundled keys are provisional (written during development, not lecturer-reviewed, synthetic text), so
every figure is agreement with that key. The same code runs unchanged on a real, lecturer-labelled file.
"""
import json
import re
from pathlib import Path
from typing import Callable, Optional

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
PLAN_TYPES = ("syllabus", "module_manual")
RRF_K = 60   # same constant as rag/retrieval/hybrid_retriever.py (a test keeps them equal)


# ── extraction ───────────────────────────────────────────────────────────────

def normalise(line: str) -> str:
    """Compare lines without list markers, case, spacing or closing punctuation."""
    line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line or "")
    return " ".join(line.split()).rstrip(" .,;:").lower()


def load_cases(path: Optional[Path] = None, split: Optional[str] = None) -> list:
    data = json.loads(Path(path or DATASETS / "extraction" / "cases.json").read_text(encoding="utf-8"))
    return [c for c in data["cases"] if split is None or c["split"] == split]


def _prf(true_positive: int, predicted: int, actual: int) -> dict:
    precision = true_positive / predicted if predicted else None
    recall = true_positive / actual if actual else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if predicted or actual else None)
    return {"correct": true_positive, "extracted": predicted, "expected": actual, "precision": precision, "recall": recall, "f1": f1}


def extraction_metrics(cases: list, outcomes: Callable[[str, bool], list], weeks: Callable[[str], list]) -> dict:
    """`outcomes(text, is_plan_document)` and `weeks(text)` are the extractors under test.
    The schedule is only read from plan documents, as in the application."""
    totals = {"outcomes": [0, 0, 0], "weeks": [0, 0, 0]}
    errors = []
    for case in cases:
        plan = case["doc_type"] in PLAN_TYPES
        got = {normalise(line) for line in outcomes(case["text"], plan)}
        want = {normalise(line) for line in case["outcomes"]}
        got_weeks = {(n, normalise(t)) for n, t in (weeks(case["text"]) if plan else [])}
        want_weeks = {(n, normalise(t)) for n, t in case["weeks"]}
        for key, found, expected in (("outcomes", got, want), ("weeks", got_weeks, want_weeks)):
            totals[key][0] += len(found & expected); totals[key][1] += len(found); totals[key][2] += len(expected)
            if found != expected:
                errors.append({"case": case["id"], "kind": key, "wrongly_extracted": sorted(map(str, found - expected)),
                               "missed": sorted(map(str, expected - found))})
    return {"cases": len(cases), "outcomes": _prf(*totals["outcomes"]), "weeks": _prf(*totals["weeks"]), "errors": errors}


# ── retrieval ────────────────────────────────────────────────────────────────

def load_retrieval(path: Optional[Path] = None) -> dict:
    return json.loads(Path(path or DATASETS / "retrieval" / "labelled.json").read_text(encoding="utf-8"))


def retrieval_metrics(queries: list, rank: Callable[[str], list], ks=(1, 3, 5)) -> dict:
    """`rank(query)` returns passage ids, best first. Reports the share of queries with a relevant passage
    in the top k (recall@k, one relevant topic per query) and the mean reciprocal rank, overall and per language pair."""
    def summarise(rows):
        if not rows:
            return None
        out = {"queries": len(rows), "mrr": round(sum(r["rr"] for r in rows) / len(rows), 3)}
        out.update({f"recall@{k}": round(sum(1 for r in rows if r["rank"] and r["rank"] <= k) / len(rows), 3) for k in ks})
        return out
    rows = []
    for q in queries:
        ranking = rank(q["text"])
        position = next((i for i, pid in enumerate(ranking, start=1) if pid in q["relevant"]), None)
        rows.append({"id": q["id"], "pair": q["pair"], "rank": position, "rr": 1 / position if position else 0.0})
    return {"all": summarise(rows), **{pair: summarise([r for r in rows if r["pair"] == pair]) for pair in sorted({r["pair"] for r in rows})},
            "missed_in_top_5": [r["id"] for r in rows if not r["rank"] or r["rank"] > 5]}


def lexical_ranker(passages: list) -> Callable[[str], list]:
    """The offline test backend: shared words plus hash vectors (rag/local_service.py)."""
    from rag.lexical import lexical_score
    def rank(query):
        scored = [(lexical_score(query, p["text"]), p["id"]) for p in passages]
        return [pid for score, pid in sorted(scored, key=lambda s: -s[0]) if score > 0]
    return rank


def bm25_ranker(passages: list, tokenise=None) -> Callable[[str], list]:
    """Keyword-only retrieval as used in live mode (rag/retrieval/bm25_retriever.py)."""
    from rank_bm25 import BM25Okapi
    from rag.retrieval.bm25_retriever import _tokenise
    tokenise = tokenise or _tokenise
    index = BM25Okapi([tokenise(p["text"]) for p in passages])
    def rank(query):
        scores = index.get_scores(tokenise(query))
        return [passages[i]["id"] for i in sorted(range(len(passages)), key=lambda i: -scores[i]) if scores[i] > 0]
    return rank


def dense_ranker(passages: list) -> Callable[[str], list]:
    """Embedding retrieval with the configured model (downloads it on first use)."""
    from config import settings
    from rag.chunking.chunk_models import RawChunk
    from rag.embedding.bge_embedder import BGEEmbedder
    embedder = BGEEmbedder(settings.embedding_model)
    chunks = [RawChunk(text=p["text"], chunk_index=i, artifact_id="a", course_id="c", file_type="txt", artifact_type="slides")
              for i, p in enumerate(passages)]
    vectors = [e.embedding for e in embedder.embed_chunks(chunks)]
    def rank(query):
        q = embedder.embed_query(query)
        scores = [sum(a * b for a, b in zip(q, v)) for v in vectors]
        return [passages[i]["id"] for i in sorted(range(len(passages)), key=lambda i: -scores[i])]
    return rank


def hybrid_ranker(*rankers, depth: int = 20) -> Callable[[str], list]:
    """Reciprocal rank fusion with the application's constant (rag/retrieval/hybrid_retriever.py)."""
    def rank(query):
        scores = {}
        for ranker in rankers:
            for position, pid in enumerate(ranker(query)[:depth], start=1):
                scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + position)
        return sorted(scores, key=lambda pid: -scores[pid])
    return rank


def reranked(ranker, passages: list, candidates: int = 8) -> Callable[[str], list]:
    """Cross-encoder reranking of the first candidates, with the configured reranker model."""
    from config import settings
    from sentence_transformers import CrossEncoder
    model = CrossEncoder(settings.rerank_model)
    text = {p["id"]: p["text"] for p in passages}
    def rank(query):
        ids = ranker(query)[:candidates]
        if not ids:
            return []
        scores = model.predict([(query, text[i]) for i in ids])
        return [i for _, i in sorted(zip(scores, ids), key=lambda s: -s[0])]
    return rank
