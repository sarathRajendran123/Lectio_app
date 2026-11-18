"""Phase 1: Stakeholder quality gate, structured constraints, course intent propagation, append-only trace, per-finding trace."""
import asyncio
import json
import time
import uuid
from types import SimpleNamespace as NS

import httpx
import pytest
from sqlalchemy import select, text

from config import settings
from services import stakeholder_gate, trace
from services import constraints as lecturer_constraints
from test_multilingual_model import _upload

API = "/api/v1"


def _course(client, headers, code):
    course = client.post(f"{API}/courses", headers=headers, json={"code": code, "title": "Algorithms"}).json()["id"]
    base = f"{API}/courses/{course}"
    for name, kind, mime in [("syllabus.md", "syllabus", "text/markdown"), ("lecture_slides.txt", "slides", "text/plain"),
                             ("lecture_transcript.vtt", "transcript", "text/vtt"), ("exam.txt", "exam", "text/plain")]:
        _upload(client, headers, base, "en_algorithms", name, kind, mime)
    return course, base


def _audit(client, headers, base):
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    for _ in range(600):
        if client.get(f"{API}/runs/{run}", headers=headers).json()["status"] != "running":
            break
        time.sleep(.1)
    return run


async def _drop_trace_guards(db):
    """What a database owner could do: remove the append-only triggers (names differ per engine, see trace.install_guards)."""
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("DROP TRIGGER IF EXISTS trace_events_guard ON trace_events"))
    else:
        await db.execute(text("DROP TRIGGER IF EXISTS trace_events_no_update"))
        await db.execute(text("DROP TRIGGER IF EXISTS trace_events_no_delete"))


def _events(client, headers, run, kind=None):
    data = client.get(f"{API}/runs/{run}/trace", headers=headers).json()
    return [e for e in data["events"] if kind is None or e["event_type"] == kind], data["integrity"]


@pytest.fixture(scope="module")
def audited(client, headers):
    course, base = _course(client, headers, "P1-GOV")
    intent = client.put(base + "/intent", headers=headers, json={
        "goals": "Students can analyse and compare search and hashing algorithms.", "cognitive_levels": ["understand", "apply", "analyse"],
        "audience": "Second-year computer science students", "scope": "Searching, hashing and graph traversal",
        "constraints": "Keep examples in Python."}).json()
    run = _audit(client, headers, base)
    return {"course": course, "base": base, "run": run, "intent": intent}


# ── course intent and goal propagation ───────────────────────────────────────

def test_intent_is_versioned_and_never_edited(client, headers):
    course = client.post(f"{API}/courses", headers=headers, json={"code": "P1-INT", "title": "Intent"}).json()["id"]
    base = f"{API}/courses/{course}"
    assert client.get(base + "/intent", headers=headers).json()["intent"] is None
    first = client.put(base + "/intent", headers=headers, json={"goals": "Explain sorting algorithms clearly.", "cognitive_levels": ["understand"]}).json()
    second = client.put(base + "/intent", headers=headers, json={"goals": "Apply sorting algorithms to real data.", "cognitive_levels": ["apply"]}).json()
    assert (first["version"], second["version"]) == (1, 2) and first["id"] != second["id"]
    data = client.get(base + "/intent", headers=headers).json()
    assert data["intent"]["goals"].startswith("Apply") and [h["version"] for h in data["history"]] == [2, 1]
    assert client.put(base + "/intent", headers=headers, json={"goals": "short"}).status_code == 422
    assert client.put(base + "/intent", headers=headers, json={"goals": "A long enough goal text.", "cognitive_levels": ["guess"]}).status_code == 422


