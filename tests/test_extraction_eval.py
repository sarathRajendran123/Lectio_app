"""Outcome and schedule extraction: measured on labelled syllabus and slide snippets, plus look-alikes that must not match."""
import pytest

from knowledge import quality_eval
from knowledge.outline_rules import is_stated_outcome, outcome_lines, schedule_entries


@pytest.mark.parametrize("split", ["dev", "test"])
def test_extraction_precision_and_recall_on_the_labelled_cases(split):
    result = quality_eval.extraction_metrics(quality_eval.load_cases(split=split), outcome_lines, schedule_entries)
    for kind in ("outcomes", "weeks"):
        assert result[kind]["precision"] >= 0.9 and result[kind]["recall"] >= 0.9, (kind, result["errors"])


def test_labelled_cases_cover_both_languages_and_document_kinds():
    cases = quality_eval.load_cases()
    assert {c["language"] for c in cases} == {"en", "de"} and {c["split"] for c in cases} == {"dev", "test"}
    assert {"slides", "module_manual", "syllabus"} <= {c["doc_type"] for c in cases}
    assert all(line.strip() for c in cases for line in c["outcomes"]) and sum(len(c["outcomes"]) for c in cases) == 24


def test_metrics_count_wrong_and_missed_lines():
    case = [{"id": "x", "doc_type": "syllabus", "text": "t", "outcomes": ["- Explain A.", "Explain B"], "weeks": [[1, "Sorting"]]}]
    result = quality_eval.extraction_metrics(case, lambda text, plan: ["explain a", "Explain C."], lambda text: [(1, "sorting."), (2, "Extra")])
    assert result["outcomes"] == {"correct": 1, "extracted": 2, "expected": 2, "precision": 0.5, "recall": 0.5, "f1": 0.5}
    assert result["weeks"]["precision"] == 0.5 and result["weeks"]["recall"] == 1.0          # markers, case and final dots are ignored
    assert {e["kind"] for e in result["errors"]} == {"outcomes", "weeks"}
    slides = [{"id": "s", "doc_type": "slides", "text": "t", "outcomes": [], "weeks": []}]
    assert quality_eval.extraction_metrics(slides, lambda text, plan: [], lambda text: [(1, "never read from slides")])["weeks"]["extracted"] == 0


# ── realistic phrasing that must be found ────────────────────────────────────

@pytest.mark.parametrize("line", [
    "CLO1: Design a normalised relational schema for a given scenario.",
    "By the end of the course, participants can explain how a query optimiser chooses a plan.",
    "Students will be able to implement binary search in Python.",
    "Students are expected to be able to evaluate competing designs.",
    "Students will implement a hash table with chaining.",
    "Students will learn to analyse the running time of algorithms.",
    "Die Studierenden können die binäre Suche erklären und ihre Komplexität bewerten.",
    "Die Studierenden sind in der Lage, Hashtabellen zu implementieren.",
    "Die Absolventinnen und Absolventen können Prozesse und Threads unterscheiden.",
    "Die Studierenden sollen Sortierverfahren implementieren.",
    "LZ3: Speicherverwaltung mit Paging beschreiben.",
])
def test_stated_outcomes_in_a_plan_document_are_found(line):
    assert outcome_lines(line, plan=True) == [line]


def test_list_items_are_outcomes_only_under_an_outcomes_heading_or_opening_line():
    text = ("## Learning outcomes\nOn completion, students will be able to:\n- summarise the trade-offs between data structures\n"
            "- justify the choice of an algorithm\n\n## Topics\n- sorting and searching in practice\n- Summarise chapter 2 before the lab")
    assert outcome_lines(text, plan=True) == ["summarise the trade-offs between data structures", "justify the choice of an algorithm"]
    german = "Qualifikationsziele\nNach Abschluss des Moduls können die Studierenden\n- ein relationales Schema entwerfen,\n- Transaktionskonzepte erläutern.\nInhalte\n- Relationenmodell und SQL im Überblick"
    assert outcome_lines(german, plan=True) == ["ein relationales Schema entwerfen", "Transaktionskonzepte erläutern."]


# ── similar-looking lines that must not match ────────────────────────────────

