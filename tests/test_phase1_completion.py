"""Phase 1 completion: agent decisions and run end in the trace, anchors outside the database,
intent in the rule-based analysis, finding decisions as constraints, and the gate for Division 1 output."""
import asyncio
import json
import time
import uuid

import pytest
from sqlalchemy import select, text

from config import settings
from services import trace
from test_phase1_governance import API, _audit, _course, _events

DIMENSIONS = {"metadata_content", "content_assessment", "metadata_assessment", "content_delivery"}


def _wait_for(client, headers, run, kind):
    for _ in range(100):
        events, integrity = _events(client, headers, run)
        if any(e["event_type"] == kind for e in events):
            return events, integrity
        time.sleep(.1)
    raise AssertionError(f"no {kind} event")


@pytest.fixture(scope="module")
def audited(client, headers):
    course, base = _course(client, headers, "P1C-GOV")
    intent = client.put(base + "/intent", headers=headers, json={
        "goals": "Students can evaluate and design search and hashing algorithms.", "cognitive_levels": ["evaluate", "create"]}).json()
    run = _audit(client, headers, base)
    return {"course": course, "base": base, "run": run, "intent": intent}


# ── audit log: agent decisions, run end, anchors ─────────────────────────────

def test_agents_record_their_own_decisions_and_the_run_is_closed_and_anchored(audited, client, headers):
    events, integrity = _wait_for(client, headers, audited["run"], "run_finished")
    decisions = [e for e in events if e["event_type"] == "agent_decision"]
    assessed = {e["payload"]["dimension"]: e for e in decisions if e["payload"]["decision"] == "dimension_assessed"}
    assert set(assessed) == DIMENSIONS
    assert all(e["agent"] and e["task_id"] and "status" in e["payload"] for e in assessed.values())
    raised = {e["subject_id"]: e for e in decisions if e["payload"]["decision"] == "finding_raised"}
    recorded = [e for e in events if e["event_type"] == "finding_recorded"]
    assert recorded
    for e in recorded:                                   # every stored finding was first decided by the agent that produced it
        own = raised[e["subject_id"]]
        assert own["seq"] < e["seq"] and own["agent"] == e["payload"]["source_agent"]
        assert own["payload"]["basis"] in ("rule_based_check", "model_review") and own["payload"]["gap_type"] == e["payload"]["gap_type"]
    finished = [e for e in events if e["event_type"] == "run_finished"]
    assert len(finished) == 1 and finished[0]["payload"]["status"] in ("completed", "waiting_for_human", "needs_review")
    for _ in range(50):                                  # the anchor is written right after the closing event
        integrity = client.get(f"{API}/runs/{audited['run']}/trace/verify", headers=headers).json()
        if integrity.get("anchored_seq"):
            break
        time.sleep(.1)
    assert integrity["valid"] and integrity["anchored_seq"] >= finished[0]["seq"]


def test_finding_trace_shows_only_that_findings_decisions(audited, client, headers):
    reports = [r for r in client.get(audited["base"] + "/reports", headers=headers).json() if r["run_id"] == audited["run"]]
    report = next(r for r in reports if r["gap_count"] > 1)
    gaps = client.get(f"{API}/reports/{report['id']}", headers=headers).json()["gaps"]
    data = client.get(f"{API}/findings/{gaps[0]['id']}/trace", headers=headers).json()
    about_gaps = [e for e in data["4_decisions"] if e["subject_type"] == "gap"]
    assert about_gaps and all(e["subject_id"] == gaps[0]["id"] for e in about_gaps)
    assert any(e["event_type"] == "agent_decision" and e["payload"]["decision"] == "finding_raised" for e in about_gaps)
    assert any(e["event_type"] == "agent_decision" and e["payload"]["decision"] == "dimension_assessed" for e in data["4_decisions"])


