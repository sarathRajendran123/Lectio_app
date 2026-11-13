"""Study evaluation: labelling sheets and metrics from lecturer labels. No database, no model.

Protocol (docs/EVALUATION.md):
  1. Before seeing any system output, each lecturer lists the alignment issues they see (issues sheet).
  2. The system's findings are exported in random order; the lecturer marks each one valid (1), not valid (0)
     or cannot judge (?), and names the stage-1 issue it corresponds to, if any.
  3. Drafts are exported without model, style or quality score; the lecturer rates them 1..5.
Nothing here produces a label. A figure whose denominator is zero is reported as None, never as a perfect score.
"""
import csv
import hashlib
import random
from collections import Counter, defaultdict
from pathlib import Path

DIMENSIONS = ("metadata_content", "content_assessment", "metadata_assessment", "content_delivery")
ISSUE_COLUMNS = ["issue_id", "dimension", "description", "where", "severity", "rater"]
FINDING_COLUMNS = ["finding_id", "dimension", "gap_type", "severity", "description", "recommendation", "valid", "matches_issue", "note"]
CRITERIA = ("relevance", "evidence_correctness", "usefulness", "cognitive_alignment")
DRAFT_COLUMNS = ["blind_id", "content_type", "content", *CRITERIA, "edit_burden", "note"]
EDIT_BURDEN = ("none", "minor", "major", "rewrite")
REVIEWED = ("approved", "rejected")