@pytest.mark.parametrize("line", [
    "Students who are not able to attend the lab must notify the lecturer in advance.",
    "Students will receive their grades within four weeks after the exam.",
    "Students should bring a laptop to every lab session.",
    "Students will be assigned to lab groups in the first week.",
    "The lecturer will be able to answer questions during office hours.",
    "Prerequisites: Students should have completed Programming 1.",
    "Students are expected to be able to program in C before the course starts.",
    "On successful completion of this module, students will be able to:",
    "Studierende können sich bis zum 1. Mai zur Prüfung anmelden.",
    "Die Studierenden sollen einen Laptop zu den Übungen mitbringen.",
    "Die Lernziele werden in der Klausur abgeprüft.",
    "Studierende, die nicht in der Lage sind teilzunehmen, melden sich bitte ab.",
    "Die Studierenden sollen Grundkenntnisse in C mitbringen.",
    "This module introduces the design and analysis of algorithms.",
])
def test_organisational_and_look_alike_lines_are_not_outcomes(line):
    assert outcome_lines(line, plan=True) == []


@pytest.mark.parametrize("line,expected", [
    ("After this lecture, students will be able to trace the execution of quicksort.", True),
    ("LO2: Explain the role of the pivot element.", True),
    ("Nach dieser Vorlesung können die Studierenden Quicksort von Hand durchführen.", True),
    ("Die Studierenden werden in der Lage sein, die Laufzeit abzuschätzen.", True),
    ("We will be able to finish chapter 3 if time permits.", False),
    ("Researchers were able to show a speed-up of 30 percent.", False),
    ("Students will work in pairs on the exercise.", False),
    ("Explain the role of the pivot element.", False),                       # a slide heading or task, not a stated outcome
    ("Die Forscher waren in der Lage, die Laufzeit zu halbieren.", False),
    ("Studierende werden in Zweiergruppen eingeteilt.", False),
])
def test_slides_and_papers_are_read_strictly(line, expected):
    assert bool(outcome_lines(line, plan=False)) is expected and is_stated_outcome(line) is expected


def test_a_date_does_not_cut_a_sentence_and_duplicates_are_reported_once():
    text = "Die Studierenden können bis zum 1. Semesterende Algorithmen analysieren. Die Studierenden können bis zum 1. Semesterende Algorithmen analysieren."
    assert outcome_lines(text, plan=True) == ["Die Studierenden können bis zum 1. Semesterende Algorithmen analysieren."]


# ── schedule ─────────────────────────────────────────────────────────────────

def test_schedule_lines_in_common_notations():
    text = ("Week 1: Sorting and complexity\nWk 2: Binary search\nWk. 3 (12 Oct): Hash tables\nWeek 4 - Graph traversal\n"
            "Lecture 5: Dynamic programming\n- Session 6: Greedy algorithms\n7. Woche: Hashtabellen\nVorlesung 8: Graphen\nKW 42: Prozesse")
    assert schedule_entries(text) == [(1, "Sorting and complexity"), (2, "Binary search"), (3, "Hash tables"), (4, "Graph traversal"),
                                      (5, "Dynamic programming"), (6, "Greedy algorithms"), (7, "Hashtabellen"), (8, "Graphen"), (42, "Prozesse")]


@pytest.mark.parametrize("line", [
    "Week 5: Reading week (no lecture)", "Week 6: Midterm exam", "Woche 4: vorlesungsfrei", "KW 44: Feiertag, keine Vorlesung",
    "Woche 5: Klausur", "Session 3: No class (public holiday)", "Week 5 deadline: submit assignment 1",
    "In week 2 we had 30 students in the lab.", "Week 99: Out of range", "See week 3: hash tables for details",
])
def test_lines_that_are_not_teaching_weeks_are_left_out(line):
    assert schedule_entries(line) == []


def test_first_entry_for_a_week_wins_and_a_real_topic_mentioning_exams_is_kept():
    assert schedule_entries("Week 1: Sorting\nWeek 1: Something else\nWeek 2: Exam-style problem solving for graph algorithms") == [
        (1, "Sorting"), (2, "Exam-style problem solving for graph algorithms")]


# ── module manuals in real layout: outcome paragraphs and schedule tables ─────

