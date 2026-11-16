"""Experiment specs, per-run measurements and the comparison between conditions. No database, no model.

A condition is one configuration of the system (settings, with or without course intent, rules or a document).
Every condition is run on the same course files; the first condition is the baseline the others are compared with.
What is measured is what the system did (scores, findings, drafts, calls, time). Whether a finding is right is a
separate question answered by lecturer labels (knowledge/study_eval.py).
"""
import hashlib
import re
from collections import Counter

# Settings a spec may change. Secrets, the database and storage paths are never taken from a spec.
ALLOWED_ENV = {
    "QUALITY_THRESHOLD", "QUALITY_MAX_RETRIES", "GENERATION_AUTO_ENABLED", "GENERATION_MAX_ITEMS_PER_RUN", "RETRIEVAL_BACKEND",
    "BLOOM_LLM_FALLBACK", "BLOOM_LLM_MAX_ITEMS", "OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODEL", "LLM_REASONING_EFFORT",
    "LLM_MAX_TOKENS_AUDIT", "LLM_MAX_TOKENS_GENERATION", "DELIVERY_POINT_TERM_COVERAGE", "DELIVERY_POINT_SIMILARITY",
    "DELIVERY_COVERED_SHARE", "DELIVERY_UNPLANNED_TERM_OVERLAP", "DELIVERY_UNPLANNED_SIMILARITY", "DELIVERY_MIN_SEGMENT_TERMS",
}
NOT_ASSESSED = ("needs_review", "failed")


def validate_spec(spec: dict) -> dict:
    if not isinstance(spec.get("dataset"), str) or not spec["dataset"]:
        raise ValueError("spec.dataset must name a folder with course files")
    repeats = spec.get("repeats", 1)
    if not isinstance(repeats, int) or not 1 <= repeats <= 10:
        raise ValueError("spec.repeats must be a whole number from 1 to 10")
    conditions = spec.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("spec.conditions must list at least one condition")
    names = set()
    for condition in conditions:
        name = condition.get("name", "")
        if not re.fullmatch(r"[a-z0-9_]{1,40}", name) or name in names:
            raise ValueError(f"condition name '{name}' must be unique, lower case letters, digits and underscores")
        names.add(name)
        unknown = set(condition) - {"name", "description", "env", "intent", "constraints", "exclude"}
        if unknown:
            raise ValueError(f"condition {name}: unknown field(s) {sorted(unknown)}")
        env = condition.get("env", {})
        refused = sorted(k for k in env if k.upper() not in ALLOWED_ENV)
        if refused:
            raise ValueError(f"condition {name}: setting(s) {refused} may not be changed by an experiment")
        if not all(isinstance(v, str) for v in env.values()):
            raise ValueError(f"condition {name}: setting values must be text")
        if condition.get("intent") is not None and not isinstance(condition["intent"].get("goals"), str):
            raise ValueError(f"condition {name}: intent needs goals")
        for field in ("constraints", "exclude"):
            if not all(isinstance(x, str) and x for x in condition.get(field, [])):
                raise ValueError(f"condition {name}: {field} must be a list of text")
    return {**spec, "repeats": repeats}


def finding_key(dimension: str, gap_type: str, description: str) -> str:
    """Identity of a finding across runs: dimension, type and wording. Run-specific ids, decimal scores, percentages
    and spacing are ignored; whole numbers stay, so "EXT-1" and "EXT-2" remain different findings."""
    text = re.sub(r"\b(?=[a-f]*\d)[0-9a-f]{8}(-[0-9a-f]{4}){0,3}(-[0-9a-f]{12})?\b", "#", description.lower())   # "exam.txt · source 3fa9c1d2"
    text = re.sub(r"\d+\.\d+%?|\d+%", "#", text)
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(f"{dimension}|{gap_type}|{text}".encode()).hexdigest()[:16]


def _mean(values, digits=4):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), digits) if values else None