def test_every_agent_task_carries_the_active_intent(audited, client, headers):
    ref = {"id": audited["intent"]["id"], "version": audited["intent"]["version"]}
    created, _ = _events(client, headers, audited["run"], "audit_created")
    assert created and created[0]["payload"]["intent"] == ref
    messages, _ = _events(client, headers, audited["run"], "agent_message")
    targets = {m["payload"]["to"] for m in messages}
    assert {"metadata_content_agent", "content_assessment_agent", "metadata_assessment_agent", "content_delivery_agent", "stakeholder_agent"} <= targets
    assert all(m["payload"]["intent"] == ref for m in messages)          # every hand-over names the intent
    done, _ = _events(client, headers, audited["run"], "agent_complete")
    agents = {e["agent"] for e in done}
    assert {"course_director", "metadata_content_agent", "content_assessment_agent", "metadata_assessment_agent",
            "content_delivery_agent", "stakeholder_agent"} <= agents
    assert all(e["payload"]["intent"] == ref for e in done)


def test_changed_intent_reaches_later_runs_and_history_keeps_the_old_one(audited, client, headers):
    old = {"id": audited["intent"]["id"], "version": audited["intent"]["version"]}
    new = client.put(audited["base"] + "/intent", headers=headers, json={
        "goals": "Students can evaluate algorithm choices for a given workload.", "cognitive_levels": ["evaluate"]}).json()
    later = _audit(client, headers, audited["base"])
    done, _ = _events(client, headers, later, "agent_complete")
    assert done and all(e["payload"]["intent"] == {"id": new["id"], "version": new["version"]} for e in done)
    before, _ = _events(client, headers, audited["run"], "agent_complete")
    assert all(e["payload"]["intent"] == old for e in before)             # the earlier run still records what it used


def test_intent_and_constraints_are_in_the_model_context():
    from agents.graph.state import AlignmentResult
    from agents.live_review import _compute
    from rag.chunking.chunk_models import RetrievedChunk
    seen = {}

    class Agent:
        def _retrieve(self, *a, **k): return [RetrievedChunk("real", "Real source excerpt", .8, "a", "slides", "c", 1, None, None, None)]
        def _invoke(self, system, human, **k):
            seen["human"] = human
            return json.dumps({"findings": [], "limitations": "none"}), 3
        def _parse_json(self, t): return json.loads(t)
    intent = {"id": "i1", "version": 4, "goals": "Analyse hashing trade-offs.", "cognitive_levels": ["analyse"], "audience": "", "scope": "", "constraints": ""}
    rules = [{"id": "c1", "kind": "avoid", "scope": "course", "text": "No multiple-choice questions."}]
    state = {"run_id": "r", "course_id": "c", "modules": [], "course_metadata": {"title": "T"}, "course_intent": intent,
             "lecturer_constraints": rules, "guidance": lecturer_constraints.guidance(intent, rules),
             "alignment_results": {"metadata_content": AlignmentResult("a", "metadata_content", .9, "pass")}}
    _compute(Agent(), state, "metadata_content")
    assert "COURSE INTENT (version 4" in seen["human"] and "Analyse hashing trade-offs." in seen["human"]
    assert "No multiple-choice questions." in seen["human"]


# ── structured lecturer constraints ──────────────────────────────────────────

