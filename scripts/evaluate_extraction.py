"""Measure outcome and schedule extraction against datasets/extraction/cases.json (or a file in the same format).

    python scripts/evaluate_extraction.py
    python scripts/evaluate_extraction.py --split test --file my_cases.json

No database or model is needed. The bundled key is provisional (see datasets/extraction/README.md).
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
    parser.add_argument("--split", default=None, help="dev | test (default: all)")
    args = parser.parse_args()
    from knowledge import quality_eval
    from knowledge.outline_rules import outcome_lines, schedule_entries
    result = quality_eval.extraction_metrics(quality_eval.load_cases(args.file, args.split), outcome_lines, schedule_entries)
    print(json.dumps({"split": args.split or "all", "label_status": "provisional key, not lecturer-reviewed" if args.file is None else "as supplied",
                      **result}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
