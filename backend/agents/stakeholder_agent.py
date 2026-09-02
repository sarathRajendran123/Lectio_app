"""
LECTIO — Stakeholder Agent
Final node before HITL pause.

Responsibilities:
  1. Load reviewer preferences from episodic memory
  2. Create ApprovalRequest records for every generated item
  3. Persist alignment reports and generated content to PostgreSQL
  4. Set workflow status to WAITING_FOR_HUMAN (pauses LangGraph)
  5. On resume (after human decisions): record decisions + learn preferences
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List

from agents.base_agent import BaseAgent
from agents.graph.state import (
    ApprovalRequest, GeneratedContentItem,
    LectioWorkflowState, Node, WorkflowStatus,
)

logger = logging.getLogger(__name__)


class StakeholderAgent(BaseAgent):
    name = "stakeholder_agent"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        course_id    = state["course_id"]
        run_id       = state["run_id"]
        initiated_by = state.get("initiated_by", "")
        generated    = state.get("generated_items", [])

        # 1. Load reviewer preferences from episodic memory
        preferences = self._load_preferences(initiated_by)

        # 2. Persist alignment reports to DB
        self._persist_reports(state, run_id, course_id)

        # 3. Persist generated content + create approval queue
        pending = self._create_approval_queue(
            generated, run_id, course_id, initiated_by
        )

        logger.info(
            f"[Stakeholder] {len(pending)} items queued for approval | "
            f"run={run_id}"
        )

        # 4. If nothing to approve → complete workflow
        if not pending:
            return {
                **state,
                "reviewer_preferences": preferences,
                "workflow_status":      WorkflowStatus.COMPLETED,
                "current_node":         Node.END,
            }

        # 5. Pause for human review
        return {
            **state,
            "reviewer_preferences":  preferences,
            "pending_approvals":     pending,
            "workflow_status":       WorkflowStatus.WAITING,
            "current_node":          Node.END,   # LangGraph halts here
        }

    # ── Episodic Memory ───────────────────────────────────────────────────────

    def _load_preferences(self, user_id: str) -> str:
        """
        Load reviewer preference patterns from agent_memory table.
        Returns a plain-English string injected into generation prompts.
        """
        if not user_id:
            return ""
        try:
            return self._run_async(self._async_load_prefs(user_id))
        except Exception as e:
            logger.warning(f"[Stakeholder] Could not load preferences: {e}")
            return ""

    async def _async_load_prefs(self, user_id: str) -> str:
        from db.session import AsyncSessionLocal
        from sqlalchemy import select
        from db.models.agent_memory import AgentMemory

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == uuid.UUID(user_id),
                    AgentMemory.memory_type == "reviewer_preference",
                )
                .order_by(AgentMemory.updated_at.desc())
                .limit(1)
            )
            record = result.scalar_one_or_none()
            if record:
                return record.content.get("preferences", "")
        return ""

    # ── DB Persistence ────────────────────────────────────────────────────────

    def _persist_reports(self, state: LectioWorkflowState, run_id: str, course_id: str):
        """Write alignment reports to PostgreSQL alignment_reports table."""
        try:
            self._run_async(self._async_persist_reports(state, run_id, course_id))
        except Exception as e:
            logger.error(f"[Stakeholder] Failed to persist reports: {e}", exc_info=True)

    async def _async_persist_reports(self, state, run_id, course_id):
        from db.session import AsyncSessionLocal
        from db.models.report import AlignmentReport, AlignmentGapRecord

        async with AsyncSessionLocal() as db:
            for report_type, result in state.get("alignment_results", {}).items():
                if not hasattr(result, "to_dict"):
                    continue
                report = AlignmentReport(
                    run_id=uuid.UUID(run_id),
                    course_id=uuid.UUID(course_id),
                    report_type=report_type,
                    overall_score=result.overall_score,
                    status=result.status,
                    gap_count=len(result.gaps),
                    findings=result.to_dict(),
                    recommendations=result.recommendations,
                )
                db.add(report)
                await db.flush()

                for gap in result.gaps:
                    db.add(AlignmentGapRecord(
                        report_id=report.id,
                        gap_type=gap.gap_type,
                        severity=gap.severity,
                        description=gap.description,
                        affected_entity_type=gap.affected_entity_type,
                        affected_entity_id=(
                            uuid.UUID(gap.affected_entity_id)
                            if gap.affected_entity_id else None
                        ),
                        score=gap.score,
                        recommendation=gap.recommendation,
                    ))

            await db.commit()

    def _create_approval_queue(
        self,
        generated:    List[GeneratedContentItem],
        run_id:       str,
        course_id:    str,
        reviewer_id:  str,
    ) -> List[ApprovalRequest]:
        """Persist generated content and build ApprovalRequest list."""
        try:
            return self._run_async(
                self._async_create_queue(generated, run_id, course_id, reviewer_id)
            )
        except Exception as e:
            logger.error(f"[Stakeholder] Failed to create approval queue: {e}", exc_info=True)
            return []

    async def _async_create_queue(self, generated, run_id, course_id, reviewer_id):
        from db.session import AsyncSessionLocal
        from db.models.generated_content import GeneratedContentRecord

        pending = []
        async with AsyncSessionLocal() as db:
            for item in generated:
                record = GeneratedContentRecord(
                    id=uuid.UUID(item.item_id),
                    run_id=uuid.UUID(run_id),
                    course_id=uuid.UUID(course_id),
                    content_type=item.content_type,
                    title=item.title,
                    content=item.content,
                    bloom_level=item.bloom_level,
                    citations=item.citations,
                    confidence_score=item.confidence,
                    approval_status="pending",
                )
                db.add(record)
                pending.append(ApprovalRequest(
                    request_id=str(uuid.uuid4()),
                    content_item_id=item.item_id,
                    content_type=item.content_type,
                    title=item.title,
                    content=item.content,
                    reviewer_id=reviewer_id or None,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ))

            await db.commit()

        return pending