def collect(get, course_id: str, run_id: str) -> dict:
    """Measurements of one finished audit. `get(path, **params)` returns decoded JSON from the API."""
    run = get(f"/runs/{run_id}")
    reports = [r for r in get(f"/courses/{course_id}/reports") if r["run_id"] == run_id]
    dimensions, findings = {}, []
    for report in reports:
        assessed = report["status"] not in NOT_ASSESSED
        dimensions[report["report_type"]] = {"status": report["status"], "score": report["overall_score"] if assessed else None,
                                             "findings": report["gap_count"], "reason": report.get("reason")}
        for gap in get(f"/reports/{report['id']}")["gaps"]:
            findings.append({"key": finding_key(report["report_type"], gap["gap_type"], gap["description"]), "dimension": report["report_type"],
                             "gap_type": gap["gap_type"], "severity": gap["severity"]})
    structure = get(f"/courses/{course_id}/structure")
    objectives = [o for m in structure["modules"] for o in m["objectives"]]
    drafts = [d for status in ("pending", "revised", "approved", "rejected") for d in get("/approvals", course_id=course_id, status=status)]
    reviews = [d["quality"] for d in drafts if d.get("quality")]
    trace = get(f"/runs/{run_id}/trace")
    events = Counter(e["event_type"] for e in trace["events"])
    calls = [e["payload"] for e in trace["events"] if e["event_type"] == "model_call"]
    return {
        "run_id": run_id, "status": run["status"], "tokens": run.get("total_tokens") or 0, "error": run.get("error_message"),
        "dimensions": dimensions, "findings": sorted(findings, key=lambda f: f["key"]),
        "finding_types": dict(Counter(f["gap_type"] for f in findings)), "severities": dict(Counter(f["severity"] for f in findings)),
        "objectives": {"count": len(objectives), "derived": sum(bool(o.get("is_generated")) for o in objectives),
                       "bloom": dict(Counter(o.get("bloom_level") or "unclassified" for o in objectives))},
        "drafts": {"count": len(drafts), "reviewed_by_gate": len(reviews), "gate_passed": sum(bool(r["passed"]) for r in reviews),
                   "mean_quality": _mean([r["score"] for r in reviews]), "mean_attempts": _mean([r["attempts"] for r in reviews], 2),
                   "models": dict(Counter(d.get("model_used") or "unknown" for d in drafts))},
        "trace": {"valid": trace["integrity"]["valid"], "events": dict(events), "model_calls": len(calls),
                  "model_calls_cached": sum(bool(c.get("cached")) for c in calls),
                  "model_calls_failed": sum(c.get("outcome") != "ok" for c in calls),
                  "tokens_in_trace": sum(int(c.get("tokens_total") or 0) for c in calls)},
    }


def _keys(run):
    return {f["key"] for f in run["findings"]}


def summarise(name: str, runs: list[dict]) -> dict:
    """One condition over its repeats."""
    finished = [r for r in runs if r.get("dimensions")]
    sets = [_keys(r) for r in finished]
    always = set.intersection(*sets) if sets else set()
    ever = set.union(*sets) if sets else set()
    dimensions = sorted({d for r in finished for d in r["dimensions"]})
    return {
        "condition": name, "runs": len(runs), "finished": len(finished), "statuses": dict(Counter(r["status"] for r in runs)),
        "scores": {d: _mean([r["dimensions"].get(d, {}).get("score") for r in finished]) for d in dimensions},
        "not_assessed": {d: sum(r["dimensions"].get(d, {}).get("score") is None for r in finished) for d in dimensions},
        "findings_mean": _mean([len(r["findings"]) for r in finished], 2), "findings_in_every_run": len(always), "findings_in_any_run": len(ever),
        "stable": (len(always) == len(ever)) if len(sets) > 1 else None,     # None: one run cannot show stability
        "drafts_mean": _mean([r["drafts"]["count"] for r in finished], 2),
        "gate_pass_share": _mean([r["drafts"]["gate_passed"] / r["drafts"]["reviewed_by_gate"] for r in finished if r["drafts"]["reviewed_by_gate"]]),
        "mean_attempts": _mean([r["drafts"]["mean_attempts"] for r in finished], 2),
        "model_calls_mean": _mean([r["trace"]["model_calls"] for r in finished], 2), "tokens_mean": _mean([r["tokens"] for r in finished], 1),
        "seconds_mean": _mean([r.get("seconds") for r in finished], 1), "trace_valid": all(r["trace"]["valid"] for r in finished) if finished else None,
        "_always": always, "_types": {f["key"]: f"{f['dimension']}: {f['gap_type']}" for r in finished for f in r["findings"]},
    }


