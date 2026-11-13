"""Phase 3, item 11: labelling sheets and study metrics. All labels in this file are made up to test the arithmetic."""
import json
import sys
import time
from pathlib import Path

import pytest

from knowledge import study_eval as study
from test_multilingual_model import _upload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study as study_script   # noqa: E402

API = "/api/v1"


def _finding(fid, dimension, valid="", match=""):
    return {"finding_id": fid, "dimension": dimension, "gap_type": "t", "severity": "warning", "description": "d",
            "recommendation": "r", "valid": valid, "matches_issue": match, "note": ""}


def _issue(iid, dimension):
    return {"issue_id": iid, "dimension": dimension, "description": "d", "where": "", "severity": "", "rater": "A"}


# ── findings: precision, recall, F1 ──────────────────────────────────────────

def test_precision_recall_and_f1_match_a_hand_computed_example():
    issues = [_issue("I1", "metadata_content"), _issue("I2", "metadata_content"), _issue("I3", "metadata_content"),
              _issue("I4", "content_assessment")]
    judgements = [_finding("F1", "metadata_content", "1", "I1"), _finding("F2", "metadata_content", "1", "I1"),   # two findings, one issue
                  _finding("F3", "metadata_content", "1"),                                                       # valid, lecturer had not listed it
                  _finding("F4", "metadata_content", "0"), _finding("F5", "metadata_content", "?"),
                  _finding("F6", "metadata_content", ""), _finding("F7", "content_assessment", "0")]
    result = study.detection_metrics(issues, judgements)
    mc = result["metadata_content"]
    assert (mc["judged"], mc["valid"], mc["cannot_judge"], mc["not_judged"], mc["valid_not_in_issue_list"]) == (4, 3, 1, 1, 1)
    assert mc["precision"] == 0.75 and mc["recall"] == round(1 / 3, 4) and mc["issues_missed"] == 2
    assert mc["f1"] == round(2 * 0.75 * (1 / 3) / (0.75 + 1 / 3), 4)
    ca = result["content_assessment"]
    assert ca["precision"] == 0.0 and ca["recall"] == 0.0 and ca["f1"] == 0.0
    total = result["all_assessed_dimensions"]
    assert total["precision"] == 0.6 and total["recall"] == 0.25


def test_an_undefined_figure_is_none_and_never_a_perfect_score():
    result = study.detection_metrics([], [_finding("F1", "content_delivery", "")])
    for name in (*study.DIMENSIONS, "all_assessed_dimensions"):
        assert result[name]["precision"] is None and result[name]["recall"] is None and result[name]["f1"] is None
    only_issues = study.detection_metrics([_issue("I1", "content_delivery")], [])
    assert only_issues["content_delivery"]["recall"] == 0.0 and only_issues["content_delivery"]["precision"] is None


def test_a_dimension_the_system_could_not_assess_is_reported_but_not_counted_as_a_miss():
    issues = [_issue("I1", "content_delivery"), _issue("I2", "metadata_content")]
    judgements = [_finding("F1", "metadata_content", "1", "I2")]
    counted = study.detection_metrics(issues, judgements)
    abstained = study.detection_metrics(issues, judgements, abstained=("content_delivery",))
    assert counted["all_assessed_dimensions"]["recall"] == 0.5
    assert abstained["all_assessed_dimensions"]["recall"] == 1.0
    assert abstained["content_delivery"]["abstained"] is True and abstained["content_delivery"]["issues_missed"] == 1   # still visible


@pytest.mark.parametrize("issues, judgements", [
    ([_issue("I1", "teaching")], []),                                                        # unknown dimension
    ([_issue("I1", "metadata_content"), _issue("I1", "metadata_content")], []),              # duplicate issue id
    ([], [_finding("F1", "metadata_content", "yes")]),                                       # label outside 1 / 0 / ?
    ([_issue("I1", "metadata_content")], [_finding("F1", "metadata_content", "1", "I9")]),   # match to an unknown issue
    ([_issue("I1", "metadata_content")], [_finding("F1", "content_delivery", "1", "I1")]),   # match across dimensions
    ([_issue("I1", "metadata_content")], [_finding("F1", "metadata_content", "0", "I1")]),   # a rejected finding cannot find an issue
])
def test_inconsistent_sheets_are_refused(issues, judgements):
    with pytest.raises(ValueError):
        study.detection_metrics(issues, judgements)


# ── agreement ────────────────────────────────────────────────────────────────

