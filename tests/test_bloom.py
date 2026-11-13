"""Bloom classifier: measured against the labelled English and German set, plus the rules behind it."""
import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from config import settings
from knowledge import bloom_eval
from knowledge.bloom_classifier import (AMBIGUOUS_VERBS, LEVEL_ORDER, classify_detail, classify_hybrid, classify_many_with_llm,
                                        classify_text, classify_with_llm)


def _rules(text):
    return classify_text(text)[0]


# ── accuracy against the labelled set ────────────────────────────────────────

def test_labelled_set_is_balanced_and_well_formed():
    rows = bloom_eval.load()
    core = [r for r in rows if r["split"] in ("dev", "test")]
    assert len(core) == 96 and len({r["id"] for r in rows}) == len(rows) == 120
    for language in ("en", "de"):
        for level in LEVEL_ORDER:
            assert sum(1 for r in core if r["language"] == language and r["level"] == level) == 8
    assert {r["kind"] for r in rows} == {"objective", "question"} and sum(1 for r in rows if r["split"] == "challenge") == 24


@pytest.mark.parametrize("language", ["en", "de"])
def test_accuracy_on_ordinary_objectives_and_questions(language):
    """Dev and held-out items: standard phrasing, inflected verbs, separable German verbs, noun traps."""
    for split in ("dev", "test"):
        result = bloom_eval.evaluate(bloom_eval.load(split=split, language=language), _rules)
        assert result["accuracy"] >= 0.95, (split, result["errors"])
        assert all(m["recall"] >= 0.85 for m in result["per_level"].values() if m["items"]), result["per_level"]


def test_known_weakness_on_hard_phrasing_is_measured_not_hidden():
    """Purpose clauses, nominalised demands and verbs outside the lexicon. These items were never tuned against.
    The rules get about a fifth right; this guards the figure in docs/EVALUATION.md against silent change."""
    result = bloom_eval.evaluate(bloom_eval.load(split="challenge"), _rules)
    assert 0.15 <= result["accuracy"] <= 0.45 and result["coverage"] <= 0.7
    wrong = {e["id"]: e["got"] for e in result["errors"]}
    assert wrong["en-ch-1"] == "apply"           # "Use ... to evaluate": the first verb is not the main demand
    assert wrong["en-ch-11"] == "create"         # "develop an understanding": the demand sits in a noun
    assert wrong["de-ch-5"] is None              # "schreiben" is not in the lexicon: left unclassified, not guessed


def test_metrics_are_computed_correctly():
    rows = [{"id": str(i), "text": t, "level": level, "language": "en"} for i, (t, level) in enumerate(
        [("a", "apply"), ("b", "apply"), ("c", "create"), ("d", "remember")])]
    result = bloom_eval.evaluate(rows, {"a": "apply", "b": "create", "c": "create", "d": None}.get)
    assert result["accuracy"] == 0.5 and result["coverage"] == 0.75 and len(result["errors"]) == 2
    assert result["per_level"]["apply"] == {"items": 2, "precision": 1.0, "recall": 0.5, "f1": pytest.approx(2 / 3)}
    assert result["per_level"]["create"]["precision"] == 0.5 and result["per_level"]["remember"]["recall"] == 0.0
    assert result["per_level"]["evaluate"]["precision"] is None and result["per_level"]["evaluate"]["recall"] is None


# ── the rules ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,level,verb", [
    ("The student interprets a given list of benchmark results.", "understand", "interpret"),      # "list" is a noun here
    ("Learners are able to carry out a unit test for a given function.", "apply", "carry out"),    # "test" is a noun
    ("Analysing a given program, students work out the bottleneck.", "analyse", "analyse"),        # inflected form
    ("The student categorises software defects by their root cause.", "analyse", "categorise"),
    ("Students can explain and apply the master theorem.", "apply", "apply"),                      # coordinated: the higher one
    ("Students will be able to deconstruct a network trace to explain a failed connection.", "analyse", "deconstruct"),
    ("Wenden Sie den Dijkstra-Algorithmus auf den folgenden Graphen an.", "apply", "anwenden"),     # separable verb
    ("Die Studierenden sind in der Lage, einen Debugger zur Fehlersuche einzusetzen.", "apply", "einsetzen"),
    ("Stellen Sie die beiden Architekturen einander gegenüber.", "analyse", "gegenüberstellen"),
    ("Stellen Sie den Ablauf des Quicksort-Algorithmus dar.", "understand", "darstellen"),
    ("Der Studierende definiert den Begriff der Komplexitätsklasse.", "remember", "definieren"),   # conjugated
    ("Erläutern Sie, warum Mergesort n log n Vergleiche benötigt.", "understand", "erläutern"),     # "Vergleiche" is a noun
    ("Die Studierenden können Algorithmen erklären und implementieren.", "apply", "implementieren"),
    ("Die Studierenden nehmen zu einer Architekturentscheidung kritisch Stellung.", "evaluate", "Stellung nehmen"),
])
def test_main_demand_is_found_across_sentence_structures(text, level, verb):
    assert classify_text(text) == (level, verb)


