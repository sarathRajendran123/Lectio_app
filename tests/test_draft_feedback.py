"""Phase 4, item 14: provisional alignment feedback on text the lecturer is still writing (test mode: rules and word-overlap search)."""
import pytest

from test_multilingual_model import _objectives, _upload

API = "/api/v1"


def _course(client, headers, code, folder, files):
    course = client.post(f"{API}/courses", headers=headers, json={"code": code, "title": "Algorithms"}).json()["id"]
    base = f"{API}/courses/{course}"
    for name, kind, mime in files:
        _upload(client, headers, base, folder, name, kind, mime)
    assert client.post(base + "/extract-model", headers=headers).status_code == 200
    return course, base


@pytest.fixture(scope="module")
def german(client, headers):
    return _course(client, headers, "FB-DE", "de_algorithmen", [("modulhandbuch.md", "syllabus", "text/markdown"),
                                                                 ("vorlesung.txt", "slides", "text/plain"), ("klausur.txt", "exam", "text/plain")])


@pytest.fixture(scope="module")
def english(client, headers):
    return _course(client, headers, "FB-EN", "en_algorithms", [("syllabus.md", "syllabus", "text/markdown"),
                                                                ("lecture_slides.txt", "slides", "text/plain"), ("exam.txt", "exam", "text/plain")])


