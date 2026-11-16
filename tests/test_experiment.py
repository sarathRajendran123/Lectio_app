"""Phase 3, items 12 and 13: experiment specs, measurements, comparison and report. Measurements in the unit tests are made up."""
import json
import sys
from pathlib import Path

import pytest

from knowledge import experiment

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_experiment   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _run(findings, scores=None, drafts=2, passed=2, tokens=0, seconds=10.0, status="completed"):
    scores = scores or {"metadata_content": .7, "content_delivery": .6}
    return {"status": status, "tokens": tokens, "seconds": seconds,
            "dimensions": {d: {"status": "warning" if s is not None else "needs_review", "score": s, "findings": 0} for d, s in scores.items()},
            "findings": [{"key": experiment.finding_key(d, t, text), "dimension": d, "gap_type": t, "severity": "warning"} for d, t, text in findings],
            "drafts": {"count": drafts, "reviewed_by_gate": drafts, "gate_passed": passed, "mean_quality": .8, "mean_attempts": 1.0},
            "trace": {"valid": True, "model_calls": 0}}


A = ("metadata_content", "clo_not_covered", "Objective EXT-1 is not covered.")
B = ("metadata_content", "clo_not_covered", "Objective EXT-2 is not covered.")
C = ("content_delivery", "delivery_not_covered", "Section 'Heaps' was not delivered.")


# ── spec ─────────────────────────────────────────────────────────────────────

def test_the_bundled_spec_is_valid_and_starts_with_a_baseline():
    spec = experiment.validate_spec(json.loads((ROOT / "experiments" / "ablation_test_mode.json").read_text(encoding="utf-8")))
    assert spec["conditions"][0]["name"] == "baseline" and not spec["conditions"][0].get("env")
    assert (ROOT / spec["dataset"]).is_dir()


@pytest.mark.parametrize("change", [
    {"dataset": ""}, {"repeats": 0}, {"repeats": 11}, {"conditions": []},
    {"conditions": [{"name": "Base Line"}]},
    {"conditions": [{"name": "a"}, {"name": "a"}]},
    {"conditions": [{"name": "a", "surprise": 1}]},
    {"conditions": [{"name": "a", "env": {"QUALITY_MAX_RETRIES": 0}}]},                    # values are text, as in the environment
    {"conditions": [{"name": "a", "intent": {"cognitive_levels": ["apply"]}}]},
    {"conditions": [{"name": "a", "exclude": [""]}]},
])
def test_a_malformed_spec_is_refused(change):
    with pytest.raises(ValueError):
        experiment.validate_spec({"dataset": "datasets/en_algorithms", "conditions": [{"name": "baseline"}], **change})


@pytest.mark.parametrize("setting", ["SECRET_KEY", "DATABASE_URL", "OPENROUTER_API_KEY", "ADMIN_PASSWORD", "ARTIFACT_STORAGE_PATH",
                                     "RUNTIME_MODE", "TRACE_ENABLED", "openrouter_api_key"])
def test_an_experiment_cannot_change_secrets_storage_mode_or_the_trace(setting):
    with pytest.raises(ValueError, match="may not be changed"):
        experiment.validate_spec({"dataset": "d", "conditions": [{"name": "a", "env": {setting: "x"}}]})


# ── identity of a finding across runs ────────────────────────────────────────

def test_the_same_finding_is_recognised_in_another_run_despite_new_ids_and_numbers():
    key = experiment.finding_key
    first = key("content_assessment", "assessment_weak_support", "Assessment 'exam.txt · source 3fa9c1d2' has weak support (score 0.31).")
    again = key("content_assessment", "assessment_weak_support", "Assessment  'exam.txt · source 77b0e4aa' has weak support (score 0.29).")
    assert first == again
    assert first != key("content_assessment", "assessment_weak_support", "Assessment 'klausur.txt · source 3fa9c1d2' has weak support (score 0.31).")
    assert first != key("metadata_assessment", "assessment_weak_support", "Assessment 'exam.txt · source 3fa9c1d2' has weak support (score 0.31).")
    assert key("metadata_content", "clo_not_covered", "Lernziel EXT-1 (erklären) ist nicht abgedeckt.") != \
           key("metadata_content", "clo_not_covered", "Lernziel EXT-1 (anwenden) ist nicht abgedeckt.")


# ── comparison ───────────────────────────────────────────────────────────────

def test_comparison_matches_a_hand_computed_example():
    results = {"baseline": [_run([A, B, C], tokens=100, seconds=10), _run([A, B, C], tokens=300, seconds=20)],
               "variant": [_run([A, C], {"metadata_content": .5, "content_delivery": None}, drafts=4, passed=1),
                           _run([A], {"metadata_content": .7, "content_delivery": None}, drafts=0, passed=0)]}
    comparison = experiment.compare(results)
    base, variant = comparison["conditions"]
    assert comparison["baseline"] == "baseline" and base["against_baseline"] is None
    assert (base["findings_mean"], base["stable"], base["tokens_mean"], base["seconds_mean"], base["gate_pass_share"]) == (3.0, True, 200.0, 15.0, 1.0)
    assert (variant["findings_mean"], variant["findings_in_every_run"], variant["findings_in_any_run"], variant["stable"]) == (1.5, 1, 2, False)
    assert variant["scores"] == {"content_delivery": None, "metadata_content": .6} and variant["not_assessed"]["content_delivery"] == 2
    assert variant["gate_pass_share"] == .25 and variant["drafts_mean"] == 2.0          # the run without drafts has no share to average
    diff = variant["against_baseline"]
    assert diff["same_findings"] == 1 and diff["overlap"] == round(1 / 3, 4) and diff["only_here"] == []
    assert diff["only_in_baseline"] == ["content_delivery: delivery_not_covered", "metadata_content: clo_not_covered"]
    assert diff["score_change"] == {"content_delivery": None, "metadata_content": -.1}  # no change is invented for an unassessed dimension