def test_decisions_become_constraints_and_history_is_kept(audited, client, headers):
    base = audited["base"]
    drafts = client.post(base + "/generate", headers=headers, json={"content_type": "exercise", "purpose": "Practice hash table collisions", "alternatives": 2}).json()
    assert all(d["rationale"] and "quality" in d for d in drafts)          # every variant comes with its reason
    rejected, revised = drafts
    assert client.post(f"{API}/approvals/{rejected['id']}/reject", headers=headers, json="Too long; keep exercises under ten minutes.").status_code == 200
    assert client.post(f"{API}/approvals/{revised['id']}/revise", headers=headers,
                       json={"revision": "Shorter exercise text.", "comment": "Use Python in every example."}).status_code == 200
    data = client.get(base + "/constraints", headers=headers).json()
    active = {c["text"]: c for c in data["active"]}
    avoid = active["Too long; keep exercises under ten minutes."]
    assert avoid["kind"] == "avoid" and avoid["scope"] == "course" and avoid["source_id"] == rejected["id"] and avoid["decision"] == "rejected"
    assert active["Use Python in every example."]["kind"] == "prefer"
    # a new rule replaces the old one without deleting it
    newer = client.post(base + "/constraints", headers=headers, json={"text": "Keep exercises under fifteen minutes.", "kind": "avoid",
                                                                      "supersedes_id": avoid["id"]}).json()
    general = client.post(base + "/constraints", headers=headers, json={"text": "Write in British English.", "kind": "require", "scope": "general"}).json()
    data = client.get(base + "/constraints", headers=headers).json()
    texts = [c["text"] for c in data["active"]]
    assert "Too long; keep exercises under ten minutes." not in texts and newer["text"] in texts and general["text"] in texts
    assert any(c["id"] == avoid["id"] for c in data["history"])            # superseded, still on record
    assert texts.index(general["text"]) < texts.index(newer["text"])       # course-specific rules come last, so they win
    retired = client.post(base + f"/constraints/{general['id']}/retire", headers=headers)
    assert retired.status_code == 201
    data = client.get(base + "/constraints", headers=headers).json()
    assert general["text"] not in [c["text"] for c in data["active"]] and any(c["id"] == general["id"] for c in data["history"])
    # general rules follow the lecturer to another course; course rules do not
    client.post(base + "/constraints", headers=headers, json={"text": "Cite the slide number.", "kind": "require", "scope": "general"})
    other = client.post(f"{API}/courses", headers=headers, json={"code": "P1-OTHER", "title": "Other"}).json()["id"]
    elsewhere = [c["text"] for c in client.get(f"{API}/courses/{other}/constraints", headers=headers).json()["active"]]
    assert "Cite the slide number." in elsewhere and newer["text"] not in elsewhere


def test_a_rejected_draft_is_not_offered_again_as_if_new(audited, client, headers):
    base = audited["base"]
    body = {"content_type": "exercise", "purpose": "Practice binary search on sorted arrays", "alternatives": 1}
    first = client.post(base + "/generate", headers=headers, json=body).json()[0]
    assert first["quality"]["passed"] is True
    client.post(f"{API}/approvals/{first['id']}/reject", headers=headers, json="Not suitable for this cohort.")
    again = client.post(base + "/generate", headers=headers, json=body).json()[0]   # test mode regenerates the same text
    assert again["quality"]["passed"] is False and again["quality"]["attempts"] == settings.quality_max_retries + 1
    assert any("already rejected" in issue for issue in again["quality"]["issues"])
    assert "did NOT pass" in again["rationale"]


def test_guidance_text_separates_general_and_course_rules():
    rules = [{"id": "1", "kind": "require", "scope": "general", "text": "British English."},
             {"id": "2", "kind": "avoid", "scope": "course", "text": "No recursion."},
             {"id": "3", "kind": "avoid", "scope": "course", "text": lecturer_constraints.NO_REASON}]
    block = lecturer_constraints.block(rules)
    assert "Required (general): British English." in block and "Avoid (this course): No recursion." in block
    assert lecturer_constraints.NO_REASON not in block
    assert lecturer_constraints.content_fingerprint("Hello,  World!") == lecturer_constraints.content_fingerprint("hello world")


# ── Stakeholder quality gate ─────────────────────────────────────────────────

CITED = [{"citation": "slides.txt, slide 3", "quote": "Hash tables resolve collisions by chaining."}]
GOOD = ("Question: Explain how a hash table resolves collisions by chaining and compare it with open addressing. "
        "Marks: 6. Marking criteria: names both methods, describes the linked list per slot, states the effect on lookup cost.")
TARGET = "Topic 'Hash tables and collision handling' has lecture content but no assessment questions."