def test_lecturer_draft_requests_are_logged_on_the_course_chain(audited, client, headers):
    client.post(audited["base"] + "/generate", headers=headers, json={"content_type": "exercise", "purpose": "Practise open addressing in hash tables", "alternatives": 1})
    data = client.get(audited["base"] + "/trace", headers=headers).json()
    kinds = [e["event_type"] for e in data["events"]]
    assert data["integrity"]["valid"] and "intent_updated" in kinds
    request = next(e for e in data["events"] if e["event_type"] == "draft_requested")
    assert request["agent"] == "lecturer" and request["payload"]["intent"]["id"] == audited["intent"]["id"]
    assert "purpose" not in request["payload"] and len(request["payload"]["purpose_fingerprint"]) == 16   # the text itself is not stored
    order = [k for k in kinds if k in ("draft_requested", "tool_call", "quality_check", "draft_queued")]
    assert order[:2] == ["draft_requested", "tool_call"] and order.index("quality_check") < order.index("draft_queued")
    anchored = client.post(audited["base"] + "/trace/anchor", headers=headers).json()
    assert any(a["chain_key"] == f"course:{audited['course']}" for a in anchored["anchored"])
    assert client.get(audited["base"] + "/trace/verify", headers=headers).json()["anchored_seq"] == len(data["events"])


def test_anchor_exposes_removed_tail_and_a_consistently_rewritten_chain(client, headers):
    from db.models.governance import TraceEvent
    from db.session import AsyncSessionLocal

    async def scenario():
        cut, rewritten = f"cut-{uuid.uuid4()}", f"rewrite-{uuid.uuid4()}"
        for chain in (cut, rewritten):
            for n in range(3):
                await trace.aemit("unit_test", {"n": n}, run_id=chain)
        async with AsyncSessionLocal() as db:
            for chain in (cut, rewritten):
                entry = await trace.anchor(db, chain)
                assert entry["seq"] == 3 and (await trace.anchor(db, chain)) == entry       # the same head is not written twice
                assert (await trace.verify_chain(db, chain))["anchored_seq"] == 3
            await trace.aemit("unit_test", {"n": 3}, run_id=cut)                            # later events do not disturb an anchor
            assert (await trace.verify_chain(db, cut))["valid"]
            # A database owner removes the guards.
            await db.execute(text("DROP TRIGGER trace_events_no_update"))
            await db.execute(text("DROP TRIGGER trace_events_no_delete"))
            # 1. Cut events off the end: the remaining chain is internally consistent, only the anchor shows it.
            await db.execute(text("DELETE FROM trace_events WHERE chain_key=:c AND seq>=3"), {"c": cut})
            # 2. Change the last event and recompute its hash so the chain still links.
            row = (await db.scalars(select(TraceEvent).where(TraceEvent.chain_key == rewritten, TraceEvent.seq == 3))).one()
            body = {**trace._body(row), "payload": {"n": 99}}
            await db.execute(text("UPDATE trace_events SET payload=:p, hash=:h WHERE chain_key=:c AND seq=3"),
                             {"p": json.dumps({"n": 99}), "h": trace._event_hash(row.prev_hash, body), "c": rewritten})
            await db.commit()
            db.expire_all()
            removed = await trace.verify_chain(db, cut)
            assert removed["valid"] is False and "removed from the end" in removed["reason"] and removed["broken_at_seq"] == 3
            changed = await trace.verify_chain(db, rewritten)
            assert changed["valid"] is False and "rewritten" in changed["reason"]
            conn = await db.connection()
            await conn.run_sync(trace.install_guards)
            await db.commit()
    asyncio.run(scenario())


# ── course intent inside the rule-based analysis ─────────────────────────────