def test_one_run_cannot_show_stability_and_a_failed_run_is_counted_not_hidden():
    comparison = experiment.compare({"baseline": [_run([A])], "broken": [{"status": "runner_error", "error": "x"}, _run([A])]})
    base, broken = comparison["conditions"]
    assert base["stable"] is None
    assert (broken["runs"], broken["finished"], broken["statuses"]) == (2, 1, {"runner_error": 1, "completed": 1})
    nothing = experiment.compare({"baseline": [{"status": "runner_error", "error": "x"}]})["conditions"][0]
    assert nothing["finished"] == 0 and nothing["findings_mean"] is None and nothing["trace_valid"] is None and nothing["scores"] == {}


def test_the_report_states_the_mode_and_does_not_claim_correctness():
    spec = {"dataset": "datasets/en_algorithms", "repeats": 2, "conditions": [{"name": "baseline"}, {"name": "variant", "description": "exam left out"}]}
    results = {"baseline": [_run([A, B]), _run([A, B])], "variant": [_run([A], {"metadata_content": None, "content_delivery": .6}), {"status": "failed", "error": "x"}]}
    report = {"spec": spec, "mode": "local_test", "started_at": "2026-01-01T00:00:00+00:00", "comparison": experiment.compare(results)}
    text = experiment.render_markdown(report)
    assert "no language model was called" in text and "does not say whether the findings are correct" in text
    assert "| variant | exam left out |" in text and "| variant | n/a | 60% |" not in text and "| variant | 60% | n/a |" in text
    assert "1 of 2" in text and "Runs that did not finish" in text and "Only in the baseline: metadata_content: clo_not_covered." in text
    live = experiment.render_markdown({**report, "mode": "live"})
    assert "no language model was called" not in live


# ── the real thing: isolated servers, test mode ──────────────────────────────

def test_two_conditions_run_on_isolated_servers_and_identical_runs_give_identical_findings(tmp_path):
    spec = {"dataset": "datasets/en_algorithms", "repeats": 2, "conditions": [
        {"name": "baseline"}, {"name": "no_transcript", "description": "transcript left out", "exclude": [".vtt"]}]}
    lines = []
    report = run_experiment.run(spec, tmp_path, echo=lines.append)
    base, variant = report["comparison"]["conditions"]
    assert base["finished"] == 2 and variant["finished"] == 2, report["runs"]
    assert base["stable"] is True and variant["stable"] is True                         # test mode is deterministic
    assert base["trace_valid"] is True and base["model_calls_mean"] == 0 and base["tokens_mean"] == 0
    runs = report["runs"]
    assert runs["baseline"][0]["mode"] == "local_test" and runs["baseline"][0]["documents"]["lecture_transcript.vtt"] == "done"
    assert runs["no_transcript"][0]["documents"]["lecture_transcript.vtt"] == "left out"
    assert runs["baseline"][0]["run_id"] != runs["baseline"][1]["run_id"]
    types = lambda run: {f["gap_type"] for f in run["findings"]}
    assert any(t.startswith("delivery_") for t in types(runs["baseline"][0]))           # the transcript check ran
    assert not any(t.startswith("delivery_not_covered") for t in types(runs["no_transcript"][0]))
    assert variant["against_baseline"]["only_in_baseline"]
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["comparison"] == report["comparison"] and "password" not in json.dumps(saved).lower()
    assert "no_transcript" in (tmp_path / "report.md").read_text(encoding="utf-8")


# ── load test statistics ─────────────────────────────────────────────────────

def test_load_statistics_match_a_hand_computed_example_and_errors_are_not_counted_as_fast_answers():
    import load_test
    assert load_test.percentile([], .95) is None and load_test.percentile([7], .95) == 7
    assert load_test.percentile(list(range(1, 101)), .5) == 50 and load_test.percentile(list(range(1, 101)), .95) == 95
    samples = [("a", 200, 10.0), ("a", 200, 30.0), ("a", 500, 1.0), ("a", None, 2.0), ("b", 404, 5.0), ("b", 201, 20.0)]
    result = load_test.summarise(samples, 2.0)
    assert result["a"] == {"requests": 4, "ok": 2, "client_errors": 0, "server_errors": 1, "transport_errors": 1, "p50_ms": 10.0, "p95_ms": 30.0, "max_ms": 30.0}
    assert result["b"]["client_errors"] == 1 and result["b"]["p50_ms"] == 20.0
    assert result["all"]["requests"] == 6 and result["all"]["ok"] == 3 and result["all"]["requests_per_second"] == 3.0
    assert load_test.summarise([("a", 500, 1.0)], 1.0)["a"]["p95_ms"] is None
