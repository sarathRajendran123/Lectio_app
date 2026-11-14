"""Analysis of the interaction log (emergent-behaviour indicators). Unit tests use hand-built events."""
import json
import sys
import time
from pathlib import Path

from knowledge import trace_analysis as analysis
from test_multilingual_model import _upload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyse_trace   # noqa: E402

API = "/api/v1"
V1, V2 = {"id": "intent-a", "version": 1}, {"id": "intent-a", "version": 2}


class Log:
    """Builds a trace the way the application writes it."""

    def __init__(self):
        self.events = []

    def add(self, event_type, agent, payload=None, task=None, subject=None):
        self.events.append({"seq": len(self.events) + 1, "event_type": event_type, "agent": agent, "task_id": task,
                            "subject_type": "gap" if subject else None, "subject_id": subject, "payload": payload or {}})
        return self

    def step(self, agent, intent=V1, assign=True):
        if assign:
            self.add("agent_message", "course_director", {"from": "course_director", "to": agent, "intent": intent})
        return self.add("agent_start", agent, {"intent": intent})


def _clean_run():
    log = Log().add("audit_created", "lecturer", {"intent": V1})
    log.step("metadata_content_agent")
    log.add("tool_call", "metadata_content_agent", {"intent": V1, "chunk_ids": ["c1", "c2"]}, task="t1")
    log.add("agent_decision", "metadata_content_agent", {"intent": V1, "decision": "finding_raised", "gap_type": "clo_not_covered",
                                                           "evidence_chunk_ids": ["c1"], "basis": "rule_based_check"}, task="t1", subject="g1")
    log.add("agent_complete", "metadata_content_agent", {"intent": V1, "duration_ms": 40, "error": None})
    log.step("stakeholder_agent")
    log.add("finding_recorded", "stakeholder_agent", {"intent": V1, "source_agent": "metadata_content_agent"}, subject="g1")
    log.add("run_finished", "workflow_service", {"status": "completed"})
    return log


def test_a_clean_run_has_full_propagation_and_no_observations():
    result = analysis.analyse_run(_clean_run().events)
    assert result["goal_propagation"]["fidelity"] == 1.0 and result["goal_propagation"]["agent_events"] == 8
    assert result["delegation"]["steps_without_assignment"] == [] and result["delegation"]["messages"] == 2
    assert result["traceability"]["findings_raised_by_agents"] == 1 == result["traceability"]["findings_recorded_for_the_lecturer"]
    assert result["run"]["status"] == "completed" and result["run"]["ms_per_agent"] == {"metadata_content_agent": 40}
    assert result["observations"] == []


def test_events_without_or_with_another_intent_are_counted_and_located():
    log = _clean_run()
    log.add("tool_call", "content_delivery_agent", {"chunk_ids": []})                         # no intent at all
    log.add("agent_decision", "content_delivery_agent", {"intent": {"id": "intent-b", "version": 1}, "decision": "dimension_assessed"})
    result = analysis.analyse_run(log.events)["goal_propagation"]
    assert (result["carrying_the_intent"], result["without_intent"], result["with_another_intent"]) == (8, 1, 1)
    assert result["fidelity"] == 0.8
    assert {(w["agent"], w["event_type"]) for w in result["where_missing"]} == {("content_delivery_agent", "tool_call"), ("content_delivery_agent", "agent_decision")}


def test_an_intent_changed_during_a_pause_is_the_intent_in_force_afterwards():
    log = Log().add("audit_created", "lecturer", {"intent": V1})
    log.step("metadata_content_agent")
    log.add("run_paused", "lecturer").add("run_held", "content_assessment_agent")
    log.add("run_continued", "content_assessment_agent", {"held_ms": 4000, "reloaded": ["course_intent"]})
    log.step("content_assessment_agent", intent=V2)
    log.add("agent_decision", "content_assessment_agent", {"intent": V1, "decision": "dimension_assessed"})     # still the old version
    result = analysis.analyse_run(log.events)
    propagation = result["goal_propagation"]
    assert propagation["intent_changed_during_pause"] == 1 and propagation["with_another_intent"] == 1
    assert propagation["where_missing"] == [{"agent": "content_assessment_agent", "event_type": "agent_decision", "events": 1}]
    assert result["run"]["pauses"] == 1 and result["run"]["held_ms"] == 4000