def compare(results: dict) -> dict:
    """results: {condition name: [run measurements]} in spec order. The first condition is the baseline."""
    summaries = [summarise(name, runs) for name, runs in results.items()]
    base = summaries[0]
    for summary in summaries:
        own, reference = summary["_always"], base["_always"]
        union = own | reference
        types = {**base["_types"], **summary["_types"]}
        summary["against_baseline"] = None if summary is base else {
            "same_findings": len(own & reference), "only_in_baseline": sorted(types[k] for k in reference - own),
            "only_here": sorted(types[k] for k in own - reference), "overlap": round(len(own & reference) / len(union), 4) if union else None,
            "score_change": {d: (round(summary["scores"][d] - base["scores"][d], 4)
                                 if summary["scores"].get(d) is not None and base["scores"].get(d) is not None else None)
                             for d in sorted(set(summary["scores"]) | set(base["scores"]))}}
    for summary in summaries:
        del summary["_always"], summary["_types"]
    return {"baseline": base["condition"], "conditions": summaries}


def _show(value, percent=False):
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return f"{value:.0%}" if percent else str(value)


def render_markdown(report: dict) -> str:
    comparison, spec = report["comparison"], report["spec"]
    lines = ["# Experiment report", "",
             f"Course files: `{spec['dataset']}`. Mode: {report['mode']}. Runs per condition: {spec['repeats']}. Started: {report['started_at']}.", "",
             "This report describes what the system did under each configuration. It does not say whether the findings are correct; "
             "that needs lecturer labels (`scripts/study.py`).", ""]
    if report["mode"] == "local_test":
        lines += ["**Test mode: no language model was called.** Drafts are fixed templates and findings come from the rule-based checks only, "
                  "so differences between conditions show the effect on those rules, not on model behaviour.", ""]
    lines += ["## Conditions", "", "| Condition | What is changed |", "|---|---|"]
    lines += [f"| {c['name']} | {c.get('description') or 'baseline'} |" for c in spec["conditions"]]
    dimensions = sorted({d for c in comparison["conditions"] for d in c["scores"]})
    lines += ["", "## Scores per dimension (mean over runs; n/a = the system could not assess it)", "",
              "| Condition | " + " | ".join(d.replace("_", " ") for d in dimensions) + " |", "|---|" + "---|" * len(dimensions)]
    lines += [f"| {c['condition']} | " + " | ".join(_show(c["scores"].get(d), True) for d in dimensions) + " |" for c in comparison["conditions"]]
    lines += ["", "## Findings, drafts and cost", "",
              "| Condition | Runs finished | Findings (mean) | Same findings in every run | Drafts (mean) | Gate passed | Attempts per draft | Model calls | Tokens | Seconds |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for c in comparison["conditions"]:
        lines.append(f"| {c['condition']} | {c['finished']} of {c['runs']} | {_show(c['findings_mean'])} | {_show(c['stable'])} | {_show(c['drafts_mean'])} | "
                     f"{_show(c['gate_pass_share'], True)} | {_show(c['mean_attempts'])} | {_show(c['model_calls_mean'])} | {_show(c['tokens_mean'])} | {_show(c['seconds_mean'])} |")
    lines += ["", f"## Difference from the baseline ({comparison['baseline']})", ""]
    for c in comparison["conditions"]:
        diff = c["against_baseline"]
        if diff is None:
            continue
        changes = ", ".join(f"{d.replace('_', ' ')} {v:+.0%}" for d, v in diff["score_change"].items() if v) or "none"
        lines += [f"### {c['condition']}", "", f"Findings shared with the baseline: {diff['same_findings']} (overlap {_show(diff['overlap'], True)}). Score changes: {changes}.", ""]
        for title, items in (("Only in the baseline", diff["only_in_baseline"]), ("Only in this condition", diff["only_here"])):
            if items:
                counted = Counter(items)
                lines += [f"{title}: " + "; ".join(f"{k} ({n})" if n > 1 else k for k, n in sorted(counted.items())) + ".", ""]
    failed = [(c["condition"], c["statuses"]) for c in comparison["conditions"] if c["finished"] < c["runs"]]
    if failed:
        lines += ["## Runs that did not finish", ""] + [f"- {name}: {statuses}" for name, statuses in failed] + [""]
    return "\n".join(lines)