def test_gate_scores_good_and_weak_drafts():
    good = stakeholder_gate.assess(GOOD, CITED, content_type="quiz", target=TARGET, intent=None)
    assert good["passed"] and good["score"] >= .9 and good["checks"]["intent_stated"] is False
    uncited = stakeholder_gate.assess(GOOD, [], content_type="quiz", target=TARGET, intent=None)
    assert not uncited["passed"] and any("cites no source" in i for i in uncited["issues"])
    short = stakeholder_gate.assess("Too short.", CITED, content_type="quiz", target=TARGET, intent=None)
    assert not short["passed"]
    off_topic = stakeholder_gate.assess("Question: Describe photosynthesis in green plants and the role of chlorophyll in capturing sunlight for energy?",
                                        CITED, content_type="quiz", target=TARGET, intent=None)
    assert off_topic["checks"]["relevance"] < .5 and not off_topic["passed"]
    assert any("low word overlap" in i for i in off_topic["issues"])
    wrong_level = stakeholder_gate.assess("Students will be able to design a new hash table collision handling scheme for large tables and justify it.",
                                          CITED, content_type="clo", target=TARGET, intent={"cognitive_levels": ["remember", "understand"]})
    assert wrong_level["checks"]["intent"] < 1 and any("course intent asks for" in i for i in wrong_level["issues"])


def test_low_cross_language_overlap_requires_review_instead_of_false_pass():
    target = "Students can identify privacy challenges and explain societal risks."
    draft = "Die Studierenden können gesellschaftliche Auswirkungen kritisch erläutern und Verantwortung bewerten."
    result = stakeholder_gate.assess(draft, CITED, content_type="clo", target=target, intent=None)
    assert result["checks"]["relevance"] < .5
    assert result["passed"] is False
    assert any("across languages" in issue for issue in result["issues"])


def _capture(monkeypatch):
    events = []
    monkeypatch.setattr(trace, "emit", lambda kind, payload=None, **kw: events.append((kind, payload or {}, kw)) or "id")
    return events


def test_gate_retries_weak_output_with_adjusted_instructions_and_another_model(monkeypatch):
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 2)
    calls = []

    def generate(extra, model):
        calls.append((extra, model))
        return NS(content="Too short." if len(calls) == 1 else GOOD, citations=CITED, model=model, tokens_used=5)
    item, review = stakeholder_gate.produce(generate, content_type="quiz", target=TARGET, intent=None, constraint_ids=["c1"],
                                            rejected_fingerprints=set(), guidance="COURSE INTENT: analyse.", models=["model-a", "model-b"])
    assert review["passed"] and review["attempts"] == 2 and item.content == GOOD
    assert calls[0] == ("COURSE INTENT: analyse.", "model-a")
    assert calls[1][1] == "model-b" and "COURSE INTENT: analyse." in calls[1][0] and "QUALITY REVIEW" in calls[1][0]   # the retry keeps the intent
    kinds = [k for k, _, _ in events]
    assert kinds == ["quality_check", "retry", "quality_check"]
    assert events[1][1]["reason"] and events[1][1]["switched_model"] is True and events[0][1]["constraint_ids"] == ["c1"]


def test_gate_stops_at_the_retry_limit_and_never_claims_a_pass(monkeypatch):
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 2)
    calls = []
    item, review = stakeholder_gate.produce(lambda extra, model: calls.append(1) or NS(content="Too short.", citations=[], model="m", tokens_used=1),
                                            content_type="quiz", target=TARGET, intent=None, constraint_ids=[], rejected_fingerprints=set())
    assert len(calls) == 3 and review["attempts"] == 3 and review["passed"] is False
    assert "did NOT pass" in review["rationale"]
    assert [k for k, _, _ in events].count("retry") == 2
    monkeypatch.setattr(settings, "quality_max_retries", 0)
    calls.clear()
    stakeholder_gate.produce(lambda extra, model: calls.append(1) or NS(content="Too short.", citations=[], model="m", tokens_used=1),
                             content_type="quiz", target=TARGET, intent=None, constraint_ids=[], rejected_fingerprints=set())
    assert len(calls) == 1                                                  # zero retries means exactly one attempt


def test_gate_records_failed_generations_and_raises_only_if_nothing_was_produced(monkeypatch):
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 1)
    with pytest.raises(ValueError):
        stakeholder_gate.produce(lambda extra, model: (_ for _ in ()).throw(ValueError("no evidence")), content_type="quiz", target=TARGET,
                                 intent=None, constraint_ids=[], rejected_fingerprints=set())
    assert [k for k, _, _ in events] == ["quality_check", "retry", "quality_check"]
    assert all(p["passed"] is False for k, p, _ in events if k == "quality_check")