def test_without_a_stated_intent_propagation_is_not_scored():
    log = Log().add("audit_created", "lecturer", {"intent": None})
    log.step("metadata_content_agent", intent=None)
    propagation = analysis.analyse_run(log.events)["goal_propagation"]
    assert propagation["intent_stated"] is False and propagation["fidelity"] is None and propagation["where_missing"] == []


def test_untraceable_and_unexpected_outputs_are_reported():
    log = _clean_run()
    log.step("content_generation_agent", assign=False)                                         # nobody asked for this step
    log.add("agent_start", "shadow_agent", {"intent": V1})                                     # not in the roster
    log.add("finding_recorded", "stakeholder_agent", {"intent": V1, "source_agent": "metadata_content_agent"}, subject="g-nobody-raised")
    log.add("agent_decision", "content_delivery_agent", {"intent": V1, "decision": "finding_raised", "evidence_chunk_ids": ["never-retrieved"]},
            subject="g2")
    log.add("finding_recorded", "stakeholder_agent", {"intent": V1, "source_agent": "metadata_content_agent"}, subject="g2")   # wrong source
    log.add("agent_complete", "content_delivery_agent", {"intent": V1, "error": "boom", "duration_ms": 5})
    log.add("model_call", "content_generation_agent", {"intent": V1, "outcome": "rejected_by_validation"})
    log.add("quality_check", "content_generation_agent", {"intent": V1, "passed": False, "issues": ["The draft cites no source excerpt."]})
    log.add("retry", "content_generation_agent", {"intent": V1, "switched_model": True})
    log.add("draft_queued", "stakeholder_agent", {"intent": V1, "quality_passed": False})
    result = analysis.analyse_run(log.events)
    assert result["delegation"]["steps_without_assignment"] == ["content_generation_agent", "shadow_agent"]
    assert result["delegation"]["agents_outside_the_roster"] == ["shadow_agent"]
    trace = result["traceability"]
    assert trace["recorded_without_an_agent_decision"] == ["g-nobody-raised"] and trace["citing_evidence_no_retrieval_returned"] == 1
    assert trace["recorded_under_another_agent"] == ["g2"]
    assert result["run"]["failed_steps"] == ["content_delivery_agent"] and result["run"]["model_calls_not_ok"] == {"rejected_by_validation": 1}
    quality = result["quality_loop"]
    assert (quality["failed_checks"], quality["retries"], quality["model_switches"], quality["drafts_queued_below_threshold"]) == (1, 1, 1, 1)
    text = " ".join(result["observations"])
    for expected in ("without an assignment", "outside the roster", "without an agent decision", "no retrieval call", "different agent",
                     "failed: content_delivery_agent", "rejected_by_validation", "below the quality threshold"):
        assert expected in text, expected
    assert "no closing run_finished" not in text
    assert "no closing run_finished" in " ".join(analysis.analyse_run(log.events[:5])["observations"])


def test_a_dimension_assigned_twice_is_reported():
    log = Log().add("audit_created", "lecturer", {"intent": V1})
    log.step("metadata_content_agent").step("metadata_content_agent")
    result = analysis.analyse_run(log.events)
    assert result["delegation"]["assigned_more_than_once"] == {"metadata_content_agent": 2}


