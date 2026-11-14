"""Deliberately defective input: broken files and courses with planted misalignments (datasets/defects, test mode)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_defect_suite as suite   # noqa: E402

API = "/api/v1"
MANIFEST = json.loads((ROOT / "datasets" / "defects" / "manifest.json").read_text(encoding="utf-8"))["courses"]


class _Server:
    """The suite's server interface on top of the test client."""

    def __init__(self, client, headers):
        self._client, self._headers = client, headers

    def get(self, path, **params):
        response = self._client.get(API + path, headers=self._headers, params=params or None)
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path, **kwargs):
        response = self._client.post(API + path, headers=self._headers, **kwargs)
        assert response.status_code < 300, response.text
        return response.json()


@pytest.fixture(scope="module")
def audited(client, headers):
    server = _Server(client, headers)
    return {name: suite.audit_course(server, ROOT / "datasets" / "defects" / name, entry["defects"]) for name, entry in MANIFEST.items()}


def _extra(course, gap_type):
    return [f["description"] for f in course["findings_not_matching_a_planted_defect"] if f["gap_type"] == gap_type]


def test_topics_the_exam_asks_about_are_not_reported_as_unassessed(audited):
    """Found by the suite: every topic was reported as 'not assessed', because only the assessment's title (a file name)
    was compared and exam documents were never searched."""
    assert _extra(audited["en_clean"], "topic_not_assessed") == []
    english = " ".join(_extra(audited["en_defects"], "topic_not_assessed"))
    assert "Graph traversal" in english and "Dynamic programming" in english                 # truly not in the exam
    assert not any(topic in english for topic in ("Sorting algorithms", "Binary search", "Hash tables"))
    german = " ".join(_extra(audited["de_defects"], "topic_not_assessed"))
    assert "Tiefensuche" in german and "Dynamische Programmierung" in german
    assert "Binäre Suche" not in german and "'Hashtabellen'" not in german


def test_every_planted_misalignment_is_found_under_the_right_name(audited):
    english, german = audited["en_defects"], audited["de_defects"]
    assert english["trace_valid"] and german["trace_valid"]
    assert [p["id"] for p in english["planted"] if not p["found"]] == []
    assert [p["id"] for p in german["planted"] if not p["found"]] == []
    found = {p["id"]: p["by"] for p in english["planted"] + german["planted"]}
    assert found["EN-1"] == ["clo_not_covered"] and found["EN-7"] == ["delivery_not_covered"] and found["EN-8"] == ["delivery_unplanned"]
    assert found["EN-2"] == ["taught_topic_outside_metadata"] == found["DE-2"]            # a slide section the module manual never mentions
    assert found["EN-3"] == ["assessment_weak_support"] == found["DE-3"]                  # the one untaught question, not the whole exam
    assert found["EN-4"] == ["assessment_level_below_objective"]                          # tested, but lower: no longer "not assessed"
    assert found["EN-5"] == ["clo_not_assessed"] == found["EN-6"] == found["DE-4"] == found["DE-5"]


def test_findings_name_the_question_and_only_true_extras_remain(audited):
    for name, question, untaught in (("en_defects", "question 4", "Ford-Fulkerson"), ("de_defects", "question 3", "Ford-Fulkerson")):
        course = audited[name]
        weak = [p for p in course["planted"] if p["id"].endswith("-3")][0]
        assert weak["found"]
        extras = course["findings_not_matching_a_planted_defect"]
        assert {f["gap_type"] for f in extras} == {"topic_not_assessed", "topic_not_delivered"}   # all true: topics missing from exam or slides
        assert len(extras) == 3


def test_the_aligned_course_raises_no_finding_at_all(audited):
    clean, defective = audited["en_clean"], audited["en_defects"]
    assert clean["findings"] == 0 and clean["findings_not_matching_a_planted_defect"] == []
    for dimension in ("metadata_content", "content_assessment", "metadata_assessment", "content_delivery"):
        assert clean["dimensions"][dimension]["score"] >= defective["dimensions"][dimension]["score"], dimension
    assert clean["dimensions"]["content_delivery"]["score"] == 1.0 and clean["dimensions"]["metadata_assessment"]["score"] == 1.0