def test_questions_without_an_action_verb_are_read_by_their_form_and_unknown_stays_unknown():
    assert classify_detail("What is the worst-case running time of insertion sort?")["method"] == "question_form"
    assert _rules("Was ist die Laufzeit von Insertionsort im schlechtesten Fall?") == "remember"
    assert _rules("Why does quicksort degrade on sorted input?") == "understand" and _rules("Warum ist Hashing im Mittel schnell?") == "understand"
    assert classify_text("Memory management in operating systems.") == (None, None)             # no demand stated: no level invented
    assert classify_text("") == (None, None)


def test_several_sentences_give_the_highest_level_reached():
    assert _rules("Which of the two hashing schemes would you choose for a small device? Give reasons.") == "evaluate"
    assert _rules("Students list the layers of the OSI model. They design a protocol on top of them.") == "create"


def test_ambiguous_verbs_are_flagged_with_the_chosen_level():
    detail = classify_detail("Students compare arrays and linked lists with respect to access time.")
    assert detail["level"] == "understand" and detail["verb"] == "compare" and detail["ambiguous"] is True
    assert classify_detail("Students can implement binary search.")["ambiguous"] is False
    assert {"compare", "develop", "write", "vergleichen"} <= AMBIGUOUS_VERBS


# ── model-assisted classification ────────────────────────────────────────────

class _Model:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def invoke(self, messages, **kw):
        self.prompts.append(messages[-1].content)
        if isinstance(self.reply, Exception):
            raise self.reply
        return NS(content=self.reply if isinstance(self.reply, str) else json.dumps(self.reply))


def test_hybrid_asks_the_model_only_for_what_the_rules_leave_open():
    texts = ["Students can implement binary search.", "Students gain an understanding of memory management.",
             "Sketch the state of the heap after each insertion."]
    model = _Model({"items": [{"n": 1, "level": "understand", "verb": "understand"}, {"n": 2, "level": "apply", "verb": "sketch"}]})
    details = classify_hybrid(texts, model)
    assert [d["level"] for d in details] == ["apply", "understand", "apply"]
    assert [d["method"] for d in details] == ["action_verb", "model", "model"]
    assert len(model.prompts) == 1 and "implement binary search" not in model.prompts[0]      # one call, only the open items
    assert "1. Students gain" in model.prompts[0] and "2. Sketch" in model.prompts[0]
    silent = _Model({"items": []})
    assert classify_hybrid(["Students can implement binary search."], silent)[0]["method"] == "action_verb" and silent.prompts == []


def test_hybrid_can_also_put_ambiguous_verbs_to_the_model_and_keeps_the_rule_level_on_record():
    model = _Model({"items": [{"n": 1, "level": "analyse", "verb": "compare"}]})
    detail = classify_hybrid(["Students compare two sorting algorithms regarding their complexity."], model, include_ambiguous=True)[0]
    assert detail["level"] == "analyse" and detail["method"] == "model" and detail["rule_level"] == "understand"


@pytest.mark.parametrize("reply", [
    "not json at all", "{\"items\": \"oops\"}", "{\"items\": [{\"n\": 1}]}", "{\"items\": [{\"n\": 1, \"level\": \"genius\"}]}",
    "{\"items\": [{\"n\": 7, \"level\": \"apply\"}]}", "{\"items\": [{\"n\": \"1\", \"level\": \"apply\"}]}", "[1, 2, 3]", "",
    "{\"items\": [null, 3, {\"level\": \"apply\"}]}", RuntimeError("provider down"),
])
def test_malformed_model_replies_leave_the_item_unclassified(reply):
    assert classify_many_with_llm(["Sketch the heap."], _Model(reply)) == {}
    assert classify_with_llm("Sketch the heap.", _Model(reply)) == (None, None)
    assert classify_hybrid(["Sketch the heap."], _Model(reply))[0]["level"] is None


def test_model_reply_is_validated_item_by_item():
    reply = "Here you go:\n```json\n" + json.dumps({"items": [
        {"n": 1, "level": "Analyze", "verb": "trace", "extra": "ignored"}, {"n": 2, "level": "nonsense"}, {"n": 3, "level": "create", "verb": ""}]}) + "\n```"
    answers = classify_many_with_llm(["a", "b", "c"], _Model(reply))
    assert answers == {0: ("analyse", "trace"), 2: ("create", None)}                           # the invalid one is dropped, not guessed


def test_extraction_uses_the_model_fallback_only_in_live_mode(monkeypatch):
    from services import course_model
    import knowledge.bloom_classifier as bloom
    items = [NS(text="Sketch the heap.", bloom_level=None, bloom_verb=None), NS(text="Trace quicksort.", bloom_level=None)]
    calls = []
    monkeypatch.setattr(bloom, "classify_many_with_llm", lambda texts, llm=None: calls.append(texts) or {0: ("apply", "sketch")})
    assert asyncio.run(course_model._classify_rest("c", items)) == 0 and calls == []             # test mode: no model call
    monkeypatch.setattr(settings, "runtime_mode", "live")
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test-key-for-readiness-check")
    assert asyncio.run(course_model._classify_rest("c", items)) == 1
    assert calls == [["Sketch the heap.", "Trace quicksort."]] and (items[0].bloom_level, items[0].bloom_verb) == ("apply", "sketch")
    assert items[1].bloom_level is None                                                         # not classified by the model: stays open
    monkeypatch.setattr(settings, "bloom_llm_fallback", False)
    assert asyncio.run(course_model._classify_rest("c", items)) == 0 and len(calls) == 1