def test_the_lecturer_side_is_summarised_from_the_course_log():
    log = Log()
    log.add("intent_updated", "lecturer").add("draft_requested", "lecturer", {"content_type": "exercise", "styles": ["applied"], "granularity": ["brief", "detailed"]})
    log.add("draft_requested", "lecturer", {"content_type": "slide_outline", "styles": ["applied", "conceptual"], "granularity": ["standard"]})
    for decision, comment, rule in (("approved", False, None), ("rejected", True, "r1"), ("rejected", True, "r2"), ("revised", False, None)):
        log.add("lecturer_decision", "lecturer", {"decision": decision, "has_comment": comment, "constraint_id": rule})
    log.add("finding_decision", "lecturer", {"decision": "rejected"}).add("constraint_recorded", "lecturer", {"kind": "avoid"})
    log.add("draft_feedback", "lecturer", {})
    result = analysis.analyse_course(log.events)
    assert result["draft_decisions"] == {"approved": 1, "rejected": 2, "revised": 1} and result["approved_share_of_decided"] == round(1 / 3, 4)
    assert result["decisions_with_a_comment"] == 2 and result["decisions_that_became_a_rule"] == 2
    assert result["draft_requests"] == {"count": 2, "by_type": {"exercise": 1, "slide_outline": 1}, "styles": {"applied": 2, "conceptual": 1},
                                        "granularity": {"brief": 1, "detailed": 1, "standard": 1}}
    assert result["finding_decisions"] == {"rejected": 1} and result["rules_recorded"] == {"avoid": 1}
    assert result["intent_versions_saved"] == 1 and result["draft_checks_while_editing"] == 1
    assert analysis.analyse_course([])["approved_share_of_decided"] is None                    # nothing decided: not 0 %, not 100 %


class _Api:
    def __init__(self, client, headers):
        self.client, self.headers = client, headers

    def get(self, path, params=None):
        return self.client.get(API + path, headers=self.headers, params=params)


def test_a_real_audit_is_analysed_through_the_api_and_the_script(client, headers, tmp_path):
    course = client.post(f"{API}/courses", headers=headers, json={"code": "TRACE-AN", "title": "Algorithms"}).json()["id"]
    base = f"{API}/courses/{course}"
    assert client.put(base + "/intent", headers=headers, json={"goals": "Students analyse and evaluate algorithms.",
                                                               "cognitive_levels": ["analyse", "evaluate"]}).status_code == 200
    for name, kind, mime in [("syllabus.md", "syllabus", "text/markdown"), ("lecture_slides.txt", "slides", "text/plain"), ("exam.txt", "exam", "text/plain")]:
        _upload(client, headers, base, "en_algorithms", name, kind, mime)
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    for _ in range(600):
        if client.get(f"{API}/runs/{run}", headers=headers).json()["status"] != "running":
            break
        time.sleep(.1)
    draft = client.post(base + "/generate", headers=headers, json={"content_type": "exercise", "purpose": "Practise binary search", "alternatives": 1}).json()[0]
    client.post(f"{API}/approvals/{draft['id']}/reject", headers=headers, json="too easy")
    result = client.get(f"{API}/runs/{run}/trace/analysis", headers=headers).json()
    propagation = result["goal_propagation"]
    assert propagation["intent_stated"] and propagation["with_another_intent"] == 0 and propagation["fidelity"] >= 0.95
    # The one known gap: the Course Director's first step starts before it has loaded the intent.
    assert propagation["where_missing"] == [{"agent": "course_director", "event_type": "agent_start", "events": 1}]
    assert result["delegation"]["steps_without_assignment"] == [] and result["delegation"]["agents_outside_the_roster"] == []
    trace = result["traceability"]
    assert trace["findings_raised_by_agents"] == trace["findings_recorded_for_the_lecturer"] > 0
    assert trace["recorded_without_an_agent_decision"] == [] and trace["citing_evidence_no_retrieval_returned"] == 0
    assert result["run"]["model_calls"] == 0 and len(result["observations"]) == 1
    report = analyse_trace.analyse(course, tmp_path, client=_Api(client, headers))
    assert run in report["runs"] and report["course"]["draft_decisions"] == {"rejected": 1} and report["course"]["intent_versions_saved"] == 1
    text = (tmp_path / "analysis.md").read_text(encoding="utf-8")
    assert "not proof of unexpected behaviour" in text and f"## Run {run}" in text and "Lecturer side" in text
    assert json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))["runs"][run]["run"]["status"]
