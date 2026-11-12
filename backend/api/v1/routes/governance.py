"""Course intent, lecturer constraints, the trace log and the Stakeholder agent's lecturer-facing view."""
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.v1.routes.courses import _assert_course_access
from auth.rbac import get_current_user
from db.models.generated_content import GeneratedContentRecord
from db.models.governance import TraceEvent
from db.models.report import AlignmentGapRecord, AlignmentReport
from db.session import get_db
from services import constraints as lecturer_constraints, intent as course_intent, stakeholder_view, trace

router = APIRouter()
Level = Literal["remember", "understand", "apply", "analyse", "evaluate", "create"]


# ── course intent ────────────────────────────────────────────────────────────

class IntentBody(BaseModel):
    goals: str = Field(min_length=10, max_length=4000)
    cognitive_levels: list[Level] = Field(default_factory=list, max_length=6)
    audience: str = Field(default="", max_length=1000)
    scope: str = Field(default="", max_length=2000)
    constraints: str = Field(default="", max_length=2000)


@router.get("/courses/{course_id}/intent")
async def get_intent(course_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id, user, db)
    return {"intent": await course_intent.active(db, course_id), "history": await course_intent.history(db, course_id)}


@router.put("/courses/{course_id}/intent")
async def set_intent(course_id: UUID, body: IntentBody, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """Saving adds a new version; runs that already happened keep the version they used."""
    await _assert_course_access(course_id, user, db)
    saved = await course_intent.save(db, course_id, user.id, **body.model_dump())
    await trace.aemit("intent_updated", {"intent": course_intent.ref(saved), "cognitive_levels": saved["cognitive_levels"]},
                      db=db, subject=("course", course_id), course_id=str(course_id), agent="lecturer")
    return saved


# ── lecturer constraints ─────────────────────────────────────────────────────

class ConstraintBody(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    kind: Literal["avoid", "prefer", "require"] = "prefer"
    scope: Literal["course", "general"] = "course"
    supersedes_id: Optional[UUID] = None


@router.get("/courses/{course_id}/constraints")
async def list_constraints(course_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id, user, db)
    return {"active": await lecturer_constraints.active(db, user.id, course_id),
            "history": await lecturer_constraints.history(db, user.id, course_id)}


async def _own_constraint(db, user, constraint_id):
    from db.models.governance import LecturerConstraint
    row = await db.get(LecturerConstraint, constraint_id)
    if not row or str(row.user_id) != str(user.id):
        raise HTTPException(404, "Constraint not found.")
    return row


@router.post("/courses/{course_id}/constraints", status_code=201)
async def add_constraint(course_id: UUID, body: ConstraintBody, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """Add a rule, or replace an earlier one (the earlier one stays in the history)."""
    await _assert_course_access(course_id, user, db)
    if body.supersedes_id:
        await _own_constraint(db, user, body.supersedes_id)
    saved = await lecturer_constraints.add(db, user.id, text=body.text, kind=body.kind, scope=body.scope, course_id=course_id,
                                           source_type="manual", supersedes_id=body.supersedes_id)
    await trace.aemit("constraint_recorded", {"constraint_id": saved["id"], "kind": saved["kind"], "scope": saved["scope"],
                                              "source_type": "manual", "supersedes_id": saved["supersedes_id"]},
                      db=db, subject=("course", course_id), course_id=str(course_id), agent="lecturer")
    return saved


@router.post("/courses/{course_id}/constraints/{constraint_id}/retire", status_code=201)
async def retire_constraint(course_id: UUID, constraint_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """Stop applying a rule. A retirement marker is added; the rule itself is kept."""
    await _assert_course_access(course_id, user, db)
    old = await _own_constraint(db, user, constraint_id)
    saved = await lecturer_constraints.add(db, user.id, text=f"Retired: {old.text}", kind="retired", scope=old.scope,
                                           course_id=old.course_id or course_id, source_type="manual", supersedes_id=constraint_id)
    await trace.aemit("constraint_recorded", {"constraint_id": saved["id"], "kind": "retired", "supersedes_id": str(constraint_id)},
                      db=db, subject=("course", course_id), course_id=str(course_id), agent="lecturer")
    return saved


# ── trace ────────────────────────────────────────────────────────────────────

async def _run_course(db, run_id):
    from db.models.generated_content import AgentRun
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return run


@router.get("/runs/{run_id}/trace")
async def run_trace(run_id: UUID, event_type: Optional[str] = None, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    run = await _run_course(db, run_id)
    await _assert_course_access(run.course_id, user, db)
    q = select(TraceEvent).where(TraceEvent.chain_key == str(run_id)).order_by(TraceEvent.seq)
    if event_type:
        q = q.where(TraceEvent.event_type == event_type)
    rows = (await db.scalars(q)).all()
    return {"run_id": str(run_id), "integrity": await trace.verify_chain(db, str(run_id)), "events": [trace.to_dict(r) for r in rows]}


@router.get("/runs/{run_id}/trace/verify")
async def verify_run_trace(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    run = await _run_course(db, run_id)
    await _assert_course_access(run.course_id, user, db)
    return await trace.verify_chain(db, str(run_id))


@router.get("/courses/{course_id}/trace")
async def course_trace(course_id: UUID, event_type: Optional[str] = None, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """Events outside any audit run: intent changes, rules, draft requests and the decisions on those drafts."""
    await _assert_course_access(course_id, user, db)
    key = f"course:{course_id}"
    q = select(TraceEvent).where(TraceEvent.chain_key == key).order_by(TraceEvent.seq)
    if event_type:
        q = q.where(TraceEvent.event_type == event_type)
    rows = (await db.scalars(q)).all()
    return {"course_id": str(course_id), "integrity": await trace.verify_chain(db, key), "events": [trace.to_dict(r) for r in rows]}


@router.get("/courses/{course_id}/trace/verify")
async def verify_course_trace(course_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id, user, db)
    return await trace.verify_chain(db, f"course:{course_id}")


@router.post("/courses/{course_id}/trace/anchor")
async def anchor_course_trace(course_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """Record the current head of the course log and of each of its run logs outside the database.

    Later checks then detect events removed from the end, or a log rewritten as a whole."""
    await _assert_course_access(course_id, user, db)
    from db.models.generated_content import AgentRun
    from db.session import AsyncSessionLocal
    runs = (await db.scalars(select(AgentRun.id).where(AgentRun.course_id == course_id))).all()
    async with AsyncSessionLocal() as committed:        # anchor only what is committed, never this request's own pending rows
        entries = [await trace.anchor(committed, key) for key in [f"course:{course_id}"] + [str(r) for r in runs]]
    return {"anchored": [e for e in entries if e], "stored_outside_database": True}


@router.get("/findings/{gap_id}/trace")
async def finding_trace(gap_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """How one finding was produced: intent, evidence, agents, model calls and checks, the result and the lecturer's decision."""
    gap = await db.get(AlignmentGapRecord, gap_id)
    if not gap:
        raise HTTPException(404, "Finding not found.")
    report = await db.get(AlignmentReport, gap.report_id)
    await _assert_course_access(report.course_id, user, db)
    return await stakeholder_view.finding_trace(db, gap, report)


@router.get("/approvals/{content_id}/trace")
async def draft_trace(content_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    item = await db.get(GeneratedContentRecord, content_id)
    if not item:
        raise HTTPException(404, "Draft not found.")
    await _assert_course_access(item.course_id, user, db)
    return await stakeholder_view.draft_trace(db, item)


# ── the Stakeholder agent's lecturer-facing view ─────────────────────────────

@router.get("/courses/{course_id}/briefing")
async def briefing(course_id: UUID, user=Depends(get_current_user), db=Depends(get_db, scope="function")):
    """Findings and drafts as the Stakeholder agent presents them: plain language, evidence, uncertainty, rationale."""
    await _assert_course_access(course_id, user, db)
    return await stakeholder_view.briefing(db, course_id, user.id)
