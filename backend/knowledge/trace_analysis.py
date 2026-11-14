"""Analysis of the trace for the questions the project asks of its interaction logs. No database, no model.

Input: the events of one chain as returned by the trace endpoints (dicts with seq, event_type, agent, task_id,
subject_type, subject_id, payload). Output: counts, shares and a list of observations in plain sentences.

What is measured, and how:
- goal propagation: the share of agent events that carry the course intent the run was started with (or reloaded
  after a pause). An event with another or no intent is listed, not judged.
- delegation: who assigned work to whom, and agent steps that began without an assignment.
- traceability: findings recorded for the lecturer without an agent decision behind them, decisions that never
  reached the lecturer, and evidence cited without a retrieval call that returned it.
- quality loop: checks, failures, retries, model switches.
These are descriptive indicators computed from the log. They are not the regret-based collusion metrics of
Colosseum (Nakamura et al., 2026); an observation is a place to look, not proof of unexpected behaviour.
"""
from collections import Counter, defaultdict

ROSTER = ("course_director", "metadata_content_agent", "content_assessment_agent", "metadata_assessment_agent",
          "content_delivery_agent", "content_generation_agent", "stakeholder_agent")
NOT_AGENTS = ("lecturer", "workflow_service", "recovery", None)
BOOKKEEPING = ("run_held", "run_continued")      # written while a run waits; not agent work


def _ref(intent):
    return (intent.get("id"), intent.get("version")) if isinstance(intent, dict) else None


def _share(part, whole):
    return round(part / whole, 4) if whole else None


