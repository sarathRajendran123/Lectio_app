"""Measure the Bloom classifier against datasets/bloom/labelled.csv (or another file in the same format).

    python scripts/evaluate_bloom.py                  # rules only, every split
    python scripts/evaluate_bloom.py --split test
    python scripts/evaluate_bloom.py --llm            # rules, then the model for items the rules leave open
    python scripts/evaluate_bloom.py --llm --ambiguous   # also re-ask the model for ambiguous verbs

--llm needs OPENROUTER_API_KEY and makes model calls (one per 20 open items). The labels in the bundled
file are provisional (see datasets/bloom/README.md): results are agreement with that key.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SECRET_KEY", "evaluation-only-secret-more-than-thirty-two-characters")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--split", default=None, help="dev | test | challenge (default: all)")
    parser.add_argument("--llm", action="store_true", help="model-assisted: ask the model for items the rules cannot classify")
    parser.add_argument("--ambiguous", action="store_true", help="with --llm: also ask the model about ambiguous verbs")
    parser.add_argument("--errors", action="store_true", help="list the misclassified items")
    args = parser.parse_args()

    from knowledge import bloom_eval
    from knowledge.bloom_classifier import classify_hybrid, classify_text
    rows = bloom_eval.load(args.file, args.split)
    if args.llm:
        levels = {}
        for start in range(0, len(rows), 20):
            batch = rows[start:start + 20]
            for row, detail in zip(batch, classify_hybrid([r["text"] for r in batch], include_ambiguous=args.ambiguous)):
                levels[row["text"]] = detail["level"]
        classify = levels.get
    else:
        classify = lambda text: classify_text(text)[0]
    report = {"classifier": "rules + model" if args.llm else "rules", "split": args.split or "all", "file": str(args.file or bloom_eval.DEFAULT_SET),
              "label_status": "provisional key, not lecturer-reviewed" if args.file is None else "as supplied",
              **{name: {k: v for k, v in result.items() if k != "errors" or (args.errors and name == "all")}
                 for name, result in bloom_eval.by_language(rows, classify).items()}}
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