def test_kappa_matches_a_hand_computed_example():
    a = [_finding(f"F{i}", "metadata_content", v) for i, v in enumerate("1111110000")]
    b = [_finding(f"F{i}", "metadata_content", v) for i, v in enumerate("1111000001")]
    assert study.kappa(a, b) == {"items": 10, "observed_agreement": 0.7, "kappa": 0.4}   # po 0.7, pe 0.6*0.5 + 0.4*0.5


def test_kappa_uses_only_findings_both_raters_judged_and_is_undefined_without_variation():
    a = [_finding("F1", "metadata_content", "1"), _finding("F2", "metadata_content", "?"), _finding("F3", "metadata_content", "1")]
    b = [_finding("F1", "metadata_content", "1"), _finding("F2", "metadata_content", "1")]
    assert study.kappa(a, b) == {"items": 1, "observed_agreement": 1.0, "kappa": None}
    assert study.kappa(a, []) == {"items": 0, "observed_agreement": None, "kappa": None}


# ── drafts ───────────────────────────────────────────────────────────────────

DRAFTS = [{"id": f"id-{n}", "content_type": "exercise", "content": f"Übung {n}: Erklären Sie Mergesort.", "title": f"Exercise · Alternative {n} (applied)",
           "model_used": model, "approval_status": status, "quality_score": .8, "quality_passed": passed}
          for n, (model, status, passed) in enumerate([("model-a", "approved", True), ("model-a", "rejected", True), ("model-b", "approved", False),
                                                       ("model-b", "pending", True), ("model-b", "revised", True), ("model-a", "rejected", False)])]


def test_the_rating_sheet_hides_model_style_status_and_quality_score():
    rows, key = study.blind_drafts(DRAFTS, seed=7)
    assert len(rows) == len(key) == 6 and set(rows[0]) == set(study.DRAFT_COLUMNS)
    text = json.dumps(rows, ensure_ascii=False)
    for hidden in ("model-a", "model-b", "approved", "rejected", "Alternative", "applied", "0.8", "id-"):
        assert hidden not in text
    assert "Übung" in text                                                              # German text survives
    assert {key[r["blind_id"]]["id"] for r in rows} == {d["id"] for d in DRAFTS}
    assert rows == study.blind_drafts(DRAFTS, seed=7)[0]                                # repeatable
    assert [r["blind_id"] for r in rows] != [r["blind_id"] for r in study.blind_drafts(DRAFTS, seed=8)[0]]


def test_draft_ratings_and_decisions_match_a_hand_computed_example():
    rows, key = study.blind_drafts(DRAFTS, seed=1)
    by_id = {key[r["blind_id"]]["id"]: r for r in rows}
    for draft_id, relevance, usefulness, burden in [("id-0", "5", "4", "none"), ("id-1", "3", "", "major"), ("id-2", "2", "2", "rewrite")]:
        by_id[draft_id].update(relevance=relevance, usefulness=usefulness, edit_burden=burden)
    result = study.draft_metrics(rows, key)
    assert result["drafts"] == 6 and result["rated"] == 3
    assert result["ratings"]["all"]["relevance"] == {"mean": 3.333, "n": 3} and result["ratings"]["all"]["usefulness"] == {"mean": 3.0, "n": 2}
    assert result["ratings"]["model-a"]["relevance"] == {"mean": 4.0, "n": 2} and result["ratings"]["model-b"]["relevance"] == {"mean": 2.0, "n": 1}
    assert result["edit_burden"] == {"none": 1, "major": 1, "rewrite": 1}
    assert result["decisions"] == {"approved": 2, "rejected": 2, "revised": 1, "pending": 1, "approved_share_of_decided": 0.5}
    assert result["quality_gate"] == {"decided_with_gate_result": 4, "gate_passed_and_approved": 1, "gate_passed_and_rejected": 1,
                                      "gate_failed_and_approved": 1, "gate_failed_and_rejected": 1}


@pytest.mark.parametrize("field, value", [("relevance", "6"), ("relevance", "4.5"), ("edit_burden", "some"), ("blind_id", "D-unknown")])
def test_invalid_ratings_are_refused(field, value):
    rows, key = study.blind_drafts(DRAFTS, seed=1)
    rows[0][field] = value
    with pytest.raises(ValueError):
        study.draft_metrics(rows, key)


def test_no_decisions_and_no_ratings_give_none():
    rows, key = study.blind_drafts([{**DRAFTS[3]}], seed=1)
    result = study.draft_metrics(rows, key)
    assert result["rated"] == 0 and result["ratings"] == {} and result["decisions"]["approved_share_of_decided"] is None


# ── files and the script ─────────────────────────────────────────────────────