def test_rule_based_checks_compare_the_intended_levels_with_objectives_and_questions():
    from agents.audit_checks import _intent_checks
    from agents.graph.state import AlignmentResult
    intent = {"id": "i1", "version": 3, "cognitive_levels": ["apply", "evaluate"]}
    objectives = [{"id": "o1", "text": "Students can implement binary search.", "bloom_level": None},
                  {"id": "o2", "text": "Students can explain hashing.", "bloom_level": "understand"}]
    assessments = [{"id": "a1", "questions": [{"id": "q1", "text": "Justify the choice of a hash function.", "bloom_level": None}]}]
    state = {"course_id": "c", "course_intent": intent}
    described = AlignmentResult("metadata_content_agent", "metadata_content", .9, "pass")
    _intent_checks(state, "metadata_content", described, objectives, assessments)
    assert described.findings["course_intent"] == {"id": "i1", "version": 3}
    assert described.findings["intent_check"]["levels_found"] == ["understand", "apply"] and described.findings["intent_check"]["not_reflected"] == ["evaluate"]
    assert [g.gap_type for g in described.gaps] == ["intent_level_without_objective"]
    assert "'evaluate'" in described.gaps[0].description and "version 3" in described.gaps[0].description and described.overall_score == .9
    assessed = AlignmentResult("metadata_assessment_agent", "metadata_assessment", .9, "pass")
    _intent_checks(state, "metadata_assessment", assessed, objectives, assessments)
    assert [g.gap_type for g in assessed.gaps] == ["intent_level_not_assessed"] and "'apply'" in assessed.gaps[0].description
    # no intent: said plainly, nothing invented; a dimension that could not be assessed gets no intent finding
    silent = AlignmentResult("metadata_content_agent", "metadata_content", .9, "pass")
    _intent_checks({"course_id": "c", "course_intent": None}, "metadata_content", silent, objectives, assessments)
    assert not silent.gaps and silent.findings["course_intent"] is None and "No course intent" in silent.findings["intent_notice"]
    unscored = AlignmentResult("metadata_assessment_agent", "metadata_assessment", 0., "needs_review")
    _intent_checks(state, "metadata_assessment", unscored, objectives, [])
    assert not unscored.gaps


def _report(client, headers, base, run, dimension):
    listed = next(r for r in client.get(base + "/reports", headers=headers).json() if r["run_id"] == run and r["report_type"] == dimension)
    return client.get(f"{API}/reports/{listed['id']}", headers=headers).json()


def test_audit_reports_intended_levels_the_course_does_not_reach(audited, client, headers):
    report = _report(client, headers, audited["base"], audited["run"], "metadata_content")
    inner = report["findings"]["findings"]
    assert inner["course_intent"] == {"id": audited["intent"]["id"], "version": audited["intent"]["version"]}
    check = inner["intent_check"]
    assert check["intended_levels"] == ["evaluate", "create"] and check["not_reflected"]       # the sample course stays below these levels
    raised = [g for g in report["gaps"] if g["gap_type"] == "intent_level_without_objective"]
    assert len(raised) == len(check["not_reflected"])
    briefing = client.get(audited["base"] + "/briefing", headers=headers).json()
    plain = next(f for f in briefing["findings"] if f["gap_id"] == raised[0]["id"])
    assert "course intent" in plain["what_was_found"] and plain["how_sure"].startswith("Low to moderate")


# ── finding decisions as constraints ─────────────────────────────────────────

def test_a_dismissed_finding_is_marked_not_raised_as_new_until_the_rule_is_retired(audited, client, headers):
    base = audited["base"]
    report = _report(client, headers, base, audited["run"], "metadata_content")
    gap = next(g for g in report["gaps"] if g["gap_type"] == "intent_level_without_objective")
    other = next(g for g in report["gaps"] if g["id"] != gap["id"])
    done = client.post(f"{API}/reports/{report['id']}/findings/{gap['id']}/review", headers=headers,
                       json={"decision": "rejected", "rationale": "This level is covered in the lab course."}).json()
    assert done["constraint_id"]
    revised = client.post(f"{API}/reports/{report['id']}/findings/{other['id']}/review", headers=headers,
                          json={"decision": "revised", "rationale": "", "revised_recommendation": "Move the topic to the reading list."}).json()
    approved = client.post(f"{API}/reports/{report['id']}/findings/{other['id']}/review", headers=headers, json={"decision": "approved"}).json()
    assert revised["constraint_id"] and approved["constraint_id"] is None        # agreeing with a finding creates no rule
    rules = {c["id"]: c for c in client.get(base + "/constraints", headers=headers).json()["active"]}
    rule = rules[done["constraint_id"]]
    assert rule["kind"] == "avoid" and rule["source_type"] == "finding_decision" and rule["source_id"] == gap["id"]
    assert "lab course" in rule["text"] and rules[revised["constraint_id"]]["kind"] == "prefer"
    assert "reading list" in rules[revised["constraint_id"]]["text"]

    second = _audit(client, headers, base)
    again = _report(client, headers, base, second, "metadata_content")
    stored = {g["gap_id"]: g for g in again["findings"]["gaps"]}
    same = [g for g in again["gaps"] if g["gap_type"] == gap["gap_type"] and g["description"] == gap["description"]]
    assert len(same) == 1 and same[0]["severity"] == "info" and "dismissed this finding before" in same[0]["recommendation"]
    assert stored[same[0]["id"]]["dismissed_by"] == done["constraint_id"]
    untouched = [g for g in again["gaps"] if g["gap_type"] == gap["gap_type"] and g["id"] != same[0]["id"]]
    assert all(g["severity"] == "warning" for g in untouched)                    # other levels are still raised
    decisions, _ = _events(client, headers, second, "agent_decision")
    assert any(e["subject_id"] == same[0]["id"] and e["payload"]["previously_dismissed_by"] == done["constraint_id"] for e in decisions)
    briefing = client.get(base + "/briefing", headers=headers).json()
    assert next(f for f in briefing["findings"] if f["gap_id"] == same[0]["id"])["previously_dismissed"] is True
    drafts = client.get(f"{API}/approvals", headers=headers, params={"course_id": audited["course"]}).json()
    assert drafts and all("rationale" in d and "quality" in d for d in drafts)   # the gate's verdict travels with every draft

    assert client.post(base + f"/constraints/{done['constraint_id']}/retire", headers=headers).status_code == 201
    third = _audit(client, headers, base)
    back = [g for g in _report(client, headers, base, third, "metadata_content")["gaps"] if g["description"] == gap["description"]]
    assert len(back) == 1 and back[0]["severity"] == "warning"                   # reinstated once the rule is retired