def test_quote_mismatch_retry_requests_source_specific_excerpt_id(monkeypatch):
    _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 1)
    calls = []
    def generate(extra, model):
        calls.append(extra)
        if len(calls) == 1:
            raise ValueError("Generated quotation does not occur verbatim in its cited source.")
        return NS(content=GOOD, citations=CITED, model=model, tokens_used=5)
    item, review = stakeholder_gate.produce(generate, content_type="quiz", target=TARGET,
        intent=None, constraint_ids=[], rejected_fingerprints=set(), models=["a", "b"])
    assert review["passed"] and item.content == GOOD
    assert "offered excerpt ID" in calls[1] and "do not copy or paraphrase" in calls[1]


# ── model-call logging ───────────────────────────────────────────────────────

def test_every_model_call_is_logged_without_prompt_text_or_secrets(monkeypatch, tmp_path):
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.openrouter import LLMError, OpenRouterChat
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "artifact_storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-super-secret-value")
    monkeypatch.setattr(settings, "openrouter_fallback_model", "fallback/model:free")
    monkeypatch.setattr(settings, "llm_retry_wait_seconds", 0)
    req = httpx.Request("POST", "http://x")
    ok = httpx.Response(200, request=req, json={"choices": [{"message": {"content": "answer"}}],
                                                "usage": {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49, "cost": 0}})
    queue = [httpx.Response(429, request=req), ok]
    monkeypatch.setattr(httpx, "post", lambda url, **kw: queue.pop(0))
    chat = OpenRouterChat(model="primary/model:free", prompt_version="audit-review/3")
    msgs = [SystemMessage(content="system rules"), HumanMessage(content="CONFIDENTIAL course text about hashing")]
    assert chat.invoke(msgs).content == "answer"
    assert chat.invoke(msgs).content == "answer"                           # served from cache, still logged
    calls = [p for k, p, _ in events if k == "model_call"]
    assert [(c["model"], c["outcome"], c["attempt"], c["cached"]) for c in calls] == [
        ("primary/model:free", "error", 1, False), ("fallback/model:free", "ok", 2, False), ("fallback/model:free", "ok", 0, True)]
    good = calls[1]
    assert good["provider"] == "openrouter" and good["prompt_version"] == "audit-review/3" and len(good["prompt_fingerprint"]) == 64
    assert (good["tokens_in"], good["tokens_out"], good["tokens_total"], good["cost"]) == (40, 9, 49, 0)
    assert good["retry_reason"].startswith("previous attempt failed") and good["duration_ms"] >= 0 and calls[0]["error"] == "HTTP 429"
    assert calls[0]["prompt_fingerprint"] == calls[2]["prompt_fingerprint"]
    dumped = json.dumps(calls)
    assert "CONFIDENTIAL" not in dumped and "sk-or-super-secret-value" not in dumped and "system rules" not in dumped
    # a rejected answer is logged as rejected, not as a success
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(200, request=req, json={"choices": [{"message": {"content": "junk"}}]}))
    with pytest.raises(ValueError):
        OpenRouterChat(model="primary/model:free").invoke([HumanMessage(content="other")], validate=lambda raw: (_ for _ in ()).throw(ValueError("bad")))
    assert events[-1][1]["outcome"] == "rejected_by_validation"
    assert trace._clean({"api_key": "x", "password": "y", "tokens_in": 3}) == {"tokens_in": 3}


# ── append-only trace: ordering, linkage, integrity ──────────────────────────