MANUAL_DE = """Lehr-/Lernmethoden | Vorlesung mit Übungen, Präsentationen der Studierenden
Fachkompetenz: Wissen und
Verstehen | Die Studierenden verstehen Graphalgorithmen als Grundlage
vieler Anwendungen und können deren Bedeutung einordnen. Sie beherrschen
die Laufzeitanalyse rekursiver Verfahren. Sie kennen gängige Datenstruk-
turen und Suchverfahren.
Fachkompetenz: Fertigkeit und
Wissenserschließung | Die Studierenden implementieren Suchverfahren in Python-
Programmen und vergleichen deren Laufzeit. Sie bilden in Woche 1 feste Teams.
Personale Kompetenz:
Sozialkompetenz | Sie präsentieren Ergebnisse verständlich vor der Gruppe.
Literatur/Lernquellen | Cormen et al.: Introduction to Algorithms."""

MANUAL_EN = """Teaching methods | Lectures with exercises
Learning outcomes | Students understand the role of hashing in databases.
They implement hash tables with chaining and evaluate their lookup cost.
The lecture notes are published weekly.
Subject-specific competences | They compare sorting algorithms by their running
time."""


def test_outcome_paragraphs_under_competence_headings_are_read_sentence_by_sentence():
    from knowledge.outline_rules import prose_outcomes
    german = prose_outcomes(MANUAL_DE)
    assert german == [
        "Die Studierenden verstehen Graphalgorithmen als Grundlage vieler Anwendungen und können deren Bedeutung einordnen.",
        "Sie beherrschen die Laufzeitanalyse rekursiver Verfahren.",
        "Sie kennen gängige Datenstrukturen und Suchverfahren.",                                   # line-end hyphen joined
        "Die Studierenden implementieren Suchverfahren in Python-Programmen und vergleichen deren Laufzeit.",  # hyphen kept
        "Sie präsentieren Ergebnisse verständlich vor der Gruppe.",
    ]                                                                     # "Sie bilden in Woche 1 feste Teams" is organisation
    english = prose_outcomes(MANUAL_EN)
    assert english == ["Students understand the role of hashing in databases.",
                       "They implement hash tables with chaining and evaluate their lookup cost.",
                       "They compare sorting algorithms by their running time."]
    assert prose_outcomes("Die Studierenden bilden feste Teams. Sie präsentieren in Woche 15.") == []   # no heading: not read
    assert prose_outcomes("") == []


def test_a_line_wise_copy_of_a_prose_outcome_is_recognised_as_a_duplicate():
    from knowledge.outline_rules import is_fragment_of, prose_outcomes
    sentences = prose_outcomes(MANUAL_DE)
    assert is_fragment_of("Verstehen | Die Studierenden verstehen Graphalgorithmen als Grundlage", sentences)
    assert is_fragment_of("Sie kennen gängige Datenstruk- turen und Suchverfahren.", sentences) is False   # different word split
    assert is_fragment_of("Sie kennen gängige Datenstrukturen und Suchverfahren.", sentences)            # same sentence again
    assert not is_fragment_of("Die Studierenden entwerfen eigene Algorithmen.", sentences)


def test_a_schedule_table_is_read_and_ends_at_the_first_other_line():
    from knowledge.outline_rules import table_schedule
    text = """Grobe Struktur / Inhalte
Woche | Thema
1 | Organisation & Einführung
2 | Sortieren: Insertion Sort, Merge Sort
3 | Hashtabellen
4 | Vorlesungsfrei
5 | Graphen und Tiefensuche
Prüfungsleistung – Übersicht
6 | Not a schedule row any more"""
    assert table_schedule(text) == [(1, "Organisation & Einführung"), (2, "Sortieren: Insertion Sort, Merge Sort"),
                                    (3, "Hashtabellen"), (5, "Graphen und Tiefensuche")]      # holiday left out, table ended
    english = "Week Topic\n1 Introduction\n2 Neural networks\n3 Training and optimisation\n12 Unrelated number later"
    assert table_schedule(english) == [(1, "Introduction"), (2, "Neural networks"), (3, "Training and optimisation")]
    assert table_schedule("1 | Introduction\n2 | Neural networks") == []                       # rows without a header are not a schedule
