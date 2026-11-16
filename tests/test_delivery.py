"""Fourth alignment dimension: what the transcript says against the prepared slides (planned vs delivered)."""
import pytest

from config import settings
from rag.chunking.chunk_models import RetrievedChunk
from services import delivery_check
from test_phase1_governance import API, _audit, _course

SLIDES = [
    "Binary search. Binary search halves the search space of a sorted array in every step. Its running time is logarithmic in the array length.",
    "Hash tables. A hash function maps keys to table slots. Collisions occur when two keys share a slot; chaining stores colliding entries in a linked list.",
    "Graph traversal. Breadth-first search visits vertices level by level using a queue. Depth-first search follows a path to its end and backtracks, using a stack.",
]


def _chunks(texts, kind, name):
    return [RetrievedChunk(f"{kind}-{i}", text, 0., "artifact-" + kind, kind, "course", None, i + 1 if kind == "slides" else None, None, None,
                           {"filename": name}) for i, text in enumerate(texts)]


def _check(transcript, slides=SLIDES):
    return delivery_check.verify(_chunks(slides, "slides", "slides.pptx"), _chunks(transcript, "transcript", "lecture.vtt"))


def _status(check):
    return {s["title"]: s["status"] for s in check["sections"]}


MATCHING = ["Today we look at binary search. It halves the search space of the sorted array in every step, so the running time is logarithmic. "
            "Next, hash tables. A hash function maps the keys to slots of the table. When two keys share a slot we get a collision, and chaining stores the colliding entries in a linked list. "
            "Finally graph traversal. Breadth-first search visits the vertices level by level with a queue. Depth-first search follows one path to its end, then backtracks using a stack."]


def test_a_transcript_that_matches_its_slides_raises_no_delivery_gap():
    check = _check(MATCHING)
    assert check["ran"] and set(_status(check).values()) == {"covered"}
    assert check["delivered_share"] == 1.0 and check["unplanned"] == []


def test_a_transcript_that_omits_a_planned_topic_is_flagged_with_the_reason():
    spoken = [MATCHING[0].split("Finally graph traversal.")[0]]          # the lecture stops before graphs
    check = _check(spoken)
    assert _status(check) == {"Binary search": "covered", "Hash tables": "covered", "Graph traversal": "not_covered"}
    missed = next(s for s in check["sections"] if s["status"] == "not_covered")
    assert missed["points_addressed"] == 0 and missed["points_total"] == 2 and all(p["transcript"] is None for p in missed["points"])
    assert check["delivered_share"] == pytest.approx(2 / 3, abs=.001)


def test_a_topic_taught_in_different_wording_is_not_flagged():
    spoken = ["Let us start with searching a sorted array. Each step of binary search cuts the remaining space in half. "
              "That is why the running time grows only with the logarithm of the array length. "
              "Now to hashing. Keys are mapped onto table slots by the hash function. "
              "If two keys land in one slot, that collision is handled by chaining: the entries go into a linked list. "
              "Finally, traversing a graph. With a queue we visit vertices one level after another, which is breadth-first search. "
              "With a stack we follow a path to the end and backtrack, which is depth-first search."]
    check = _check(spoken)
    assert set(_status(check).values()) == {"covered"}, _status(check)
    literal = SLIDES[0].split(". ")[1]
    assert literal not in spoken[0]                                     # none of it is a copy of the slide sentence


def test_a_topic_covered_only_in_part_is_reported_as_partial_with_the_missing_points():
    slides = ["Hash tables. A hash function maps keys to table slots. Open addressing probes for the next free slot after a collision. "
              "The load factor controls the expected lookup cost and triggers resizing."]
    check = _check(["Today hash tables. The hash function maps every key to a slot of the table."], slides)
    section = check["sections"][0]
    assert section["status"] == "partial" and section["points_addressed"] == 1 and section["points_total"] == 3
    assert [p["addressed"] for p in section["points"]] == [True, False, False]


def test_unexpected_taught_content_is_identified_and_examples_are_not_flagged():
    extra = (" Next, a different subject. Red-black trees keep themselves balanced through rotations and recolouring after every insertion, "
             "which guarantees logarithmic height for ordered dictionaries.")
    aside = (" Now, for example, imagine a library where a librarian opens the catalogue in the middle and discards half of the drawers each time, "
             "which is how people looked up titles before computers existed.")
    with_extra = _check([MATCHING[0] + extra])
    assert len(with_extra["unplanned"]) == 1 and "Red-black trees" in with_extra["unplanned"][0]["transcript"]["excerpt"]
    assert set(_status(with_extra).values()) == {"covered"}             # planned content is unaffected
    spoken = MATCHING[0].replace(" Next, hash tables.", aside + " Next, hash tables.")
    with_example = _check([spoken])
    assert with_example["unplanned"] == [] and len(with_example["examples_or_asides"]) == 1
    small_talk = _check([MATCHING[0] + " Next, any questions so far? Good, then see you on Thursday."])
    assert small_talk["unplanned"] == []