def test_finding_identity_survives_changing_scores_and_differs_between_items():
    from services.constraints import finding_fingerprint as fp
    assert fp("topic_shallow_coverage", None, "Week 3 topic 'Hashing' has low coverage (score=0.41).") == \
        fp("topic_shallow_coverage", None, "Week 3 topic 'Hashing' has low coverage (score=0.37).")
    assert fp("clo_not_assessed", "id-1", "x") == fp("clo_not_assessed", "id-1", "different wording")
    assert fp("clo_not_assessed", "id-1") != fp("clo_not_assessed", "id-2") and fp("clo_not_assessed", "id-1") != fp("clo_not_covered", "id-1")


# ── the gate for Division 1 output, and model reassignment for automatic drafts ──

def _capture(monkeypatch):
    events = []
    monkeypatch.setattr(trace, "emit", lambda kind, payload=None, **kw: events.append((kind, payload or {}, kw)) or "id")
    return events


def _flaky_agent(failures):
    from agents.base_agent import BaseAgent
    from agents.graph.state import AlignmentResult

    class Flaky(BaseAgent):
        name = "content_assessment_agent"
        calls = 0

        def run(self, state):
            Flaky.calls += 1
            if Flaky.calls <= failures:
                raise RuntimeError("retrieval backend unavailable")
            return {**state, "alignment_results": {"content_assessment": AlignmentResult(self.name, "content_assessment", .8, "pass")}}

        def _run_async(self, coro):
            coro.close()
    return Flaky


def test_a_failed_division_step_is_retried_before_it_is_reported(monkeypatch):
    from agents.graph.workflow import execute_agent
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 1)
    state = {"run_id": str(uuid.uuid4()), "course_id": str(uuid.uuid4()), "modules": [], "assessments": []}
    agent = _flaky_agent(1)
    out = execute_agent(agent(), state, "content_assessment")
    result = out["alignment_results"]["content_assessment"]
    assert agent.calls == 2 and result.status == "pass" and result.findings["attempts"] == 2
    kinds = [k for k, _, _ in events]
    assert kinds[:3] == ["agent_start", "quality_check", "retry"] and kinds[-1] == "agent_complete"
    assert events[1][1]["passed"] is False and "unavailable" in events[2][1]["reason"]
    # still failing after the retry: reported as failed with the reason, never as a result
    events.clear()
    agent = _flaky_agent(5)
    out = execute_agent(agent(), state, "content_assessment")
    result = out["alignment_results"]["content_assessment"]
    assert agent.calls == 2 and result.status == "failed" and result.findings["attempts"] == 2 and "unavailable" in result.findings["error"]
    assert [k for k, _, _ in events].count("retry") == 1 and events[-1][0] == "agent_failed"
    monkeypatch.setattr(settings, "quality_max_retries", 0)
    agent = _flaky_agent(5)
    execute_agent(agent(), state, "content_assessment")
    assert agent.calls == 1                                                     # zero retries means exactly one attempt


