"""Measure a Bloom classifier against a labelled set (datasets/bloom/labelled.csv).

Reports accuracy, coverage (share of items that got any level), and precision / recall per level.
An unclassified item counts as wrong for accuracy and recall, and is not a prediction for precision.
"""
import csv
from pathlib import Path
from typing import Callable, Optional

from knowledge.bloom_classifier import LEVEL_ORDER

DEFAULT_SET = Path(__file__).resolve().parents[2] / "datasets" / "bloom" / "labelled.csv"


def load(path: Optional[Path] = None, split: Optional[str] = None, language: Optional[str] = None) -> list:
    with open(path or DEFAULT_SET, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["level"] not in LEVEL_ORDER:
            raise ValueError(f"{row['id']}: unknown level {row['level']!r}")
    return [r for r in rows if (split is None or r["split"] == split) and (language is None or r["language"] == language)]


def evaluate(rows: list, classify: Callable[[str], Optional[str]]) -> dict:
    """`classify(text)` returns a level name or None."""
    predicted = [(row, classify(row["text"])) for row in rows]
    correct = sum(1 for row, got in predicted if got == row["level"])
    per_level = {}
    for level in LEVEL_ORDER:
        true_positive = sum(1 for row, got in predicted if got == level and row["level"] == level)
        said = sum(1 for _, got in predicted if got == level)
        actual = sum(1 for row, _ in predicted if row["level"] == level)
        precision = true_positive / said if said else None
        recall = true_positive / actual if actual else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if actual else None)
        per_level[level] = {"items": actual, "precision": precision, "recall": recall, "f1": f1}
    return {"items": len(rows), "accuracy": correct / len(rows) if rows else None,
            "coverage": sum(1 for _, got in predicted if got) / len(rows) if rows else None,
            "per_level": per_level,
            "errors": [{"id": row["id"], "expected": row["level"], "got": got, "text": row["text"]} for row, got in predicted if got != row["level"]]}


def by_language(rows: list, classify: Callable[[str], Optional[str]]) -> dict:
    return {"all": evaluate(rows, classify), **{lang: evaluate([r for r in rows if r["language"] == lang], classify)
                                                for lang in sorted({r["language"] for r in rows})}}