def read_csv(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path, columns, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def findings_sheet(findings: list[dict], seed: int = 0) -> list[dict]:
    """Findings in random order with empty judgement columns."""
    rows = [{**{c: f.get(c, "") for c in FINDING_COLUMNS[:6]}, "valid": "", "matches_issue": "", "note": ""} for f in findings]
    random.Random(seed).shuffle(rows)
    return rows


def blind_drafts(drafts: list[dict], seed: int = 0) -> tuple[list[dict], dict]:
    """Rating sheet without model, style, quality score or status, and the key that links it back."""
    order = list(drafts)
    random.Random(seed).shuffle(order)
    rows, key = [], {}
    for draft in order:
        blind = "D-" + hashlib.sha256(f"{seed}:{draft['id']}".encode()).hexdigest()[:10]
        rows.append({"blind_id": blind, "content_type": draft.get("content_type", ""), "content": draft.get("content", ""),
                     **{c: "" for c in CRITERIA}, "edit_burden": "", "note": ""})
        key[blind] = {k: draft.get(k) for k in ("id", "model_used", "title", "content_type", "approval_status", "quality_score", "quality_passed")}
    return rows, key


def _ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def _f1(precision, recall):
    if precision is None or recall is None:
        return None
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def detection_metrics(issues: list[dict], judgements: list[dict], abstained: tuple = ()) -> dict:
    """Precision, recall and F1 per dimension from one rater's issue list and judgements.

    precision = findings judged valid / findings judged (0 or 1)
    recall    = stage-1 issues matched by at least one valid finding / stage-1 issues
    A dimension the system could not assess is an abstention: reported, and excluded from the totals.
    """
    ids = {}
    for issue in issues:
        if issue["dimension"] not in DIMENSIONS:
            raise ValueError(f"Issue {issue['issue_id']}: unknown dimension '{issue['dimension']}'")
        if not issue["issue_id"] or issue["issue_id"] in ids:
            raise ValueError(f"Issue ids must be present and unique: '{issue['issue_id']}'")
        ids[issue["issue_id"]] = issue["dimension"]
    for row in judgements:
        if row["dimension"] not in DIMENSIONS:
            raise ValueError(f"Finding {row['finding_id']}: unknown dimension '{row['dimension']}'")
        if row["valid"] not in ("1", "0", "?", ""):
            raise ValueError(f"Finding {row['finding_id']}: 'valid' must be 1, 0, ? or empty")
        match = row.get("matches_issue", "")
        if match and ids.get(match) != row["dimension"]:
            raise ValueError(f"Finding {row['finding_id']}: matches_issue '{match}' is not an issue of the same dimension")
        if match and row["valid"] != "1":
            raise ValueError(f"Finding {row['finding_id']}: only a valid finding can match an issue")
    result = {}
    totals = Counter()
    for dimension in DIMENSIONS:
        rows = [r for r in judgements if r["dimension"] == dimension]
        listed = [i for i, d in ids.items() if d == dimension]
        valid = [r for r in rows if r["valid"] == "1"]
        judged = [r for r in rows if r["valid"] in ("1", "0")]
        found = {r["matches_issue"] for r in valid if r.get("matches_issue")}
        counts = {"findings": len(rows), "judged": len(judged), "valid": len(valid), "not_valid": len(judged) - len(valid),
                  "cannot_judge": sum(r["valid"] == "?" for r in rows), "not_judged": sum(r["valid"] == "" for r in rows),
                  "valid_not_in_issue_list": sum(not r.get("matches_issue") for r in valid),
                  "issues_listed": len(listed), "issues_found": len(found), "issues_missed": len(listed) - len(found)}
        precision, recall = _ratio(len(valid), len(judged)), _ratio(len(found), len(listed))
        result[dimension] = {**counts, "abstained": dimension in abstained, "precision": precision, "recall": recall, "f1": _f1(precision, recall)}
        if dimension not in abstained:
            totals.update({k: counts[k] for k in ("judged", "valid", "issues_listed", "issues_found")})
    precision, recall = _ratio(totals["valid"], totals["judged"]), _ratio(totals["issues_found"], totals["issues_listed"])
    result["all_assessed_dimensions"] = {**totals, "precision": precision, "recall": recall, "f1": _f1(precision, recall)}
    return result


def kappa(first: list[dict], second: list[dict]) -> dict:
    """Cohen's kappa for two raters' valid / not valid judgements on the same findings."""
    a = {r["finding_id"]: r["valid"] for r in first if r["valid"] in ("1", "0")}
    b = {r["finding_id"]: r["valid"] for r in second if r["valid"] in ("1", "0")}
    shared = sorted(set(a) & set(b))
    if not shared:
        return {"items": 0, "observed_agreement": None, "kappa": None}
    n = len(shared)
    observed = sum(a[i] == b[i] for i in shared) / n
    expected = sum((sum(a[i] == label for i in shared) / n) * (sum(b[i] == label for i in shared) / n) for label in ("1", "0"))
    # With every judgement in one category chance agreement is 1 and kappa is undefined.
    return {"items": n, "observed_agreement": round(observed, 4),
            "kappa": round((observed - expected) / (1 - expected), 4) if expected < 1 else None}


def _mean(values):
    return round(sum(values) / len(values), 3) if values else None


def draft_metrics(ratings: list[dict], key: dict) -> dict:
    """Mean ratings per criterion, overall and per model, plus decisions taken in the application."""
    groups = defaultdict(lambda: defaultdict(list))
    burden = Counter()
    rated = 0
    for row in ratings:
        entry = key.get(row["blind_id"])
        if entry is None:
            raise ValueError(f"Rating sheet row '{row['blind_id']}' is not in the key")
        scores = {}
        for criterion in CRITERIA:
            value = row.get(criterion, "")
            if value == "":
                continue
            if value not in ("1", "2", "3", "4", "5"):
                raise ValueError(f"{row['blind_id']}: {criterion} must be a whole number from 1 to 5")
            scores[criterion] = int(value)
        if row.get("edit_burden"):
            if row["edit_burden"] not in EDIT_BURDEN:
                raise ValueError(f"{row['blind_id']}: edit_burden must be one of {', '.join(EDIT_BURDEN)}")
            burden[row["edit_burden"]] += 1
        rated += bool(scores)
        for criterion, value in scores.items():
            groups["all"][criterion].append(value)
            groups[entry.get("model_used") or "unknown"][criterion].append(value)
    statuses = Counter((entry.get("approval_status") or "pending") for entry in key.values())
    reviewed = sum(statuses[s] for s in REVIEWED)
    gate = [(e.get("quality_passed"), e.get("approval_status")) for e in key.values() if e.get("quality_passed") is not None and e.get("approval_status") in REVIEWED]
    return {"drafts": len(key), "rated": rated,
            "ratings": {group: {c: {"mean": _mean(v), "n": len(v)} for c, v in sorted(criteria.items())} for group, criteria in sorted(groups.items())},
            "edit_burden": dict(burden),
            "decisions": {**{s: statuses[s] for s in ("approved", "rejected", "revised", "pending")},
                          "approved_share_of_decided": _ratio(statuses["approved"], reviewed)},
            "quality_gate": {"decided_with_gate_result": len(gate),
                             "gate_passed_and_approved": sum(p and s == "approved" for p, s in gate),
                             "gate_passed_and_rejected": sum(p and s == "rejected" for p, s in gate),
                             "gate_failed_and_approved": sum((not p) and s == "approved" for p, s in gate),
                             "gate_failed_and_rejected": sum((not p) and s == "rejected" for p, s in gate)}}


def _show(value):
    if value is None:
        return "n/a"
    return f"{value:.0%}" if isinstance(value, float) else str(value)


def render_markdown(report: dict) -> str:
    """Plain report for a thesis appendix. Says where the labels came from and what is undefined."""
    manifest = report.get("manifest", {})
    lines = ["# Evaluation report", "",
             f"Labels: {report.get('label_status', 'as supplied')}. Course: {manifest.get('course_code', 'n/a')}. "
             f"Run: {manifest.get('run_id', 'n/a')}. Mode: {manifest.get('mode', 'n/a')}. Model: {manifest.get('model', 'n/a')}.", ""]
    detection = report.get("detection")
    if detection:
        lines += ["## Findings", "", "| Dimension | Judged | Valid | Precision | Issues listed | Found | Recall | F1 |", "|---|---|---|---|---|---|---|---|"]
        for name in (*DIMENSIONS, "all_assessed_dimensions"):
            d = detection[name]
            label = name.replace("_", " ") + (" (not assessed by the system)" if d.get("abstained") else "")
            lines.append(f"| {label} | {d['judged']} | {d['valid']} | {_show(d['precision'])} | {d['issues_listed']} | {d['issues_found']} | {_show(d['recall'])} | {_show(d['f1'])} |")
        lines += ["", "n/a means the figure is undefined (nothing judged, or no issue listed). "
                      "Recall is measured against the issues the lecturer listed before seeing the findings.", ""]
    agreement = report.get("agreement")
    if agreement:
        lines += ["## Agreement between two raters", "",
                  f"Findings judged by both: {agreement['items']}. Observed agreement: {_show(agreement['observed_agreement'])}. "
                  f"Cohen's kappa: {agreement['kappa'] if agreement['kappa'] is not None else 'n/a'}.", ""]
    drafts = report.get("drafts")
    if drafts:
        lines += ["## Drafts", "", f"Drafts: {drafts['drafts']}; rated: {drafts['rated']}.", "",
                  "| Group | " + " | ".join(c.replace("_", " ") for c in CRITERIA) + " |", "|---|" + "---|" * len(CRITERIA)]
        for group, criteria in drafts["ratings"].items():
            cells = [f"{criteria[c]['mean']} (n={criteria[c]['n']})" if c in criteria else "n/a" for c in CRITERIA]
            lines.append(f"| {group} | " + " | ".join(cells) + " |")
        decisions = drafts["decisions"]
        lines += ["", f"Decisions in the application: {decisions['approved']} approved, {decisions['rejected']} rejected, "
                      f"{decisions['revised']} revised and awaiting a decision, {decisions['pending']} pending. "
                      f"Approved share of decided drafts: {_show(decisions['approved_share_of_decided'])}.", ""]
    return "\n".join(lines)