def test_sheets_survive_a_round_trip_with_german_text_and_excel_byte_order_mark(tmp_path):
    rows = [{**_finding("F1", "metadata_content", "1"), "description": 'Lernziel "erklären"; mit Komma, Umlaut ä und\nZeilenumbruch'}]
    study.write_csv(tmp_path / "a.csv", study.FINDING_COLUMNS, rows)
    assert study.read_csv(tmp_path / "a.csv") == rows
    (tmp_path / "b.csv").write_bytes(b"\xef\xbb\xbf" + (tmp_path / "a.csv").read_bytes())   # as saved by Excel
    assert study.read_csv(tmp_path / "b.csv") == rows


class _Api:
    def __init__(self, client, headers):
        self.client, self.headers = client, headers

    def get(self, path, params=None):
        return self.client.get(API + path, headers=self.headers, params=params)


def test_export_and_score_end_to_end_without_inventing_a_label(client, headers, tmp_path, capsys):
    course = client.post(f"{API}/courses", headers=headers, json={"code": "STUDY-1", "title": "Algorithms"}).json()["id"]
    base = f"{API}/courses/{course}"
    for name, kind, mime in [("syllabus.md", "syllabus", "text/markdown"), ("lecture_slides.txt", "slides", "text/plain"), ("exam.txt", "exam", "text/plain")]:
        _upload(client, headers, base, "en_algorithms", name, kind, mime)
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    for _ in range(600):
        if client.get(f"{API}/runs/{run}", headers=headers).json()["status"] != "running":
            break
        time.sleep(.1)
    manifest = study_script.export(course, tmp_path, seed=3, client=_Api(client, headers))
    assert manifest["run_id"] == run and manifest["course_code"] == "STUDY-1" and manifest["mode"] == "local_test" and manifest["findings"] > 0
    findings = study.read_csv(tmp_path / "findings.csv")
    assert len(findings) == manifest["findings"] and all(f["valid"] == "" and f["matches_issue"] == "" for f in findings)
    assert {f["dimension"] for f in findings} <= set(study.DIMENSIONS)
    blind = study.read_csv(tmp_path / "drafts_blind.csv")
    key = json.loads((tmp_path / "drafts_key.json").read_text(encoding="utf-8"))
    assert len(blind) == len(key) == manifest["drafts"] and all("model" not in column for column in blind[0]) if blind else True

    study_script.main(["issues-template", "--out", str(tmp_path / "issues.csv")])
    with pytest.raises(SystemExit):
        study_script.main(["issues-template", "--out", str(tmp_path / "issues.csv")])      # a filled sheet is never overwritten
    # Scoring sheets nobody filled in: every figure is undefined.
    report = study_script.score(tmp_path / "issues.csv", [tmp_path / "findings.csv"], tmp_path / "drafts_blind.csv", tmp_path / "drafts_key.json",
                                tmp_path / "manifest.json", tmp_path / "report", "not labelled")
    assert all(report["detection"][d]["precision"] is None and report["detection"][d]["recall"] is None for d in study.DIMENSIONS)
    assert report["drafts"]["rated"] == 0
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Labels: not labelled" in text and "STUDY-1" in text and "n/a" in text and "100%" not in text
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["manifest"]["run_id"] == run

    # A rater fills in the sheets (made-up labels): the figures follow from them.
    first = findings[0]
    study.write_csv(tmp_path / "issues.csv", study.ISSUE_COLUMNS, [_issue("I1", first["dimension"]), _issue("I2", first["dimension"])])
    rated = [{**f, "valid": "1" if n == 0 else "0", "matches_issue": "I1" if n == 0 else ""} for n, f in enumerate(findings)]
    study.write_csv(tmp_path / "rater1.csv", study.FINDING_COLUMNS, rated)
    study.write_csv(tmp_path / "rater2.csv", study.FINDING_COLUMNS, [{**f, "matches_issue": ""} for f in rated])
    study_script.main(["score", "--issues", str(tmp_path / "issues.csv"), "--findings", str(tmp_path / "rater1.csv"), str(tmp_path / "rater2.csv"),
                       "--manifest", str(tmp_path / "manifest.json"), "--out", str(tmp_path / "report2"), "--label-status", "made up for a software test"])
    result = json.loads((tmp_path / "report2.json").read_text(encoding="utf-8"))
    total = result["detection"]["all_assessed_dimensions"]
    assert total["valid"] == 1 and total["judged"] == len(findings) and total["recall"] == 0.5
    assert result["agreement"]["items"] == len(findings) and result["agreement"]["observed_agreement"] == 1.0
    assert "made up for a software test" in capsys.readouterr().out