def test_an_exam_is_audited_question_by_question(client, headers):
    course = client.post(f"{API}/courses", headers=headers, json={"code": "DEFECT-QBYQ", "title": "Questions"}).json()["id"]
    base = f"{API}/courses/{course}"
    for name, kind, text in (("slides.txt", "slides", "Binary search. Binary search halves the search space of a sorted array in every step and runs in logarithmic time."),
                             ("exam.txt", "exam", "Question 1. Explain how binary search halves the search space of a sorted array.\n"
                                                  "Question 2. Describe the photosynthesis reaction inside chloroplast membranes of plant cells.\n")):
        assert client.post(base + "/artifacts", headers=headers, data={"artifact_type": kind}, files={"file": (name, text.encode(), "text/plain")}).status_code == 201
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    import time
    for _ in range(600):
        if client.get(f"{API}/runs/{run}", headers=headers).json()["status"] != "running":
            break
        time.sleep(.1)
    report = next(r for r in client.get(base + "/reports", headers=headers).json() if r["report_type"] == "content_assessment")
    weak = [g["description"] for g in client.get(f"{API}/reports/{report['id']}", headers=headers).json()["gaps"] if g["gap_type"] == "assessment_weak_support"]
    assert len(weak) == 1 and "question 2," in weak[0] and "photosynthesis" in weak[0] and "binary search" not in weak[0]


def test_text_without_words_is_refused_and_short_real_text_is_kept(client, headers):
    course = client.post(f"{API}/courses", headers=headers, json={"code": "DEFECT-WORDS", "title": "Words"}).json()["id"]
    base = f"{API}/courses/{course}"

    def status(name, data):
        r = client.post(base + "/artifacts", headers=headers, data={"artifact_type": "slides"}, files={"file": (name, data, "text/plain")})
        assert r.status_code == 201, r.text
        return client.get(base + f"/artifacts/{r.json()['id']}/status", headers=headers).json()

    for name, data in (("letters.txt", b"x" * 50_000), ("symbols.txt", b"1234567890 +-*/ ()[]{} 3.14159 ;;;; ---- ==== 42 42")):
        result = status(name, data)
        assert result["processing_status"] == "error" and "no readable text" in result["processing_error"], name
    assert status("kurz.txt", "Binäre Suche halbiert Suchraum.".encode())["processing_status"] == "done"      # four German words are enough


def test_a_failed_document_shows_a_reason_without_internal_paths_or_error_class_names(client, headers):
    from services.safe_parser import lecturer_message
    leaked = r"pymupdf.FileDataError: Failed to open file 'C:\Users\someone\AppData\Local\Temp\lectio\uploads\abc_truncated.pdf'."
    shown = lecturer_message(leaked, "pdf")
    assert "could not be read as PDF" in shown and "C:\\" not in shown and "pymupdf" not in shown and "Error" not in shown
    assert lecturer_message("ValueError: No extractable text. For scanned PDFs, install Tesseract or upload a text/OCR version.", "pdf").startswith("No extractable text")
    assert lecturer_message("", "docx").startswith("The file could not be read as DOCX")
    course = client.post(f"{API}/courses", headers=headers, json={"code": "DEFECT-MSG", "title": "Messages"}).json()["id"]
    base = f"{API}/courses/{course}"

    def outcome(name, data, mime, kind="slides"):
        r = client.post(base + "/artifacts", headers=headers, data={"artifact_type": kind}, files={"file": (name, data, mime)})
        assert r.status_code == 201, r.text
        return client.get(base + f"/artifacts/{r.json()['id']}/status", headers=headers).json()

    broken = outcome("truncated.pdf", b"%PDF-1.7\n" + b"\x00\xff garbage " * 200, "application/pdf")
    assert broken["processing_status"] == "error" and broken["processing_error"].startswith("The file could not be read as PDF")
    assert "Error" not in broken["processing_error"] and "\\" not in broken["processing_error"] and "/" not in broken["processing_error"]
    transcript = outcome("plain.vtt", b"WEBVTT\n\nBinary search halves the search space.\n", "text/vtt", "transcript")
    assert transcript["processing_status"] == "error" and "cue lines" in transcript["processing_error"] and "PDF" not in transcript["processing_error"]


def test_every_broken_file_has_at_least_one_acceptable_outcome_defined():
    cases = suite.broken_files()
    assert len(cases) >= 28 and len({c[0] for c in cases}) == len(cases)
    assert all(c[6] and set(c[6]) <= {suite.REFUSED, suite.PROCESSED} for c in cases)
