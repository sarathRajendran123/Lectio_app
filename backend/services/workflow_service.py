"""
LECTIO — Workflow Service
Bridges FastAPI routes ↔ LangGraph workflow.
Handles: run creation, async execution, status updates, approval processing.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agents.graph.state import WorkflowStatus, initial_state
from db.models.generated_content import (
    AgentRun, ApprovalRecord, GeneratedContentRecord,
)
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class WorkflowService:

    # ── Launch a new audit run ─────────────────────────────────────────────────

    async def start_run(
        self,
        course_id:    str,
        initiated_by: str,
        workflow_type: str = "full_audit",
        db: Optional[AsyncSession] = None,
    ) -> str:
        """
        Create an AgentRun record and launch the workflow in a background thread.
        Returns the run_id immediately.
        """
        run_id = str(uuid.uuid4())

        # Create run record
        run = AgentRun(
            id=uuid.UUID(run_id),
            course_id=uuid.UUID(course_id),
            initiated_by=uuid.UUID(initiated_by) if initiated_by else None,
            workflow_type=workflow_type,
            status="running",
        )
        if db:
            db.add(run)
            await db.flush()
        else:
            async with AsyncSessionLocal() as session:
                session.add(run)
                await session.commit()

        # Run the workflow in a background thread (non-blocking)
        import asyncio
        asyncio.create_task(self._execute_workflow(run_id, course_id, initiated_by))
        logger.info(f"[WorkflowService] Run {run_id} started for course {course_id}")
        return run_id

    async def _execute_workflow(
        self,
        run_id:       str,
        course_id:    str,
        initiated_by: str,
    ) -> None:
        """Execute LangGraph workflow in background. Updates DB on completion."""
        from agents.graph.workflow import workflow_app

        state = initial_state(
            run_id=run_id,
            course_id=course_id,
            initiated_by=initiated_by,
        )

        try:
            logger.info(f"[WorkflowService] Executing workflow for run {run_id}")
            final_state = workflow_app.invoke(state)
            status      = final_state.get("workflow_status", WorkflowStatus.COMPLETED)
            tokens      = final_state.get("total_tokens", 0)

            await self._update_run(
                run_id=run_id,
                status=str(status),
                tokens=tokens,
                final_state=self._serialise_state(final_state),
            )
            logger.info(f"[WorkflowService] Run {run_id} completed with status={status}")

        except Exception as e:
            logger.error(f"[WorkflowService] Run {run_id} FAILED: {e}", exc_info=True)
            await self._update_run(
                run_id=run_id,
                status="failed",
                error=str(e)[:500],
            )

    async def _update_run(
        self,
        run_id: str,
        status: str,
        tokens: int = 0,
        final_state: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            values: dict = {
                "status":           status,
                "completed_at":     datetime.now(timezone.utc),
                "total_tokens_used": tokens,
            }
            if final_state:
                values["workflow_state"] = final_state
            if error:
                values["error_message"] = error

            await db.execute(
                update(AgentRun)
                .where(AgentRun.id == uuid.UUID(run_id))
                .values(**values)
            )
            await db.commit()

    def _serialise_state(self, state: dict) -> dict:
        """Make state JSON-serialisable (convert dataclasses to dicts)."""
        import json

        def default(obj):
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)

        return json.loads(json.dumps(dict(state), default=default))

    # ── Status ────────────────────────────────────────────────────────────────

    async def get_run_status(self, run_id: str, db: AsyncSession) -> Optional[dict]:
        result = await db.execute(
            select(AgentRun).where(AgentRun.id == uuid.UUID(run_id))
        )
        run = result.scalar_one_or_none()
        if not run:
            return None
        return {
            "run_id":          str(run.id),
            "course_id":       str(run.course_id),
            "status":          run.status,
            "workflow_type":   run.workflow_type,
            "started_at":      run.started_at.isoformat(),
            "completed_at":    run.completed_at.isoformat() if run.completed_at else None,
            "total_tokens":    run.total_tokens_used,
            "error_message":   run.error_message,
        }

    # ── Approvals ─────────────────────────────────────────────────────────────

    async def submit_approval(
        self,
        content_id:  str,
        reviewer_id: str,
        decision:    str,       # approved | rejected | revised
        comment:     Optional[str],
        revision:    Optional[str],
        db: AsyncSession,
    ) -> dict:
        """Record a human approval decision and update content status."""
        # Record the decision
        record = ApprovalRecord(
            content_id=uuid.UUID(content_id),
            reviewer_id=uuid.UUID(reviewer_id),
            decision=decision,
            comment=comment,
            revision_text=revision,
        )
        db.add(record)

        # Update content approval_status
        final_content = revision if revision and decision == "revised" else None
        await db.execute(
            update(GeneratedContentRecord)
            .where(GeneratedContentRecord.id == uuid.UUID(content_id))
            .values(
                approval_status=decision,
                content=final_content if final_content else GeneratedContentRecord.content,
            )
        )

        # Update episodic memory if reviewer revised/rejected
        if decision in ("revised", "rejected"):
            await self._update_episodic_memory(
                reviewer_id=reviewer_id,
                decision=decision,
                comment=comment,
                db=db,
            )

        await db.flush()
        return {"content_id": content_id, "decision": decision, "recorded": True}

    async def _update_episodic_memory(
        self,
        reviewer_id: str,
        decision:    str,
        comment:     Optional[str],
        db: AsyncSession,
    ) -> None:
        """Append this decision to the reviewer's episodic memory."""
        from db.models.agent_memory import AgentMemory
        from sqlalchemy import select

        result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.user_id == uuid.UUID(reviewer_id),
                AgentMemory.memory_type == "reviewer_preference",
            )
        )
        record = result.scalar_one_or_none()

        episode = {
            "decision": decision,
            "comment":  comment or "",
            "ts":       datetime.now(timezone.utc).isoformat(),
        }

        if record:
            history = record.content.get("history", [])
            history.append(episode)
            record.content = {
                **record.content,
                "history":     history[-20:],    # Keep last 20 decisions
                "preferences": self._summarise_preferences(history),
            }
        else:
            db.add(AgentMemory(
                user_id=uuid.UUID(reviewer_id),
                memory_type="reviewer_preference",
                content={
                    "history":     [episode],
                    "preferences": comment or "",
                },
            ))

    def _summarise_preferences(self, history: list) -> str:
        """Extract preference signals from decision history."""
        rejections = [h["comment"] for h in history if h["decision"] == "rejected" and h["comment"]]
        if not rejections:
            return ""
        return f"Reviewer has previously noted: {'; '.join(rejections[-3:])}"


# Module-level singleton
workflow_service = WorkflowService()
