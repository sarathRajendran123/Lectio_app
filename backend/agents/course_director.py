"""
LECTIO — Course Director Agent
Supervisor node in the LangGraph graph.

Responsibilities:
  1. Load course context from PostgreSQL on first invocation
  2. Route to the correct next agent based on workflow state
  3. Merge alignment results from parallel agents
  4. Decide when to trigger generation vs proceed to HITL
  5. Guard against infinite loops (max_iterations)

Routing logic:
  START  → load context → META_CONTENT (always first)
         → CONTENT_ASSESSMENT (parallel in concept, sequential in graph)
         → META_ASSESSMENT
         → CONTENT_DELIVERY
         → CONTENT_GENERATION (only if gaps found requiring content)
         → STAKEHOLDER (always last)
         → END
"""

import logging
from typing import List

from agents.base_agent import BaseAgent
from agents.graph.state import (
    AlignmentGap, AlignmentResult, LectioWorkflowState,
    Node, WorkflowStatus,
)

logger = logging.getLogger(__name__)

# Alignment agents in execution order
ALIGNMENT_SEQUENCE = [
    Node.META_CONTENT,
    Node.CONTENT_ASSESSMENT,
    Node.META_ASSESSMENT,
    Node.CONTENT_DELIVERY,
]


class CourseDirectorAgent(BaseAgent):
    name = "course_director"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        iteration = state.get("iteration", 0) + 1

        # Safety guard
        if iteration > state.get("max_iterations", 20):
            logger.error("Max iterations exceeded — aborting workflow")
            return {
                **state,
                "iteration": iteration,
                "workflow_status": WorkflowStatus.FAILED,
                "current_node": Node.END,
            }

        updates: dict = {"iteration": iteration}

        # ── Step 1: Load course context (first call only) ──────────────────────
        if not state.get("course_metadata"):
            logger.info(f"[Director] Loading course context for {state['course_id']}")
            context = self._load_course_context(state["course_id"])
            updates.update(context)

        # ── Step 2: Determine next node ────────────────────────────────────────
        completed = set(state.get("alignment_results", {}).keys())
        next_node  = self._route(completed, state)
        updates["current_node"] = next_node

        # ── Step 3: If all alignment done → merge gaps ─────────────────────────
        alignment_keys = {
            Node.META_CONTENT:       "metadata_content",
            Node.CONTENT_ASSESSMENT: "content_assessment",
            Node.META_ASSESSMENT:    "metadata_assessment",
            Node.CONTENT_DELIVERY:   "content_delivery",
        }
        all_done = all(
            alignment_keys[n] in completed for n in ALIGNMENT_SEQUENCE
        )

        if all_done and not state.get("all_gaps"):
            merged = self._merge_gaps(state.get("alignment_results", {}))
            updates["all_gaps"] = merged
            logger.info(
                f"[Director] All alignment checks done. "
                f"Merged {len(merged)} unique gaps."
            )

        logger.info(f"[Director] Routing → {next_node} (iteration {iteration})")
        return {**state, **updates}

    # ── Routing ───────────────────────────────────────────────────────────────

    def _route(self, completed: set, state: LectioWorkflowState) -> str:
        alignment_keys = {
            "metadata_content":    Node.META_CONTENT,
            "content_assessment":  Node.CONTENT_ASSESSMENT,
            "metadata_assessment": Node.META_ASSESSMENT,
            "content_delivery":    Node.CONTENT_DELIVERY,
        }

        # Run alignment agents in order
        for key, node in alignment_keys.items():
            if key not in completed:
                return node

        # All alignment done — decide on generation
        gaps = state.get("all_gaps") or []
        needs_generation = any(
            g.severity in ("critical", "warning") for g in gaps
            if isinstance(g, AlignmentGap)
        )
        generated = state.get("generated_items", [])

        if needs_generation and not generated:
            return Node.CONTENT_GENERATION

        # Nothing left to do — go to HITL
        return Node.STAKEHOLDER

    # ── Context Loader ────────────────────────────────────────────────────────

    def _load_course_context(self, course_id: str) -> dict:
        """
        Load structured course data from PostgreSQL synchronously.
        Called once at the start of each workflow run.
        Note: agents run in sync context (LangGraph nodes are sync by default).
        """
        return self._run_async(self._async_load(course_id))

    async def _async_load(self, course_id: str) -> dict:
        from db.session import AsyncSessionLocal
        from db.repositories.course_repository import CourseRepository

        async with AsyncSessionLocal() as db:
            repo   = CourseRepository(db)
            course = await repo.get_by_id_with_modules(course_id)

            if not course:
                return {"course_metadata": {}, "modules": [], "assessments": []}

            metadata = {
                "id":       str(course.id),
                "code":     course.code,
                "title":    course.title,
                "level":    course.level,
                "credits":  course.credits,
                "semester": course.semester,
                "year":     course.year,
            }

            modules = []
            for mod in course.modules:
                clos = [
                    {
                        "id":          str(clo.id),
                        "code":        clo.code,
                        "text":        clo.text,
                        "bloom_level": clo.bloom_level,
                    }
                    for clo in mod.learning_objectives
                ]
                weeks = []
                for wk in mod.weeks:
                    topics = [
                        {"id": str(t.id), "title": t.title}
                        for t in wk.topics
                    ]
                    weeks.append({
                        "week_number": wk.week_number,
                        "title":       wk.title,
                        "topics":      topics,
                    })
                modules.append({
                    "id":              str(mod.id),
                    "title":           mod.title,
                    "sequence_number": mod.sequence_number,
                    "clos":            clos,
                    "weeks":           weeks,
                })

            assessments = [
                {
                    "id":             str(a.id),
                    "title":          a.title,
                    "type":           a.type,
                    "weight_percent": float(a.weight_percent or 0),
                    "week_due":       a.week_due,
                }
                for a in course.assessments
            ]

            return {
                "course_metadata": metadata,
                "modules":         modules,
                "assessments":     assessments,
            }

    # ── Gap Merging ───────────────────────────────────────────────────────────

    def _merge_gaps(self, results: dict) -> List[AlignmentGap]:
        """
        Merge gaps from all agents, deduplicating by (gap_type, affected_entity_id).
        When the same entity is flagged by multiple agents, keep the highest severity.
        """
        seen:   dict = {}

        severity_rank = {"critical": 3, "warning": 2, "info": 1, "pass": 0}

        for result in results.values():
            if not isinstance(result, AlignmentResult):
                continue
            for gap in result.gaps:
                key = (gap.gap_type, gap.affected_entity_id or gap.description[:50])
                if key in seen:
                    existing = seen[key]
                    if severity_rank.get(gap.severity, 0) > severity_rank.get(existing.severity, 0):
                        seen[key] = gap
                else:
                    seen[key] = gap

        return list(seen.values())