def analyse_run(events: list) -> dict:
    events = sorted(events, key=lambda e: e["seq"])
    by_type = Counter(e["event_type"] for e in events)
    agent_events = [e for e in events if e.get("agent") not in NOT_AGENTS and e["event_type"] not in BOOKKEEPING]
    observations = []

    # ── goal propagation ─────────────────────────────────────────────────────
    created = next((e for e in events if e["event_type"] == "audit_created"), None)
    reference = _ref((created or {}).get("payload", {}).get("intent")) if created else None
    carried = other = missing = 0
    gaps = Counter()
    switches = 0
    for event in events:
        if event["event_type"] == "run_continued" and "course_intent" in (event["payload"].get("reloaded") or []):
            reference = "reloaded"                      # the next agent event defines the intent now in force
            switches += 1
            continue
        if event.get("agent") in NOT_AGENTS or event["event_type"] in BOOKKEEPING:
            continue
        seen = _ref(event["payload"].get("intent"))
        if reference == "reloaded" and seen:
            reference = seen
        if seen is None:
            missing += 1
            gaps[(event["agent"], event["event_type"])] += 1
        elif reference in (None, "reloaded") or seen == reference:
            carried += 1
        else:
            other += 1
            gaps[(event["agent"], event["event_type"])] += 1
    stated = created is not None and (reference is not None or switches > 0)
    propagation = {"intent_stated": stated, "agent_events": len(agent_events),
                   "carrying_the_intent": carried if stated else None, "without_intent": missing if stated else None,
                   "with_another_intent": other if stated else None, "intent_changed_during_pause": switches,
                   "fidelity": _share(carried, len(agent_events)) if stated else None,
                   "where_missing": [{"agent": a, "event_type": t, "events": n} for (a, t), n in gaps.most_common()] if stated else []}
    if stated and other:
        observations.append(f"{other} agent event(s) carry a course intent other than the one in force.")
    if stated and missing:
        worst = gaps.most_common(1)[0]
        observations.append(f"{missing} agent event(s) carry no course intent (most: {worst[0][0]}, {worst[0][1]}, {worst[1]}).")

    # ── delegation ───────────────────────────────────────────────────────────
    messages = [e for e in events if e["event_type"] == "agent_message"]
    edges = Counter((e["payload"].get("from"), e["payload"].get("to")) for e in messages)
    assigned = Counter()
    unassigned = []
    steps = Counter()
    for event in events:
        if event["event_type"] == "agent_message":
            assigned[event["payload"].get("to")] += 1
        elif event["event_type"] == "agent_start":
            steps[event["agent"]] += 1
            if event["agent"] != "course_director":
                if assigned[event["agent"]] > 0:
                    assigned[event["agent"]] -= 1
                else:
                    unassigned.append(event["agent"])
    repeated = {to: n for (_, to), n in edges.items() if n > 1 and to != "course_director"}
    unknown = sorted({e["agent"] for e in agent_events} - set(ROSTER))
    delegation = {"messages": len(messages), "edges": [{"from": a, "to": b, "count": n} for (a, b), n in sorted(edges.items(), key=str)],
                  "steps_per_agent": dict(steps), "steps_without_assignment": unassigned, "assigned_more_than_once": repeated,
                  "agents_outside_the_roster": unknown}
    if unassigned:
        observations.append(f"Step(s) began without an assignment from the Course Director: {', '.join(unassigned)}.")
    if repeated:
        observations.append("Assigned more than once: " + ", ".join(f"{k} ({v})" for k, v in repeated.items()) + ".")
    if unknown:
        observations.append(f"Events from agents outside the roster: {', '.join(unknown)}.")

    # ── traceability of what reached the lecturer ────────────────────────────
    raised = {e["subject_id"]: e for e in events if e["event_type"] == "agent_decision" and e["payload"].get("decision") == "finding_raised"}
    recorded = {e["subject_id"]: e for e in events if e["event_type"] == "finding_recorded"}
    retrieved = defaultdict(set)
    for event in events:
        if event["event_type"] == "tool_call":
            retrieved[event.get("task_id")].update(event["payload"].get("chunk_ids") or [])
    all_retrieved = set().union(*retrieved.values()) if retrieved else set()
    no_evidence = [e for e in raised.values() if not e["payload"].get("evidence_chunk_ids")]
    unretrieved = [e for e in raised.values() if set(e["payload"].get("evidence_chunk_ids") or []) - all_retrieved]
    misattributed = [gid for gid, e in recorded.items() if gid in raised and e["payload"].get("source_agent") != raised[gid]["agent"]]
    traceability = {"findings_raised_by_agents": len(raised), "findings_recorded_for_the_lecturer": len(recorded),
                    "recorded_without_an_agent_decision": sorted(set(recorded) - set(raised)),
                    "raised_but_not_recorded": len(set(raised) - set(recorded)),
                    "raised_without_evidence": len(no_evidence),
                    "raised_without_evidence_by_type": dict(Counter(e["payload"].get("gap_type") for e in no_evidence)),
                    "citing_evidence_no_retrieval_returned": len(unretrieved), "recorded_under_another_agent": misattributed,
                    "by_basis": dict(Counter(e["payload"].get("basis") for e in raised.values())),
                    "previously_dismissed": sum(bool(e["payload"].get("previously_dismissed_by")) for e in raised.values())}
    if traceability["recorded_without_an_agent_decision"]:
        observations.append(f"{len(traceability['recorded_without_an_agent_decision'])} finding(s) reached the lecturer without an agent decision in the log.")
    if unretrieved:
        observations.append(f"{len(unretrieved)} finding(s) cite evidence that no retrieval call in this run returned.")
    if misattributed:
        observations.append(f"{len(misattributed)} finding(s) were recorded under a different agent than the one that raised them.")

    # ── quality loop, failures, pauses, cost ─────────────────────────────────
    checks = [e for e in events if e["event_type"] == "quality_check"]
    retries = [e for e in events if e["event_type"] == "retry"]
    calls = [e["payload"] for e in events if e["event_type"] == "model_call"]
    completes = [e for e in events if e["event_type"] == "agent_complete"]
    failed_steps = [e["agent"] for e in completes if e["payload"].get("error")] + [e["agent"] for e in events if e["event_type"] == "agent_failed"]
    queued = [e["payload"] for e in events if e["event_type"] == "draft_queued"]
    quality = {"checks": len(checks), "failed_checks": sum(not e["payload"].get("passed") for e in checks), "retries": len(retries),
               "model_switches": sum(bool(e["payload"].get("switched_model")) for e in retries),
               "failed_check_reasons": dict(Counter((e["payload"].get("issues") or ["unspecified"])[0][:80] for e in checks if not e["payload"].get("passed"))),
               "drafts_queued": len(queued), "drafts_queued_below_threshold": sum(not q.get("quality_passed") for q in queued)}
    finished = next((e for e in reversed(events) if e["event_type"] == "run_finished"), None)
    run = {"events": len(events), "event_types": dict(by_type), "status": (finished or {}).get("payload", {}).get("status"),
           "failed_steps": failed_steps, "model_review_errors": sum(bool(e["payload"].get("model_review_error")) for e in completes),
           "model_calls": len(calls), "model_calls_not_ok": dict(Counter(c.get("outcome") for c in calls if c.get("outcome") != "ok")),
           "model_calls_cached": sum(bool(c.get("cached")) for c in calls),
           "pauses": by_type.get("run_paused", 0), "held_ms": sum(e["payload"].get("held_ms") or 0 for e in events if e["event_type"] == "run_continued"),
           "ms_per_agent": {a: sum(e["payload"].get("duration_ms") or 0 for e in completes if e["agent"] == a) for a in sorted({e["agent"] for e in completes})}}
    if failed_steps:
        observations.append(f"Step(s) that failed: {', '.join(failed_steps)}.")
    if run["model_calls_not_ok"]:
        observations.append("Model calls that did not succeed: " + ", ".join(f"{k} ({v})" for k, v in run["model_calls_not_ok"].items()) + ".")
    if quality["drafts_queued_below_threshold"]:
        observations.append(f"{quality['drafts_queued_below_threshold']} draft(s) reached the lecturer below the quality threshold (shown with a warning).")
    if finished is None:
        observations.append("The log has no closing run_finished event.")
    return {"run": run, "goal_propagation": propagation, "delegation": delegation, "traceability": traceability, "quality_loop": quality,
            "observations": observations}