def test_run_trace_is_ordered_linked_and_verifies(audited, client, headers):
    events, integrity = _events(client, headers, audited["run"])
    assert integrity["valid"] and integrity["events"] == len(events) and len(events) > 20
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    kinds = [e["event_type"] for e in events]
    for kind in ("audit_created", "agent_start", "agent_message", "tool_call", "agent_complete", "finding_recorded"):
        assert kind in kinds, kind
    starts = {}
    for e in events:
        if e["event_type"] == "agent_start":
            starts.setdefault(e["task_id"], []).append(e["seq"])
    for e in events:
        if e["event_type"] == "agent_complete":
            assert any(s < e["seq"] for s in starts[e["task_id"]])          # a step ends after it starts
    tools = [e for e in events if e["event_type"] == "tool_call"]
    assert all(e["task_id"] and e["agent"] for e in tools)                  # every tool call belongs to a task and an agent
    assert all("query_fingerprint" in e["payload"] and "query" not in e["payload"] for e in tools if e["payload"]["tool"] == "retrieve")
    assert {e["payload"]["tool"] for e in tools} == {"retrieve", "delivery_verification", "draft_plan"}   # draft_plan added 2026-11-16
    plan = next(e["payload"] for e in tools if e["payload"]["tool"] == "draft_plan")
    assert plan["drafts_planned"] <= plan["cap"] and plan["drafts_planned"] <= plan["findings_considered"]


def test_trace_refuses_update_and_delete_and_detects_tampering(client, headers):
    from db.models.governance import TraceEvent
    from db.session import AsyncSessionLocal
    chain = f"tamper-{uuid.uuid4()}"

    async def scenario():
        for n in range(3):
            await trace.aemit("unit_test", {"n": n}, run_id=chain)
        async with AsyncSessionLocal() as db:
            assert (await trace.verify_chain(db, chain)) == {"chain_key": chain, "valid": True, "events": 3, "head": (await trace.verify_chain(db, chain))["head"], "anchored_seq": None}
            row = (await db.scalars(select(TraceEvent).where(TraceEvent.chain_key == chain, TraceEvent.seq == 2))).one()
            row.payload = {"n": 99}
            with pytest.raises(trace.AppendOnlyViolation):
                await db.flush()                                            # the ORM refuses to change an event
            await db.rollback()
            with pytest.raises(trace.AppendOnlyViolation):
                await db.delete(row); await db.flush()
            await db.rollback()
            for statement in ("UPDATE trace_events SET event_type='x' WHERE chain_key=:c", "DELETE FROM trace_events WHERE chain_key=:c"):
                with pytest.raises(Exception, match="append-only"):
                    await db.execute(text(statement), {"c": chain})         # the database refuses plain SQL too
                await db.rollback()
            # Someone with database-owner rights drops the guard and edits a row: the chain exposes it.
            await _drop_trace_guards(db)
            await db.execute(text("UPDATE trace_events SET payload='{\"n\": 99}' WHERE chain_key=:c AND seq=2"), {"c": chain})
            await db.commit()
            broken = await trace.verify_chain(db, chain)
            assert broken["valid"] is False and broken["broken_at_seq"] == 2
            conn = await db.connection()
            await conn.run_sync(trace.install_guards)                       # put the guard back for the other tests
            await db.commit()
    asyncio.run(scenario())


# ── the Stakeholder agent's lecturer-facing view and per-finding trace ───────

def test_briefing_is_plain_language_with_evidence_and_uncertainty(audited, client, headers):
    data = client.get(audited["base"] + "/briefing", headers=headers).json()
    assert data["presented_by"] == "stakeholder_agent" and data["course_intent"]["goals"]
    assert len(data["checks"]) == 4 and data["findings"]
    for finding in data["findings"]:
        assert finding["what_was_found"] and finding["why_it_matters"] and finding["how_sure"] and finding["compares"]
        assert "_" not in finding["what_was_found"]                         # no internal identifiers in the lecturer text
        if not finding["evidence"]:
            assert finding["how_sure"].startswith("Low")                    # no evidence is said plainly
    for draft in data["drafts_waiting"]:
        assert draft["rationale"]