def _review_agent(replies, seen):
    from rag.chunking.chunk_models import RetrievedChunk

    class Agent:
        def _retrieve(self, *a, **k): return [RetrievedChunk("real", "Real source excerpt", .8, "a", "slides", "c", 1, None, None, None)]
        def _invoke(self, system, human, **k):
            seen.append(human)
            return json.dumps(replies[min(len(seen), len(replies)) - 1]), 7
        def _parse_json(self, t): return json.loads(t)
    return Agent()


def _finding(evidence):
    return {"title": "Objective not taught", "description": "The objective has no matching material.", "severity": "warning", "rationale": "No excerpt covers it.",
            "correction": "Add material or revise the objective.", "evidence_ids": [evidence], "evidence_strength": "moderate"}


def test_model_review_with_unsupplied_evidence_is_asked_again_and_only_verified_findings_surface(monkeypatch):
    from agents.graph.state import AlignmentResult
    from agents.live_review import augment
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 1)

    def state():
        return {"run_id": str(uuid.uuid4()), "course_id": "c", "modules": [], "course_metadata": {"title": "T"},
                "alignment_results": {"metadata_content": AlignmentResult("a", "metadata_content", .9, "pass")}}
    seen = []
    first = state()
    out = augment(_review_agent([{"findings": [_finding("invented-id")], "limitations": "none"},
                                 {"findings": [_finding("real")], "limitations": "none"}], seen), first, "metadata_content")
    result = first["alignment_results"]["metadata_content"]
    assert len(seen) == 2 and "QUALITY REVIEW" in seen[1] and "real" in seen[1].split("QUALITY REVIEW")[1]
    assert len(result.gaps) == 1 and result.findings["live_review"]["attempts"] == 2 and result.findings["live_review"]["discarded_unverifiable"] == 0
    assert out["total_tokens"] == 14                                            # both calls are counted
    kinds = [(k, p.get("passed")) for k, p, _ in events]
    assert kinds == [("quality_check", False), ("retry", None), ("quality_check", True)]
    # the second answer is no better: the unverifiable finding is still dropped, and the loop stops at the limit
    seen.clear(); events.clear()
    second = state()
    augment(_review_agent([{"findings": [_finding("invented-id")], "limitations": "none"}], seen), second, "metadata_content")
    result = second["alignment_results"]["metadata_content"]
    assert len(seen) == 2 and not result.gaps and result.findings["live_review"]["discarded_unverifiable"] == 1
    assert events[-1][1]["passed"] is False


def test_a_weak_automatic_draft_is_reassigned_to_another_model(monkeypatch):
    from types import SimpleNamespace as NS
    from agents.content_generation_agent import ContentGenerationAgent
    from agents.graph.state import AlignmentGap
    from test_phase1_governance import CITED, GOOD, TARGET
    events = _capture(monkeypatch)
    monkeypatch.setattr(settings, "quality_max_retries", 1)
    monkeypatch.setattr(settings, "openrouter_fallback_model", "other/model:free")
    used = []

    class Rag:
        def generate(self, model=None, **kw):
            used.append((model, kw.get("extra_instructions") or ""))
            return NS(content="Too short." if len(used) == 1 else GOOD, citations=CITED, tokens_used=5)
    agent = ContentGenerationAgent()
    monkeypatch.setattr(agent, "_get_rag", lambda: Rag())
    gap = AlignmentGap(str(uuid.uuid4()), "clo_not_assessed", "warning", TARGET, "clo", None, 0., "Add an assessment item.")
    item, tokens = agent._generate_for_gap(gap, "c", {"run_id": "r", "course_intent": None, "lecturer_constraints": []}, "COURSE INTENT: analyse.")
    assert [m for m, _ in used] == [settings.openrouter_model, "other/model:free"] and tokens == 10
    assert "QUALITY REVIEW" in used[1][1] and "COURSE INTENT: analyse." in used[1][1]
    assert item.review["passed"] and item.review["attempts"] == 2 and "other/model:free" in item.review["rationale"]
    retry = next(p for k, p, _ in events if k == "retry")
    assert retry["switched_model"] is True and retry["next_model"] == "other/model:free"
