"""
LECTIO — Agent Runs, Reports, and Approvals Routes

POST /api/v1/courses/{id}/run-audit     — Start audit workflow
GET  /api/v1/runs/{run_id}              — Get run status
GET  /api/v1/courses/{id}/reports       — List alignment reports
GET  /api/v1/reports/{id}              — Get full report
GET  /api/v1/approvals                 — List pending approvals
POST /api/v1/approvals/{id}/approve    — Approve content
POST /api/v1/approvals/{id}/revise     — Submit revision
POST /api/v1/approvals/{id}/reject     — Reject content
"""

import logging
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import CurrentUser, get_current_user
from db.models.generated_content import GeneratedContentRecord
from db.models.report import AlignmentReport, AlignmentGapRecord
from db.repositories.course_repository import CourseRepository
from db.session import get_db
from services.workflow_service import workflow_service

runs_router     = APIRouter()
reports_router  = APIRouter()
approvals_router = APIRouter()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# AGENT RUNS
# ═══════════════════════════════════════

@runs_router.post("/courses/{course_id}/run-audit", status_code=status.HTTP_202_ACCEPTED)
async def start_audit(
    course_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """
    Initiate a full alignment audit workflow for a course.
    Returns immediately with run_id; workflow runs in background.
    Poll GET /runs/{run_id} for status.
    """
    repo   = CourseRepository(db)
    course = await repo.get_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    if not await repo.user_can_access(course_id, UUID(user.id), user.roles):
        raise HTTPException(status_code=403, detail="Access denied.")

    run_id = await workflow_service.start_run(
        course_id=str(course_id),
        initiated_by=str(user.id),
        db=db,
    )
    logger.info(f"Audit run {run_id} started by {user.email} for course {course_id}")
    return {"run_id": run_id, "status": "running", "message": "Audit workflow started."}


@runs_router.get("/runs/{run_id}")
async def get_run_status(
    run_id: UUID,
    user:   CurrentUser  = Depends(get_current_user),
    db:     AsyncSession = Depends(get_db),
):
    """Poll for workflow run status and progress."""
    run_data = await workflow_service.get_run_status(str(run_id), db)
    if not run_data:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run_data


@runs_router.get("/runs/{run_id}/steps")
async def get_run_steps(
    run_id: UUID,
    user:   CurrentUser  = Depends(get_current_user),
    db:     AsyncSession = Depends(get_db),
):
    """Get step-by-step agent execution log for a run."""
    from db.models.generated_content import AgentStep
    result = await db.execute(
        select(AgentStep)
        .where(AgentStep.run_id == run_id)
        .order_by(AgentStep.created_at)
    )
    steps = result.scalars().all()
    return [
        {
            "agent_name":    s.agent_name,
            "status":        s.status,
            "tokens_used":   s.tokens_used,
            "duration_ms":   s.duration_ms,
            "created_at":    s.created_at.isoformat(),
            "error_message": s.error_message,
        }
        for s in steps
    ]


# ═══════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════

@reports_router.get("/courses/{course_id}/reports")
async def list_reports(
    course_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """List all alignment reports for a course."""
    result = await db.execute(
        select(AlignmentReport)
        .where(AlignmentReport.course_id == course_id)
        .order_by(AlignmentReport.generated_at.desc())
    )
    reports = result.scalars().all()
    return [
        {
            "id":            str(r.id),
<<<<<<< HEAD
            "run_id":        str(r.run_id),
=======
>>>>>>> 0769384aa5cfe90c2fafe2f4f7f21aeb558648b0
            "report_type":   r.report_type,
            "overall_score": float(r.overall_score or 0),
            "status":        r.status,
            "gap_count":     r.gap_count,
            "generated_at":  r.generated_at.isoformat(),
        }
        for r in reports
    ]


@reports_router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """Get a full alignment report with all gaps."""
    result = await db.execute(
        select(AlignmentReport).where(AlignmentReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    gaps_result = await db.execute(
        select(AlignmentGapRecord).where(AlignmentGapRecord.report_id == report_id)
    )
    gaps = gaps_result.scalars().all()

    return {
        "id":              str(report.id),
        "course_id":       str(report.course_id),
        "report_type":     report.report_type,
        "overall_score":   float(report.overall_score or 0),
        "status":          report.status,
        "findings":        report.findings,
        "recommendations": report.recommendations,
        "generated_at":    report.generated_at.isoformat(),
        "gaps": [
            {
                "id":          str(g.id),
                "gap_type":    g.gap_type,
                "severity":    g.severity,
                "description": g.description,
                "score":       float(g.score or 0),
                "recommendation": g.recommendation,
                "is_resolved": g.is_resolved,
            }
            for g in gaps
        ],
    }


@reports_router.post("/reports/{report_id}/gaps/{gap_id}/resolve", status_code=200)
async def resolve_gap(
    report_id: UUID,
    gap_id:    UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """Mark an alignment gap as manually resolved."""
    from sqlalchemy import update
    from datetime import datetime, timezone
    await db.execute(
        update(AlignmentGapRecord)
        .where(AlignmentGapRecord.id == gap_id)
        .values(
            is_resolved=True,
            resolved_by=uuid.UUID(user.id),
            resolved_at=datetime.now(timezone.utc),
        )
    )
    return {"gap_id": str(gap_id), "resolved": True}


# ═══════════════════════════════════════
# APPROVALS
# ═══════════════════════════════════════

@approvals_router.get("/approvals")
async def list_approvals(
    status_filter: Optional[str] = Query(None, alias="status"),
    course_id:     Optional[UUID] = Query(None),
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """List generated content items pending review."""
    q = select(GeneratedContentRecord)
    if status_filter:
        q = q.where(GeneratedContentRecord.approval_status == status_filter)
    else:
        q = q.where(GeneratedContentRecord.approval_status == "pending")
    if course_id:
        q = q.where(GeneratedContentRecord.course_id == course_id)

    result = await db.execute(q.order_by(GeneratedContentRecord.created_at.desc()))
    items  = result.scalars().all()

    return [
        {
            "id":             str(i.id),
            "content_type":   i.content_type,
            "title":          i.title,
            "content":        i.content,
            "bloom_level":    i.bloom_level,
            "confidence_score": float(i.confidence_score or 0),
            "citations":      i.citations or [],
            "approval_status": i.approval_status,
            "created_at":     i.created_at.isoformat(),
        }
        for i in items
    ]


@approvals_router.get("/approvals/{content_id}")
async def get_approval_item(
    content_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GeneratedContentRecord).where(GeneratedContentRecord.id == content_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found.")
    return {
        "id":              str(item.id),
        "content_type":    item.content_type,
        "title":           item.title,
        "content":         item.content,
        "bloom_level":     item.bloom_level,
        "confidence_score": float(item.confidence_score or 0),
        "citations":       item.citations or [],
        "approval_status": item.approval_status,
    }


def _approval_body(decision: str):
    async def handler(
        content_id: UUID,
        comment:    Optional[str] = Body(None),
        revision:   Optional[str] = Body(None),
        user: CurrentUser  = Depends(get_current_user),
        db:   AsyncSession = Depends(get_db),
    ):
        result = await workflow_service.submit_approval(
            content_id=str(content_id),
            reviewer_id=str(user.id),
            decision=decision,
            comment=comment,
            revision=revision,
            db=db,
        )
        return result
    return handler


@approvals_router.post("/approvals/{content_id}/approve")
async def approve_content(
    content_id: UUID,
    comment: Optional[str] = Body(None),
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    return await workflow_service.submit_approval(
        str(content_id), str(user.id), "approved", comment, None, db
    )


@approvals_router.post("/approvals/{content_id}/revise")
async def revise_content(
    content_id: UUID,
    comment:  Optional[str] = Body(None),
    revision: Optional[str] = Body(None),
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    if not revision:
        raise HTTPException(status_code=422, detail="revision text is required.")
    return await workflow_service.submit_approval(
        str(content_id), str(user.id), "revised", comment, revision, db
    )


@approvals_router.post("/approvals/{content_id}/reject")
async def reject_content(
    content_id: UUID,
    comment: Optional[str] = Body(None),
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    return await workflow_service.submit_approval(
        str(content_id), str(user.id), "rejected", comment, None, db
    )