def test_each_finding_can_be_traced_from_intent_to_decision(audited, client, headers):
    reports = client.get(audited["base"] + "/reports", headers=headers).json()
    first_run = [r for r in reports if r["run_id"] == audited["run"]]
    report = next(r for r in first_run if r["gap_count"])
    gap = client.get(f"{API}/reports/{report['id']}", headers=headers).json()["gaps"][0]
    before = client.get(f"{API}/findings/{gap['id']}/trace", headers=headers).json()
    assert before["1_intent"]["used"]["id"] == audited["intent"]["id"]      # the intent active when it ran, not the current one
    assert before["integrity"]["valid"] and before["run_id"] == audited["run"]
    assert before["finding"]["what_was_found"] and before["6_result"]["report_type"] == report["report_type"]
    assert any(e["event_type"] == "finding_recorded" and e["subject_id"] == gap["id"] for e in before["4_decisions"])
    assert any(e["event_type"] == "agent_message" for e in before["4_decisions"])
    assert before["3_agents"] and before["summary"]["events"] > 0
    assert before["7_lecturer"]["finding_decisions"] == []
    r = client.post(f"{API}/reports/{report['id']}/findings/{gap['id']}/review", headers=headers,
                    json={"decision": "approved", "rationale": "Confirmed against the exam paper."})
    assert r.status_code == 200, r.text
    after = client.get(f"{API}/findings/{gap['id']}/trace", headers=headers).json()
    assert after["7_lecturer"]["finding_decisions"][0]["decision"] == "approved"
    assert any(e["event_type"] == "finding_decision" for e in after["4_decisions"] + after["5_model_calls_and_checks"]) or after["summary"]["events"] > before["summary"]["events"]
    assert after["integrity"]["valid"]
    assert client.get(f"{API}/findings/{uuid.uuid4()}/trace", headers=headers).status_code == 404


def test_draft_trace_links_review_decision_and_events(audited, client, headers):
    draft = client.post(audited["base"] + "/generate", headers=headers,
                        json={"content_type": "quiz", "purpose": "Quiz on graph traversal with BFS and DFS", "alternatives": 1}).json()[0]
    client.post(f"{API}/approvals/{draft['id']}/approve", headers=headers, json="Good.")
    data = client.get(f"{API}/approvals/{draft['id']}/trace", headers=headers).json()
    assert data["review"]["passed"] is True and data["review"]["rationale"] == draft["rationale"]
    kinds = [e["event_type"] for e in data["5_model_calls_and_checks"]]
    assert "quality_check" in kinds and data["7_lecturer"][0]["decision"] == "approved"
    assert data["2_evidence"] and data["integrity"]["valid"]


def test_exercise_with_no_student_question_fails_structure():
    result = stakeholder_gate.assess(
        'Gradient descent uses the negative gradient to adjust parameters and reduce a loss function.',
        CITED, content_type='exercise', target='Explain gradient descent', intent=None,
    )
    assert not result['passed']
    assert any('No question' in issue for issue in result['issues'])


def test_exercise_requested_answers_are_required_and_retryable():
    question = 'Question: How does gradient descent update model parameters to reduce the loss function?'
    target = 'Create a gradient descent exercise with suggested answers.'
    missing = stakeholder_gate.assess(question, CITED, content_type='exercise', target=target, intent=None)
    assert not missing['passed']
    assert any('requested suggested answers' in issue for issue in missing['issues'])
    complete = stakeholder_gate.assess(question + '\n\n### Suggested answers\nThe gradient guides the parameter update.',
                                       CITED, content_type='exercise', target=target, intent=None)
    assert complete['checks']['structure'] == 1.0
    no_request = stakeholder_gate.assess(question, CITED, content_type='exercise',
                                         target='Create a gradient descent exercise.', intent=None)
    assert not any('requested suggested answers' in issue for issue in no_request['issues'])


def test_requested_answers_in_constraints_are_checked():
    result = stakeholder_gate.assess(
        'Question: How does gradient descent update model parameters to reduce the loss function?',
        CITED, content_type='exercise', target='Practice gradient descent', intent=None,
        requirements='Include a model answer.',
    )
    assert not result['passed']
    assert any('requested suggested answers' in issue for issue in result['issues'])
