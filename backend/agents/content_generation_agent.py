"""
LECTIO — Content Generation Agent

Generates educational content to fill gaps identified by alignment agents.
Every output is RAG-grounded — citations required for every claim.

Generation targets (by gap type):
  clo_not_covered      → draft replacement/supplementary CLO
  clo_not_assessed     → suggest assessment question at correct Bloom level
  topic_not_delivered  → suggest exercise or discussion activity
  topic_not_assessed   → generate quiz question(s)
  bloom_level_mismatch → suggest revised CLO at correct level
"""

import logging
import uuid
from typing import List

from agents.base_agent import BaseAgent
from agents.graph.state import (
    AlignmentGap, GeneratedContentItem,
    LectioWorkflowState, Node,
)
from knowledge.bloom_classifier import BLOOM_VERBS, classify_text

logger = logging.getLogger(__name__)

# Max items to generate per run (respect Groq free tier rate limits)
MAX_ITEMS_PER_RUN = 8


class ContentGenerationAgent(BaseAgent):
    name = "content_generation_agent"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        course_id = state["course_id"]
        all_gaps  = state.get("all_gaps", [])

        # Filter to actionable gaps only
        actionable = [
            g for g in all_gaps
            if isinstance(g, AlignmentGap)
            and g.severity in ("critical", "warning")
            and g.gap_type in (
                "clo_not_covered", "clo_not_assessed",
                "topic_not_assessed", "bloom_level_mismatch",
                "topic_not_delivered",
            )
        ][:MAX_ITEMS_PER_RUN]

        if not actionable:
            logger.info("[Generation] No actionable gaps — skipping generation")
            return {**state, "current_node": Node.DIRECTOR}

        logger.info(f"[Generation] Generating content for {len(actionable)} gaps")

        generated:   List[GeneratedContentItem] = list(state.get("generated_items", []))
        total_tokens = state.get("total_tokens", 0)
        preferences  = state.get("reviewer_preferences", "")

        for gap in actionable:
            item, tokens = self._generate_for_gap(
                gap, course_id, state, preferences
            )
            if item:
                generated.append(item)
            total_tokens += tokens

        logger.info(f"[Generation] Produced {len(generated)} items")
        return {
            **state,
            "generated_items": generated,
            "total_tokens":    total_tokens,
            "current_node":    Node.DIRECTOR,
        }

    # ── Dispatch by gap type ──────────────────────────────────────────────────

    def _generate_for_gap(
        self,
        gap:         AlignmentGap,
        course_id:   str,
        state:       LectioWorkflowState,
        preferences: str,
    ) -> tuple[GeneratedContentItem | None, int]:
        dispatch = {
            "clo_not_covered":     self._gen_clo,
            "clo_not_assessed":    self._gen_assessment_question,
            "topic_not_assessed":  self._gen_quiz_question,
            "bloom_level_mismatch": self._gen_revised_clo,
            "topic_not_delivered": self._gen_exercise,
        }
        handler = dispatch.get(gap.gap_type)
        if not handler:
            return None, 0

        try:
            return handler(gap, course_id, state, preferences)
        except Exception as e:
            logger.error(f"[Generation] Failed for gap {gap.gap_id}: {e}", exc_info=True)
            return None, 0

    # ── CLO Generation ────────────────────────────────────────────────────────

    def _gen_clo(self, gap, course_id, state, preferences):
        course = state.get("course_metadata", {})
        task   = (
            f"Generate ONE clear, measurable Course Learning Objective (CLO) "
            f"for a {course.get('level','undergraduate')} course '{course.get('title','')}'. "
            f"\n\nThis CLO must address the following identified gap:\n{gap.description}"
            f"\n\nThe CLO must:\n"
            "- Start with a Bloom's Taxonomy action verb at the APPLY level or above\n"
            "- Be specific, measurable, and achievable in one semester\n"
            "- Cite [SOURCE_N] for any content it references\n\n"
            "Format: 'Upon completion of this module, students will be able to [verb] ...'"
        )
        extra = preferences or "Ensure CLOs are written in South African NQF-aligned language."
        result = self._get_rag().generate(
            task_prompt=task,
            course_id=course_id,
            top_k=8,
            extra_instructions=extra,
        )
        bloom, _ = classify_text(result.content)
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="clo",
            title=f"Suggested CLO — {gap.description[:60]}",
            content=result.content,
            bloom_level=bloom,
            source_gap_id=gap.gap_id,
            citations=result.citations,
            confidence=self._confidence(result),
        ), result.tokens_used

    # ── Assessment Question ───────────────────────────────────────────────────

    def _gen_assessment_question(self, gap, course_id, state, preferences):
        # Find the CLO's Bloom level for question targeting
        clo_text  = gap.description
        bloom, _  = classify_text(clo_text)
        bloom     = bloom or "apply"
        verbs     = BLOOM_VERBS.get(bloom, ["describe"])[:3]

        task = (
            f"Generate ONE assessment question at the '{bloom.upper()}' level "
            f"of Bloom's Taxonomy (using verbs such as: {', '.join(verbs)}).\n\n"
            f"This question must evaluate the following CLO:\n{gap.description}\n\n"
            "Requirements:\n"
            "- Include clear marking criteria (how many marks, what earns full credit)\n"
            "- Cite [SOURCE_N] for any content referenced in the question\n"
            "- Suitable for a formal university assessment\n\n"
            "Format:\n"
            "Question: ...\nMarks: X\nMarking Criteria: ..."
        )
        result = self._get_rag().generate(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            extra_instructions=preferences,
        )
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="quiz",
            title=f"Assessment Question — {bloom.title()} Level",
            content=result.content,
            bloom_level=bloom,
            source_gap_id=gap.gap_id,
            citations=result.citations,
            confidence=self._confidence(result),
        ), result.tokens_used

    # ── Quiz Question ─────────────────────────────────────────────────────────

    def _gen_quiz_question(self, gap, course_id, state, preferences):
        topic = gap.description.replace("Topic '", "").split("'")[0]
        task  = (
            f"Generate 2 multiple-choice quiz questions testing understanding of: '{topic}'.\n\n"
            "For each question provide:\n"
            "- The question stem\n"
            "- 4 options (A, B, C, D)\n"
            "- The correct answer with a one-sentence explanation\n"
            "- Bloom's level (remember/understand/apply)\n"
            "- Citation [SOURCE_N] for the content the question is based on\n\n"
            "Keep questions clear and unambiguous."
        )
        result = self._get_rag().generate(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            where={"artifact_type": {"$in": ["slides", "transcript"]}},
            extra_instructions=preferences,
        )
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="quiz",
            title=f"Quiz Questions — {topic[:50]}",
            content=result.content,
            bloom_level="understand",
            source_gap_id=gap.gap_id,
            citations=result.citations,
            confidence=self._confidence(result),
        ), result.tokens_used

    # ── Revised CLO ───────────────────────────────────────────────────────────

    def _gen_revised_clo(self, gap, course_id, state, preferences):
        task = (
            f"The following CLO has a Bloom's level mismatch with its assessment:\n"
            f"{gap.description}\n\n"
            "Rewrite the CLO at the correct Bloom's level so that it is "
            "achievable given the course content. "
            "Cite [SOURCE_N] for content that supports the revised CLO.\n\n"
            "Format: 'Upon completion, students will be able to [verb] ...'"
        )
        result = self._get_rag().generate(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            extra_instructions=preferences,
        )
        bloom, _ = classify_text(result.content)
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="clo",
            title="Revised CLO — Bloom Level Correction",
            content=result.content,
            bloom_level=bloom,
            source_gap_id=gap.gap_id,
            citations=result.citations,
            confidence=self._confidence(result),
        ), result.tokens_used

    # ── Exercise ──────────────────────────────────────────────────────────────

    def _gen_exercise(self, gap, course_id, state, preferences):
        task = (
            f"Design a practical exercise or activity for the following undelivered topic:\n"
            f"{gap.description}\n\n"
            "The exercise should:\n"
            "- Be completable in 30–45 minutes\n"
            "- Include clear learning outcomes, instructions, and expected output\n"
            "- Be grounded in the course materials (cite [SOURCE_N])\n"
            "- Include a brief facilitator guide"
        )
        result = self._get_rag().generate(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            extra_instructions=preferences,
        )
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="exercise",
            title=f"Suggested Exercise — {gap.description[:60]}",
            content=result.content,
            bloom_level="apply",
            source_gap_id=gap.gap_id,
            citations=result.citations,
            confidence=self._confidence(result),
        ), result.tokens_used

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _confidence(self, result) -> float:
        """Estimate confidence from citation density."""
        n_citations = len(result.citations)
        n_words     = len(result.content.split())
        if n_words == 0:
            return 0.0
        density = n_citations / max(n_words / 50, 1)   # citations per 50 words
        return min(0.95, 0.50 + density * 0.20)
