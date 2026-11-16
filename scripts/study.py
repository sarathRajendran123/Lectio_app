"""Labelling sheets and metrics for the lecturer study (protocol: docs/EVALUATION.md).

    python scripts/study.py issues-template --out study/issues.csv
        Empty sheet for the lecturer's own list of alignment issues. Fill it BEFORE exporting findings.

    python scripts/study.py export --course <course id> --out study/
        Reads the latest audit of a course from a running API and writes:
          findings.csv      the system's findings in random order, with empty judgement columns
          drafts_blind.csv  the drafts without model, style, quality score or status
          drafts_key.json   links the blind ids back (keep it away from the raters)
          manifest.json     course, run, mode, model, dimensions the system could not assess
        Needs LECTIO_API_URL (default http://127.0.0.1:8000) and LECTIO_ACCESS_TOKEN of the course owner.

    python scripts/study.py score --issues issues.csv --findings rater1.csv [rater2.csv]
                                  [--drafts ratings.csv --key drafts_key.json] [--manifest manifest.json] --out study/report
        Writes report.json and report.md. Metrics use the first findings file; a second one adds rater agreement.

The script never creates a label. Sheets that are not filled in give "n/a", not a score.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from knowledge import study_eval as study   # noqa: E402  (no database or settings import)

STATUSES = ("pending", "revised", "approved", "rejected")


def export(course_id: str, out: Path, seed: int, client=None) -> dict:
    import httpx
    client = client or httpx.Client(base_url=os.environ.get("LECTIO_API_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1",
                                    headers={"Authorization": "Bearer " + os.environ["LECTIO_ACCESS_TOKEN"]}, timeout=120)

    def get(path, **params):
        response = client.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    course = get(f"/courses/{course_id}")
    reports = get(f"/courses/{course_id}/reports")
    if not reports:
        raise SystemExit("This course has no audit yet. Run an audit first.")
    run_id = reports[0]["run_id"]                                  # newest first
    reports = [r for r in reports if r["run_id"] == run_id]
    findings, abstained = [], []
    for report in reports:
        if report["status"] in ("needs_review", "failed"):
            abstained.append(report["report_type"])
        for gap in get(f"/reports/{report['id']}")["gaps"]:
            findings.append({"finding_id": gap["id"], "dimension": report["report_type"], "gap_type": gap["gap_type"],
                             "severity": gap["severity"], "description": gap["description"], "recommendation": gap["recommendation"] or ""})
    drafts = []
    for status in STATUSES:
        for item in get("/approvals", course_id=course_id, status=status):
            quality = item.get("quality") or {}
            drafts.append({**item, "quality_score": quality.get("score"), "quality_passed": quality.get("passed")})
    system = get("/system/status")
    run = get(f"/runs/{run_id}")
    manifest = {"course_id": course_id, "course_code": course.get("code"), "run_id": run_id, "run_status": run.get("status"),
                "mode": system.get("mode"), "model": system.get("model"), "abstained_dimensions": sorted(abstained),
                "findings": len(findings), "drafts": len(drafts), "seed": seed,
                "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    rows, key = study.blind_drafts(drafts, seed)
    out.mkdir(parents=True, exist_ok=True)
    study.write_csv(out / "findings.csv", study.FINDING_COLUMNS, study.findings_sheet(findings, seed))
    study.write_csv(out / "drafts_blind.csv", study.DRAFT_COLUMNS, rows)
    (out / "drafts_key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def score(issues: Path, findings: list[Path], drafts: Path | None, key: Path | None, manifest: Path | None, out: Path, label_status: str) -> dict:
    manifest_data = json.loads(manifest.read_text(encoding="utf-8")) if manifest else {}
    first = study.read_csv(findings[0])
    report = {"label_status": label_status, "manifest": manifest_data, "rater_files": [f.name for f in findings],
              "detection": study.detection_metrics(study.read_csv(issues), first, tuple(manifest_data.get("abstained_dimensions", ())))}
    if len(findings) > 1:
        report["agreement"] = study.kappa(first, study.read_csv(findings[1]))
    if drafts and key:
        report["drafts"] = study.draft_metrics(study.read_csv(drafts), json.loads(key.read_text(encoding="utf-8")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    out.with_suffix(".md").write_text(study.render_markdown(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("issues-template")
    template.add_argument("--out", type=Path, required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--course", required=True)
    exporter.add_argument("--out", type=Path, required=True)
    exporter.add_argument("--seed", type=int, default=0)
    scorer = commands.add_parser("score")
    scorer.add_argument("--issues", type=Path, required=True)
    scorer.add_argument("--findings", type=Path, nargs="+", required=True)
    scorer.add_argument("--drafts", type=Path)
    scorer.add_argument("--key", type=Path)
    scorer.add_argument("--manifest", type=Path)
    scorer.add_argument("--out", type=Path, required=True)
    scorer.add_argument("--label-status", default="as supplied; state who labelled and when")
    args = parser.parse_args(argv)
    if args.command == "issues-template":
        if args.out.exists():
            raise SystemExit(f"{args.out} exists; not overwritten.")
        study.write_csv(args.out, study.ISSUE_COLUMNS, [])
        print(f"Wrote {args.out}. Dimensions: {', '.join(study.DIMENSIONS)}.")
    elif args.command == "export":
        print(json.dumps(export(args.course, args.out, args.seed), indent=2))
    else:
        report = score(args.issues, args.findings, args.drafts, args.key, args.manifest, args.out, args.label_status)
        print(study.render_markdown(report))


if __name__ == "__main__":
    main()