def test_findings_carry_valid_transcript_and_slide_references():
    slides, spoken = _chunks(SLIDES, "slides", "slides.pptx"), _chunks(MATCHING, "transcript", "lecture.vtt")
    check = delivery_check.verify(slides, spoken)
    slide_ids, transcript_ids = {c.chunk_id for c in slides}, {c.chunk_id for c in spoken}
    for number, section in enumerate(check["sections"], start=1):
        assert section["planned"]["chunk_id"] in slide_ids and section["planned"]["slide"] == number
        assert section["planned"]["document"] == "slides.pptx" and section["planned"]["excerpt"] in " ".join(SLIDES)
        for point in section["points"]:
            ref = point["transcript"]
            assert ref["chunk_id"] in transcript_ids and ref["document"] == "lecture.vtt" and ref["excerpt"] in MATCHING[0]
            assert 0 <= ref["segment"] < check["transcript_segments"]


def test_semantic_matching_accepts_a_paraphrase_with_no_shared_words_and_thresholds_are_configurable(monkeypatch):
    slides = ["Sorting. Merge sort repeatedly divides the list and combines ordered halves."]
    spoken = ["We split the sequence again and again, then join the two arranged parts together into one."]
    assert _status(_check(spoken, slides)) == {"Sorting": "not_covered"}                # shared words alone cannot see it
    close = {slides[0].split(". ", 1)[1]: [1.0, 0.0], spoken[0]: [0.8, 0.6]}

    def embed(texts):
        return [close.get(t, [0.0, 1.0]) for t in texts]
    check = delivery_check.verify(_chunks(slides, "slides", "s"), _chunks(spoken, "transcript", "t"), embed)
    assert _status(check) == {"Sorting": "covered"} and check["sections"][0]["points"][0]["similarity"] == .8
    monkeypatch.setattr(settings, "delivery_point_similarity", .9)
    assert _status(delivery_check.verify(_chunks(slides, "slides", "s"), _chunks(spoken, "transcript", "t"), embed)) == {"Sorting": "not_covered"}


def test_without_a_transcript_delivery_is_reported_as_unverified():
    check = delivery_check.verify(_chunks(SLIDES, "slides", "s"), [])
    assert check["ran"] is False and "transcript" in check["reason"] and "unverified" in check["reason"]


def test_audit_scores_the_delivery_dimension_on_the_transcript(client, headers):
    course, base = _course(client, headers, "P2-DELIV")
    run = _audit(client, headers, base)
    listed = next(r for r in client.get(base + "/reports", headers=headers).json() if r["run_id"] == run and r["report_type"] == "content_delivery")
    report = client.get(f"{API}/reports/{listed['id']}", headers=headers).json()
    check = report["findings"]["findings"]["delivery_verification"]
    status = {s["title"]: s["status"] for s in check["sections"]}
    # the sample lecture talks about binary search, hash tables and graphs, and never about sorting or complexity
    assert status["Binary search"] == "covered" and status["Hash tables"] == "covered" and status["Graph traversal"] == "covered"
    assert status["Sorting algorithms"] == "not_covered" and status["Complexity analysis"] == "not_covered"
    assert report["overall_score"] == pytest.approx(check["delivered_share"]) == pytest.approx(.6)
    assert report["status"] == "warning" and listed["reason"] is None
    flagged = [g for g in report["gaps"] if g["gap_type"] == "delivery_not_covered"]
    assert len(flagged) == 2 and all("lecture_slides.txt" in g["description"] for g in flagged)
    stored = {g["gap_id"]: g for g in report["findings"]["gaps"]}
    evidence = client.get(base + "/evidence", headers=headers).json()
    known = {e.get("chunk_id") or e.get("id") for e in evidence}
    for g in flagged:
        ids = stored[g["id"]]["evidence_chunk_ids"]
        assert ids and set(ids) <= known                                    # references point at real stored excerpts
    briefing = client.get(base + "/briefing", headers=headers).json()
    plain = next(f for f in briefing["findings"] if f["gap_id"] == flagged[0]["id"])
    assert "transcript" in plain["what_was_found"] and plain["evidence"] and plain["evidence"][0]["type"] == "slides"