def _feedback(client, headers, base, **body):
    r = client.post(base + "/draft-feedback", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _types(result):
    return {f["type"] for f in result["findings"]}


def test_feedback_is_marked_provisional_and_every_finding_states_its_uncertainty(client, headers, english):
    result = _feedback(client, headers, english[1], content_type="exercise", text="Explain how binary search halves the search space of a sorted array.")
    assert result["provisional"] is True and "No model was used" in result["notice"] and "not an audit result" in result["notice"]
    assert all(f["uncertainty"] and f["severity"] in ("info", "warning") for f in result["findings"])
    assert result["bloom"]["level"] == "understand" and result["bloom"]["verb"] == "explain"


def test_a_task_on_a_taught_topic_comes_with_the_passages_it_rests_on(client, headers, english):
    result = _feedback(client, headers, english[1], content_type="exercise", text="Explain how binary search halves the search space of a sorted array.")
    assert "feedback_no_teaching_evidence" not in _types(result) and "feedback_weak_teaching_evidence" not in _types(result)
    top = result["evidence"][0]
    assert "Binary search halves the search space" in top["excerpt"] and top["artifact_type"] == "slides" and top["chunk_id"] and 0 < top["match"] <= 1
    known = {e["id"] for e in client.get(english[1] + "/evidence", headers=headers).json()}
    assert all(e["chunk_id"] in known for e in result["evidence"])                       # only real passages of this course are shown


def test_a_task_on_an_untaught_topic_is_reported_as_insufficient_evidence_not_as_wrong(client, headers, english):
    result = _feedback(client, headers, english[1], content_type="quiz", text="Describe the photosynthesis reaction inside chloroplast membranes.")
    assert "feedback_no_teaching_evidence" in _types(result) and result["evidence"] == []
    finding = next(f for f in result["findings"] if f["type"] == "feedback_no_teaching_evidence")
    assert "Insufficient evidence" in finding["message"] and "not proof" in finding["uncertainty"]


def test_a_task_below_the_intended_level_is_flagged_and_one_at_the_level_is_not(client, headers, english):
    low = _feedback(client, headers, english[1], content_type="exercise", intended_level="evaluate", text="List the steps of merge sort.")
    assert low["bloom"] == {"level": "remember", "verb": "list", "method": "action_verb", "ambiguous": False, "intended": "evaluate"}
    assert "feedback_level_below_intended" in _types(low)
    assert next(f for f in low["findings"] if f["type"] == "feedback_level_below_intended")["severity"] == "warning"
    right = _feedback(client, headers, english[1], content_type="exercise", intended_level="evaluate",
                      text="Evaluate whether merge sort or insertion sort suits a nearly sorted list.")
    assert not {"feedback_level_below_intended", "feedback_level_above_intended"} & _types(right)
    high = _feedback(client, headers, english[1], content_type="exercise", intended_level="remember", text="Evaluate the load factor of a hash table.")
    assert "feedback_level_above_intended" in _types(high)


def test_a_task_below_the_level_of_its_objective_is_flagged_in_german(client, headers, german):
    objectives = _objectives(client, headers, german[1])
    target = next(o for o in objectives if "binäre Suche" in o["text"])                   # "... erklären und ihre Komplexität bewerten"
    assert target["bloom_level"] == "understand"       # known classifier limit: of two joined demands the first is taken (docs/EVALUATION.md)
    result = _feedback(client, headers, german[1], content_type="exercise", objective_ids=[target["id"]],
                       text="Nennen Sie die Schritte der binären Suche in einem sortierten Array.")
    assert result["bloom"]["level"] == "remember"
    assert "feedback_level_below_objective" in _types(result)
    assert result["objectives"] == [{"id": target["id"], "code": target["code"], "text": target["text"], "bloom_level": "understand",
                                     "match": result["objectives"][0]["match"], "selected": True}]
    assert "Binäre Suche" in result["evidence"][0]["excerpt"]
    same = _feedback(client, headers, german[1], content_type="exercise", objective_ids=[target["id"]],
                     text="Erklären Sie die binäre Suche für ein sortiertes Array.")
    assert "feedback_level_below_objective" not in _types(same)


def test_the_objective_a_task_addresses_is_found_without_being_selected(client, headers, german):
    result = _feedback(client, headers, german[1], content_type="quiz", text="Vergleichen Sie Verkettung und offene Adressierung bei Kollisionen in Hashtabellen.")
    assert result["objectives"] and "Hashtabellen" in result["objectives"][0]["text"] and result["objectives"][0]["selected"] is False
    none = _feedback(client, headers, german[1], content_type="quiz", text="Beschreiben Sie die Photosynthese in den Chloroplasten.")
    assert none["objectives"] == [] and "feedback_no_objective_matched" in _types(none)


def test_a_new_objective_is_checked_against_existing_ones_the_exam_and_the_course_intent(client, headers, english):
    base = english[1]
    module = client.post(base + "/modules", headers=headers, json={"title": "Sorting", "sequence_number": 1}).json()["id"]   # this syllabus states no outcomes
    existing = client.post(base + f"/modules/{module}/clos", headers=headers, json={"text": "Students can analyse the running time of merge sort."}).json()
    repeat = _feedback(client, headers, base, content_type="clo", text=existing["text"])
    assert "feedback_similar_objective_exists" in _types(repeat)
    assessed = _feedback(client, headers, base, content_type="clo", text="Students can compare chaining and open addressing for collision handling in hash tables.")
    assert "feedback_objective_not_assessed" not in _types(assessed) and "Question 2" in assessed["assessment_evidence"][0]["excerpt"]
    unassessed = _feedback(client, headers, base, content_type="clo", text="Students can describe the photosynthesis reaction inside chloroplast membranes.")
    assert {"feedback_objective_not_assessed", "feedback_no_teaching_evidence"} <= _types(unassessed)
    assert "feedback_level_outside_intent" not in _types(unassessed)                     # no intent stated yet
    assert client.put(base + "/intent", headers=headers, json={"goals": "Students analyse and evaluate algorithms.",
                                                               "cognitive_levels": ["analyse", "evaluate"]}).status_code == 200
    outside = _feedback(client, headers, base, content_type="clo", text="Students can list the steps of merge sort.")
    assert "feedback_level_outside_intent" in _types(outside)
    inside = _feedback(client, headers, base, content_type="clo", text="Students can evaluate sorting algorithms for a given input.")
    assert "feedback_level_outside_intent" not in _types(inside)


def test_a_course_without_documents_says_what_could_not_be_checked_instead_of_raising_findings(client, headers):
    course = client.post(f"{API}/courses", headers=headers, json={"code": "FB-EMPTY", "title": "Empty"}).json()["id"]
    result = _feedback(client, headers, f"{API}/courses/{course}", content_type="clo", text="Students can analyse sorting algorithms.")
    assert len(result["not_checked"]) == 3 and result["evidence"] == [] and result["assessment_evidence"] == []
    assert _types(result) == set() and result["bloom"]["level"] == "analyse"


def test_text_without_a_recognised_verb_is_reported_as_unclear_not_guessed(client, headers, english):
    result = _feedback(client, headers, english[1], content_type="exercise", intended_level="apply", text="Binary search and sorted arrays with 64 entries.")
    assert result["bloom"]["level"] is None and "feedback_level_unclear" in _types(result)
    assert not {"feedback_level_below_intended", "feedback_level_above_intended"} & _types(result)


def test_feedback_stores_no_draft_changes_no_report_and_logs_only_a_fingerprint(client, headers, english):
    course, base = english
    before = client.get(base + "/export", headers=headers).json()
    text = "Explain why open addressing probes for the next free slot. UNIQUE-MARKER-TEXT"
    _feedback(client, headers, base, content_type="exercise", text=text)
    after = client.get(base + "/export", headers=headers).json()
    assert after["suggestions"] == before["suggestions"] and after["reports"] == before["reports"]
    assert _objectives(client, headers, base) == _objectives(client, headers, base)
    trace = client.get(base + "/trace", headers=headers, params={"event_type": "draft_feedback"}).json()
    event = trace["events"][-1]
    assert event["payload"]["content_type"] == "exercise" and len(event["payload"]["text_fingerprint"]) == 16
    assert "UNIQUE-MARKER-TEXT" not in str(trace) and client.get(base + "/trace/verify", headers=headers).json()["valid"] is True


def test_feedback_works_while_an_audit_is_running_and_refuses_bad_input(client, headers, english):
    course, base = english
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    try:
        assert client.post(base + "/draft-feedback", headers=headers, json={"content_type": "exercise", "text": "Explain binary search."}).status_code == 200
    finally:
        client.post(f"{API}/runs/{run}/cancel", headers=headers)
    other = client.post(f"{API}/courses", headers=headers, json={"code": "FB-OTHER", "title": "Other"}).json()["id"]
    module = client.post(f"{API}/courses/{other}/modules", headers=headers, json={"title": "Module", "sequence_number": 1}).json()["id"]
    foreign = client.post(f"{API}/courses/{other}/modules/{module}/clos", headers=headers, json={"text": "Explain how hashing works."}).json()["id"]
    for body in ({"content_type": "exercise", "text": "short"}, {"content_type": "essay", "text": "Explain binary search."},
                 {"content_type": "exercise", "text": "Explain binary search.", "intended_level": "master"},
                 {"content_type": "exercise", "text": "x" * 6001},
                 {"content_type": "exercise", "text": "Explain binary search.", "objective_ids": [foreign]}):
        assert client.post(base + "/draft-feedback", headers=headers, json=body).status_code == 422, body


# ── accessibility of the colours that carry text ────────────────────────────

def _contrast(foreground, background):
    def luminance(colour):
        channels = [int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_colours_meet_wcag_aa_contrast():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))
    from components.ui_components import BLOOM_COLOURS
    for level, colour in BLOOM_COLOURS.items():
        assert _contrast("#FFFFFF", colour) >= 4.5, level                    # white badge text on each level colour
    for colour in ("#182B3A", "#526461", "#6B7280"):                         # body text, metric labels, small grey labels
        assert _contrast(colour, "#FAF9F6") >= 4.5 and _contrast(colour, "#FFFFFF") >= 4.5, colour
    assert _contrast("#FFFFFF", "#24695D") >= 4.5                            # primary button text
    assert _contrast("#B87928", "#FAF9F6") >= 3.0                            # focus ring, a non-text indicator
