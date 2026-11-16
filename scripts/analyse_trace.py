"""Analyse the interaction log of a course: goal propagation, delegation, traceability, quality loop, lecturer decisions.

    python scripts/analyse_trace.py --course <course id> --out study/trace

Reads the course log and its latest runs (at most 20) from a running API and writes analysis.json and analysis.md.
Needs LECTIO_API_URL (default http://127.0.0.1:8000) and LECTIO_ACCESS_TOKEN of the course owner.
The indicators are descriptive (knowledge/trace_analysis.py); an observation is a place to look, not a verdict.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from knowledge import trace_analysis   # noqa: E402  (no database or settings import)


def analyse(course_id: str, out: Path, client=None) -> dict:
    import httpx
    client = client or httpx.Client(base_url=os.environ.get("LECTIO_API_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1",
                                    headers={"Authorization": "Bearer " + os.environ["LECTIO_ACCESS_TOKEN"]}, timeout=120)
    response = client.get(f"/courses/{course_id}/trace/analysis")
    response.raise_for_status()
    report = response.json()
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "analysis.md").write_text(trace_analysis.render_markdown(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(trace_analysis.render_markdown(analyse(args.course, args.out)))


if __name__ == "__main__":
    main()
