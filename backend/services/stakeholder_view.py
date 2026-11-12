"""What the Stakeholder agent tells the lecturer: plain-language findings, drafts with a rationale, and traces.

Other agents produce structured findings and drafts; this module is the one place that turns them into
lecturer-facing text. Wording is rule-based on purpose: it adds no model call and no unsupported claim.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select

from db.models.artifact import Chunk, CourseArtifact
from db.models.generated_content import AgentRun, ApprovalRecord, GeneratedContentRecord
from db.models.governance import DraftReview, TraceEvent
from db.models.report import AlignmentGapRecord, AlignmentReport
from db.models.review import FindingDecision
from services import constraints as lecturer_constraints, intent as course_intent, trace

DIMENSIONS = {
    "metadata_content": "what the course says it teaches against what the materials teach",
    "content_assessment": "what is taught against what is tested",
    "metadata_assessment": "the stated objectives against what is tested",
    "content_delivery": "what was planned against what was delivered",
}
# gap type -> (what was found, why it matters)
MEANING = {
    "clo_not_covered": ("A stated learning objective has little or no support in the teaching materials.",
                        "Students may be promised an outcome the course does not teach."),
    "clo_not_assessed": ("A stated learning objective is not tested by any uploaded assessment.",
                         "An outcome that is never assessed cannot be shown to have been achieved."),
    "topic_not_assessed": ("A topic is taught but no assessment question covers it.",
                           "Students may treat untested material as optional."),
    "bloom_level_mismatch": ("An assessment asks for a higher thinking level than the materials reach.",
                             "Students may be tested on a skill they were not taught to practise."),
    "topic_not_delivered": ("A planned topic has no matching teaching material.",
                            "The plan and the delivered course may have drifted apart."),
    "assessment_weak_support": ("An assessment has only weak support in the teaching materials.",
                                "The assessment may probe content the course barely covers."),
    "assessment_no_content": ("An assessment could not be matched to any course content.", "It may test material that was not uploaded or not taught."),
    "assessment_unclear_outcome": ("An assessment question does not clearly map to a stated objective.",
                                   "It is unclear which outcome the question is evidence for."),
    "objective_not_measurable": ("An objective uses a verb that is hard to observe or test.", "A vague objective is difficult to teach towards and to assess."),
    "taught_topic_outside_metadata": ("A topic is taught but not described in the course plan.", "The module description may understate what the course covers."),
    "planned_sequence_difference": ("Material for a topic carries a different week than the plan.", "The order of delivery may differ from the schedule."),
    "delivery_information_missing": ("No planned teaching activities are stored for this course.", "Delivery cannot be compared with a plan that is missing."),
    "sequencing_error": ("Topics appear to be taught out of the planned order.", "Prerequisites may be taught after they are needed."),
    "delivery_not_covered": ("A planned topic does not appear in the lecture transcript.", "What was planned may not have been taught in the recorded session."),
    "delivery_partial": ("A planned topic appears only partly in the lecture transcript.", "Part of the planned content may have been skipped."),
    "delivery_unplanned": ("The lecture covers content that is not in the planned materials.", "The slides may no longer describe what is taught."),
    "intent_level_without_objective": ("A thinking level you asked for in the course intent is not reached by any stated learning objective.",
                                       "The course as described may not aim at what you intend it to achieve."),
    "intent_level_not_assessed": ("A thinking level you asked for in the course intent is not reached by any assessment question.",
                                  "The intended level of the course is not evidenced by what is tested."),
    "topic_shallow_coverage": ("A planned topic has only weak support in the slides or transcript.", "The topic may be treated more briefly than the plan suggests."),
    "live_missing_objective": ("The model review found content with no matching learning objective.", "Taught or assessed content is not reflected in the stated outcomes."),
    "live_missing_assessment": ("The model review found an objective or topic with no matching assessment.", "The outcome is not evidenced by any assessment."),
    "live_alignment_review": ("The model review raised a possible alignment issue.", "It needs your judgement; the model only saw retrieved excerpts."),
}


def brief(gap: dict, dimension: str, evidence: list) -> dict:
    """One finding in plain language: what, why, evidence, how sure, and what to do."""
    what, why = MEANING.get(gap["gap_type"], ("A possible alignment issue was found.", "It may affect how well the course parts fit together."))
    model_based = gap["gap_type"].startswith("live_")
    dismissed = gap.get("dismissed_by")
    if gap["gap_type"].startswith("intent_level_"):
        certainty = ("Low to moderate: thinking levels are read from action verbs (a heuristic) and no source excerpt is attached. "
                     "Check the wording of the objectives or questions yourself.")
    elif not evidence:
        certainty = "Low: no direct excerpt supports this. Missing documents or independent study can explain it."
    elif model_based:
        certainty = "Moderate at best: an AI model inferred this from a few retrieved excerpts. Check the excerpts yourself."
    else:
        certainty = "Moderate: a rule-based comparison of your uploaded files. It cannot see material that was not uploaded."
    return {"gap_id": gap["id"], "dimension": dimension, "compares": DIMENSIONS.get(dimension, dimension), "severity": gap["severity"],
            "what_was_found": what, "detail": gap["description"], "why_it_matters": why, "evidence": evidence,
            "how_sure": certainty, "suggested_action": gap.get("recommendation") or "", "produced_by": "AI model review" if model_based else "rule-based check",
            "resolved": bool(gap.get("is_resolved")), "previously_dismissed": bool(dismissed),
            "dismissed_note": "You dismissed this finding in an earlier review; it is listed for completeness and no draft is produced for it." if dismissed else None}


async def _evidence(db, chunk_ids: list) -> list:
    ids = []
    for c in chunk_ids or []:
        try:
            ids.append(UUID(str(c)))
        except ValueError:
            continue
    if not ids:
        return []
    rows = (await db.execute(select(Chunk, CourseArtifact).join(CourseArtifact, Chunk.artifact_id == CourseArtifact.id)
                             .where(Chunk.id.in_(ids)))).all()
    return [{"chunk_id": str(c.id), "document": a.original_filename, "type": a.artifact_type, "page": c.page_number,
             "slide": c.slide_number, "excerpt": c.text[:600]} for c, a in rows]


def _stored_gaps(report: AlignmentReport) -> dict:
    """gap_id -> the gap as the agent produced it (this is where the evidence ids are kept)."""
    return {g.get("gap_id"): g for g in ((report.findings or {}).get("gaps") or [])}


async def briefing(db, course_id, user_id) -> dict:
    reports = (await db.scalars(select(AlignmentReport).where(AlignmentReport.course_id == course_id)
                                .order_by(AlignmentReport.generated_at.desc()))).all()
    latest = {}
    for r in reports:
        latest.setdefault(r.report_type, r)
    findings = []
    for report_type, report in sorted(latest.items()):
        stored = _stored_gaps(report)
        gaps = (await db.scalars(select(AlignmentGapRecord).where(AlignmentGapRecord.report_id == report.id))).all()
        for g in gaps:
            evidence = await _evidence(db, (stored.get(str(g.id)) or {}).get("evidence_chunk_ids"))
            findings.append(brief({"id": str(g.id), "gap_type": g.gap_type, "severity": g.severity, "description": g.description,
                                   "recommendation": g.recommendation, "is_resolved": g.is_resolved,
                                   "dismissed_by": (stored.get(str(g.id)) or {}).get("dismissed_by")}, report_type, evidence))
    order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3), f["dimension"]))
    drafts = (await db.execute(select(GeneratedContentRecord, DraftReview).outerjoin(DraftReview, DraftReview.content_id == GeneratedContentRecord.id)
                               .where(GeneratedContentRecord.course_id == course_id, GeneratedContentRecord.approval_status == "pending")
                               .order_by(GeneratedContentRecord.created_at.desc()))).all()
    intent = await course_intent.active(db, course_id)
    return {
        "presented_by": "stakeholder_agent",
        "course_intent": intent,
        "intent_notice": None if intent else "No course intent is stated yet. State it so every agent works towards your goals.",
        "constraints": await lecturer_constraints.active(db, user_id, course_id),
        "checks": [{"dimension": t, "compares": DIMENSIONS.get(t, t), "status": r.status, "score": float(r.overall_score or 0),
                    "scored": r.status not in ("needs_review", "failed"), "run_id": str(r.run_id)} for t, r in sorted(latest.items())],
        "findings": findings,
        "drafts_waiting": [{"id": str(d.id), "title": d.title, "content_type": d.content_type, "model": d.model_used,
                            "rationale": rv.rationale if rv else "No quality review is recorded for this draft (created before reviews were introduced).",
                            "quality_score": rv.score if rv else None, "quality_passed": rv.passed if rv else None,
                            "issues": rv.issues if rv else [], "attempts": rv.attempts if rv else None,
                            "needs_care": bool(rv and not rv.passed)} for d, rv in drafts],
        "notice": "Scores and findings are heuristic evidence, not proof. Nothing changes in your course until you decide.",
    }


def _summary(events: list) -> dict:
    calls = [e for e in events if e["event_type"] == "model_call"]
    return {"events": len(events), "model_calls": len(calls), "cached_calls": sum(1 for c in calls if c["payload"].get("cached")),
            "failed_calls": sum(1 for c in calls if c["payload"].get("outcome") != "ok"),
            "tokens": sum(int(c["payload"].get("tokens_total") or 0) for c in calls),
            "retries": sum(1 for e in events if e["event_type"] == "retry"),
            "quality_checks": sum(1 for e in events if e["event_type"] == "quality_check")}


async def _intent_used(db, events: list) -> Optional[dict]:
    for e in events:
        ref = e["payload"].get("intent")
        if ref and ref.get("id"):
            return await course_intent.by_id(db, ref["id"])
    return None


async def finding_trace(db, gap: AlignmentGapRecord, report: AlignmentReport) -> dict:
    run_id = str(report.run_id)
    stored = _stored_gaps(report).get(str(gap.id)) or {}
    agent = (report.findings or {}).get("agent_name") or f"{report.report_type}_agent"
    rows = (await db.scalars(select(TraceEvent).where(TraceEvent.chain_key == run_id).order_by(TraceEvent.seq))).all()
    drafts = (await db.scalars(select(GeneratedContentRecord).where(GeneratedContentRecord.source_gap_id == gap.id))).all()
    draft_ids = {str(d.id) for d in drafts}
    relevant = []
    for r in rows:
        p = r.payload or {}
        if r.subject_type == "gap" and r.subject_id != str(gap.id):
            continue                                   # another finding's own events
        mine = (p.get("dimension") == report.report_type or r.agent == agent
                or (r.subject_type == "gap" and r.subject_id == str(gap.id))
                or (r.subject_type == "draft" and r.subject_id in draft_ids)
                or (r.event_type == "agent_message" and p.get("to") in (agent, "content_generation_agent", "stakeholder_agent"))
                or r.event_type == "audit_created")
        if mine:
            relevant.append(trace.to_dict(r))
    later = (await db.scalars(select(TraceEvent).where(TraceEvent.chain_key != run_id, or_(
        (TraceEvent.subject_type == "gap") & (TraceEvent.subject_id == str(gap.id)),
        (TraceEvent.subject_type == "draft") & (TraceEvent.subject_id.in_(draft_ids or {"-"})))).order_by(TraceEvent.ts))).all()
    decisions = (await db.scalars(select(FindingDecision).where(FindingDecision.gap_id == gap.id).order_by(FindingDecision.created_at))).all()
    draft_decisions = (await db.scalars(select(ApprovalRecord).where(ApprovalRecord.content_id.in_([d.id for d in drafts] or [UUID(int=0)]))
                                        .order_by(ApprovalRecord.decided_at))).all()
    intent = await _intent_used(db, relevant)
    constraint_ids = next((e["payload"].get("constraint_ids") for e in relevant if e["payload"].get("constraint_ids")), [])
    evidence = await _evidence(db, stored.get("evidence_chunk_ids"))
    events = relevant + [trace.to_dict(r) for r in later]
    return {
        "finding": brief({"id": str(gap.id), "gap_type": gap.gap_type, "severity": gap.severity, "description": gap.description,
                          "recommendation": gap.recommendation, "is_resolved": gap.is_resolved,
                          "dismissed_by": stored.get("dismissed_by")}, report.report_type, evidence),
        "1_intent": {"used": intent, "note": None if intent else "No course intent was stated when this audit ran.",
                     "constraint_ids": constraint_ids},
        "2_evidence": evidence,
        "3_agents": sorted({e["agent"] for e in events if e["agent"]}),
        "4_decisions": [e for e in events if e["event_type"] in ("agent_message", "agent_start", "agent_complete", "agent_failed", "agent_decision", "finding_recorded", "finding_decision")],
        "5_model_calls_and_checks": [e for e in events if e["event_type"] in ("model_call", "tool_call", "quality_check", "retry")],
        "6_result": {"report_type": report.report_type, "score": float(report.overall_score or 0), "status": report.status,
                     "drafts": [{"id": str(d.id), "title": d.title, "status": d.approval_status} for d in drafts]},
        "7_lecturer": {"finding_decisions": [{"decision": d.decision, "rationale": d.rationale, "at": d.created_at.isoformat() if d.created_at else None} for d in decisions],
                       "draft_decisions": [{"content_id": str(d.content_id), "decision": d.decision, "comment": d.comment,
                                            "at": d.decided_at.isoformat() if d.decided_at else None} for d in draft_decisions]},
        "summary": _summary(events),
        "integrity": await trace.verify_chain(db, run_id),
        "run_id": run_id,
    }


async def draft_trace(db, item: GeneratedContentRecord) -> dict:
    review = await db.get(DraftReview, item.id)
    conditions = [(TraceEvent.subject_type == "draft") & (TraceEvent.subject_id == str(item.id))]
    if review and review.task_id:
        conditions.append(TraceEvent.task_id == review.task_id)
    rows = (await db.scalars(select(TraceEvent).where(or_(*conditions)).order_by(TraceEvent.ts))).all()
    events = [trace.to_dict(r) for r in rows]
    decisions = (await db.scalars(select(ApprovalRecord).where(ApprovalRecord.content_id == item.id).order_by(ApprovalRecord.decided_at))).all()
    chain = str(item.run_id) if item.run_id else f"course:{item.course_id}"
    return {
        "draft": {"id": str(item.id), "title": item.title, "content_type": item.content_type, "status": item.approval_status, "model": item.model_used},
        "review": None if not review else {"score": review.score, "threshold": review.threshold, "passed": review.passed, "attempts": review.attempts,
                                           "issues": review.issues, "checks": review.checks, "rationale": review.rationale},
        "1_intent": {"used": await course_intent.by_id(db, review.intent_id) if review and review.intent_id else None,
                     "constraint_ids": review.constraint_ids if review else []},
        "2_evidence": [{"citation": c.get("citation"), "excerpt": (c.get("quote") or "")[:600]} for c in (item.citations or [])],
        "5_model_calls_and_checks": [e for e in events if e["event_type"] in ("model_call", "tool_call", "quality_check", "retry")],
        "7_lecturer": [{"decision": d.decision, "comment": d.comment, "at": d.decided_at.isoformat() if d.decided_at else None} for d in decisions],
        "summary": _summary(events),
        "integrity": await trace.verify_chain(db, chain),
    }