def analyse_course(events: list) -> dict:
    """Lecturer-side events of a course chain: what was asked for, decided and turned into rules."""
    by_type = Counter(e["event_type"] for e in events)
    decisions = [e["payload"] for e in events if e["event_type"] == "lecturer_decision"]
    findings = [e["payload"] for e in events if e["event_type"] == "finding_decision"]
    requests = [e["payload"] for e in events if e["event_type"] == "draft_requested"]
    rules = [e["payload"] for e in events if e["event_type"] == "constraint_recorded"]
    counted = Counter(d.get("decision") for d in decisions)
    decided = counted["approved"] + counted["rejected"]
    return {"events": len(events), "event_types": dict(by_type),
            "draft_decisions": dict(counted), "approved_share_of_decided": _share(counted["approved"], decided),
            "decisions_with_a_comment": sum(bool(d.get("has_comment")) for d in decisions),
            "decisions_that_became_a_rule": sum(bool(d.get("constraint_id")) for d in decisions),
            "finding_decisions": dict(Counter(f.get("decision") for f in findings)),
            "rules_recorded": dict(Counter(r.get("kind") for r in rules)),
            "draft_requests": {"count": len(requests), "by_type": dict(Counter(r.get("content_type") for r in requests)),
                               "styles": dict(Counter(s for r in requests for s in r.get("styles") or [])),
                               "granularity": dict(Counter(g for r in requests for g in r.get("granularity") or []))},
            "intent_versions_saved": by_type.get("intent_updated", 0), "draft_checks_while_editing": by_type.get("draft_feedback", 0)}


def _show(value):
    if value is None:
        return "n/a"
    return f"{value:.0%}" if isinstance(value, float) else str(value)


def render_markdown(report: dict) -> str:
    lines = ["# Interaction log analysis", "",
             "Descriptive indicators computed from the append-only trace. An observation is a place to look, not proof of "
             "unexpected behaviour. These are not Colosseum's regret-based metrics.", ""]
    for name, run in report.get("runs", {}).items():
        g, d, t, q, r = run["goal_propagation"], run["delegation"], run["traceability"], run["quality_loop"], run["run"]
        lines += [f"## Run {name}", "", f"Status: {r['status'] or 'not finished'}. Events: {r['events']}. Model calls: {r['model_calls']}. Pauses: {r['pauses']}.", "",
                  "| Question | Result |", "|---|---|",
                  f"| Course intent stated | {'yes' if g['intent_stated'] else 'no (propagation not applicable)'} |",
                  f"| Agent events carrying the intent in force | {_show(g['carrying_the_intent'])} of {g['agent_events']} ({_show(g['fidelity'])}) |",
                  f"| Agent events with another intent | {_show(g['with_another_intent'])} |",
                  f"| Task assignments from the Course Director | {d['messages']} |",
                  f"| Steps without an assignment | {len(d['steps_without_assignment'])} |",
                  f"| Findings raised by agents / recorded for the lecturer | {t['findings_raised_by_agents']} / {t['findings_recorded_for_the_lecturer']} |",
                  f"| Recorded without an agent decision | {len(t['recorded_without_an_agent_decision'])} |",
                  f"| Raised without source evidence | {t['raised_without_evidence']} |",
                  f"| Citing evidence no retrieval returned | {t['citing_evidence_no_retrieval_returned']} |",
                  f"| Quality checks failed / retries / model switches | {q['failed_checks']} of {q['checks']} / {q['retries']} / {q['model_switches']} |",
                  f"| Drafts queued below the threshold | {q['drafts_queued_below_threshold']} of {q['drafts_queued']} |", ""]
        if g["where_missing"]:
            lines += ["Events without the intent in force: " + "; ".join(f"{w['agent']} {w['event_type']} ({w['events']})" for w in g["where_missing"][:8]) + ".", ""]
        lines += ["Observations:"] + ([f"- {o}" for o in run["observations"]] or ["- none"]) + [""]
    course = report.get("course")
    if course:
        requests = course["draft_requests"]
        lines += ["## Lecturer side (course log)", "",
                  f"Draft decisions: {course['draft_decisions'] or 'none'}; approved share of decided: {_show(course['approved_share_of_decided'])}. "
                  f"Decisions with a comment: {course['decisions_with_a_comment']}; turned into a rule: {course['decisions_that_became_a_rule']}. "
                  f"Finding decisions: {course['finding_decisions'] or 'none'}. Rules recorded: {course['rules_recorded'] or 'none'}. "
                  f"Draft requests: {requests['count']} {requests['by_type'] or ''}. Intent versions saved: {course['intent_versions_saved']}. "
                  f"Checks while editing: {course['draft_checks_while_editing']}.", ""]
    return "\n".join(lines)
