"""Compare retrieval methods on datasets/retrieval/labelled.json (or a file in the same format).

    python scripts/evaluate_retrieval.py              # keyword methods only (no model needed)
    python scripts/evaluate_retrieval.py --neural     # adds embeddings, fusion and reranking (downloads the models once)

Reports recall@1/3/5 and mean reciprocal rank, overall and per language pair (en-en, de-de, de-en, en-de).
The bundled key is provisional (see datasets/retrieval/README.md). The passages are ranked in memory with the
application's tokeniser, embedding model, fusion constant and reranker model; the SQL vector store is not used.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SECRET_KEY", "evaluation-only-secret-more-than-thirty-two-characters")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--neural", action="store_true", help="also run the embedding model, fusion and the reranker")
    parser.add_argument("--candidates", type=int, default=20, help="how many fused results the reranker sees")
    args = parser.parse_args()
    from config import settings
    from knowledge import quality_eval as q
    data = q.load_retrieval(args.file)
    passages, queries = data["passages"], data["queries"]
    systems = {"keyword (bm25)": q.bm25_ranker(passages), "offline test backend (shared words + hash vectors)": q.lexical_ranker(passages)}
    if args.neural:
        dense = q.dense_ranker(passages)
        hybrid = q.hybrid_ranker(dense, systems["keyword (bm25)"])
        systems.update({f"embeddings ({settings.embedding_model})": dense, "hybrid (embeddings + bm25, rank fusion)": hybrid,
                        f"hybrid + reranker ({settings.rerank_model}, top {args.candidates})": q.reranked(hybrid, passages, args.candidates)})
    report = {"passages": len(passages), "queries": len(queries),
              "label_status": "provisional key, not lecturer-reviewed" if args.file is None else "as supplied", "systems": {}}
    for name, rank in systems.items():
        started = time.time()
        report["systems"][name] = {**q.retrieval_metrics(queries, rank), "seconds_for_all_queries": round(time.time() - started, 2)}
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
