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

_SEVERITY = {'critical': 0, 'warning': 1}


def pick_gaps(gaps, limit):
    """Worst gaps first, one per gap type before a second of any type, so the cap spreads across problems."""
    ordered = sorted(gaps, key=lambda g: (_SEVERITY.get(g.severity, 2), g.score))
    picked, seen = [], set()
    for g in ordered:
        if g.gap_type not in seen:
            picked.append(g); seen.add(g.gap_type)
    picked += [g for g in ordered if g not in picked]
    return picked[:limit]


TEACHING_ONLY = {"artifact_type": {"$in": ["slides", "transcript", "reading", "other"]}}
DRAFT_TYPE = {"clo_not_covered": "clo", "clo_not_assessed": "quiz", "topic_not_assessed": "quiz", "bloom_level_mismatch": "clo",
              "topic_not_delivered": "exercise", "live_missing_objective": "clo", "live_missing_assessment": "quiz"}


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
                "clo_not_assessed",
                "topic_not_assessed", "bloom_level_mismatch",
                "topic_not_delivered",
                "live_missing_objective", "live_missing_assessment",
            )
        ]
        from config import settings
        actionable = pick_gaps(actionable, settings.generation_max_items_per_run)

        if not actionable:
            logger.info("[Generation] No actionable gaps — skipping generation")
            return {**state, "generation_attempted": True, "current_node": Node.DIRECTOR}

        logger.info(f"[Generation] Generating content for {len(actionable)} gaps")
        from knowledge import language
        objective_texts = [c.get("text") or "" for m in state.get("modules", []) for c in m.get("clos", [])]
        self._language_code = language.detect(objective_texts or [state.get("course_metadata", {}).get("title", "")])
        self._language = language.instruction(self._language_code, "the language of the course materials")

        generated:   List[GeneratedContentItem] = list(state.get("generated_items", []))
        total_tokens = state.get("total_tokens", 0)
        # Intent and structured constraints replace the old "last three rejection comments" string.
        preferences  = state.get("guidance") or state.get("reviewer_preferences", "")
        self._rejected = self._load_rejected(course_id)
        errors       = list(state.get("error_log", []))
        failures     = 0
        self._failure_reasons = []

        for gap in actionable:
            item, tokens = self._generate_for_gap(
                gap, course_id, state, preferences
            )
            if item:
                generated.append(item)
            else:
                failures += 1
            total_tokens += tokens

        logger.info(f"[Generation] Produced {len(generated)} items ({failures} failed)")

        # If every single generation attempt failed (e.g. LLM API key invalid,
        # model decommissioned, rate limited), record it visibly instead of
        # silently completing with zero content and no explanation. This also
        # marks generation as "attempted" so the Director doesn't send us back
        # here again next iteration — without this, an unrecoverable failure
        # (same cause every retry) would loop until max_iterations and fail
        # the whole run with the real cause buried only in application logs.
        if failures and not generated:
            from agents.graph.state import WorkflowError
            from datetime import datetime, timezone
            no_evidence = self._failure_reasons and all("Insufficient source evidence" in r for r in self._failure_reasons)
            invalid_quotes = self._failure_reasons and all("Generated quotation does not occur verbatim" in r for r in self._failure_reasons)
            errors.append(WorkflowError(
                agent=self.name,
                message=(
                    f"No draft was written for {failures} finding(s): no supporting passage was found in the teaching "
                    "material, so nothing could be grounded. Upload the relevant material, or write the change yourself."
                    if no_evidence else
                    f"No draft was written for {failures} finding(s): generated quotations could not be verified "
                    "against their cited sources, even after any configured retry. Review the source evidence or try a different model."
                    if invalid_quotes else
                    f"All {failures} content generation attempt(s) failed — "
                    "check backend logs for the underlying LLM error "
                    "(invalid/expired API key, decommissioned model, or rate limit)."
                ),
                ts=datetime.now(timezone.utc).isoformat(),
            ))

        return {
            **state,
            "generated_items":     generated,
            "generation_attempted": True,
            "error_log":           errors,
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
            "live_missing_objective":  self._gen_clo,
            "live_missing_assessment": self._gen_assessment_question,
        }
        handler = dispatch.get(gap.gap_type)
        if not handler:
            return None, 0

        from types import SimpleNamespace
        from config import settings
        from services import stakeholder_gate, trace
        from services.intent import ref as intent_ref
        spent = [0]
        def generate(extra, model):
            self._model = model                     # a retry may be reassigned to another model
            item, tokens = handler(gap, course_id, state, extra)
            spent[0] += tokens
            return SimpleNamespace(content=item.content, citations=item.citations, model=model or settings.openrouter_model, tokens_used=tokens, item=item)
        models = list(dict.fromkeys(m for m in [settings.openrouter_model, *settings.llm_models[1:], settings.openrouter_fallback_model] if m))[:2]
        task_id = f"{state.get('run_id')}:draft:{gap.gap_id}"
        constraint_ids = [c["id"] for c in state.get("lecturer_constraints") or []]
        try:
            # The Stakeholder gate checks every draft before the lecturer sees it and retries weak ones (bounded).
            with trace.context(task_id=task_id, agent=self.name):
                best, review = stakeholder_gate.produce(
                    generate, content_type=DRAFT_TYPE.get(gap.gap_type, "clo"),
                    target=(self._objective(gap, state) or {}).get("text") or self._topic(gap) or gap.description,
                    intent=state.get("course_intent"), constraint_ids=constraint_ids,
                    rejected_fingerprints=getattr(self, "_rejected", set()), guidance=preferences, subject=("gap", gap.gap_id),
                    models=models)
            best.item.review = {**review, "task_id": task_id, "intent": intent_ref(state.get("course_intent")), "constraint_ids": constraint_ids}
            return best.item, spent[0]
        except Exception as e:
            logger.error(f"[Generation] Failed for gap {gap.gap_id}: {e}", exc_info=True)
            getattr(self, "_failure_reasons", []).append(str(e))
            return None, spent[0]

    def _draft(self, **kwargs):
        """Grounded generation with the model the Stakeholder gate assigned to this attempt, in the course's language."""
        rule = getattr(self, "_language", None)
        if rule:
            kwargs["extra_instructions"] = "\n".join(p for p in (kwargs.get("extra_instructions"), rule) if p)
        return self._get_rag().generate(model=getattr(self, "_model", None), **kwargs)

    def _objective_template(self):
        """The sentence frame for an objective, in the course's language (an English frame made German drafts mixed)."""
        if getattr(self, "_language_code", None) == "de":
            return "Nach Abschluss des Moduls können die Studierenden [Gegenstand] [Verb] ..."
        return "Upon completion of this module, students will be able to [verb] ..."

    @staticmethod
    def _objective(gap, state):
        """The stated objective a finding is about (its wording and level), or None."""
        if gap.affected_entity_type != "clo" or not gap.affected_entity_id:
            return None
        return next((c for m in state.get("modules", []) for c in m.get("clos", []) if str(c.get("id")) == str(gap.affected_entity_id)), None)

    @staticmethod
    def _topic(gap):
        """The topic named in a topic finding ("Week 5 topic 'Dynamic programming' ...", "Topic 'Hash tables' ...")."""
        import re
        match = re.search(r"[Tt]opic '([^']+)'", gap.description or "")
        return match.group(1) if match else None

    def _load_rejected(self, course_id) -> set:
        """Fingerprints of drafts the lecturer already rejected for this course."""
        async def load():
            from db.session import AsyncSessionLocal
            from services.constraints import rejected_fingerprints
            async with AsyncSessionLocal() as db:
                return await rejected_fingerprints(db, course_id)
        try:
            return self._run_async(load())
        except Exception:
            return set()

    # ── CLO Generation ────────────────────────────────────────────────────────

    def _gen_clo(self, gap, course_id, state, preferences):
        course = state.get("course_metadata", {})
        objective = self._objective(gap, state)
        about = (f"The stated objective {objective.get('code') or ''} has no matching teaching material:\n\"{objective['text']}\"\n"
                 f"Finding: {gap.description}") if objective else gap.description
        task   = (
            f"Generate ONE clear, measurable Course Learning Objective (CLO) "
            f"for a {course.get('level','undergraduate')} course '{course.get('title','')}'. "
            f"\n\nThis CLO must address the following identified gap:\n{about}"
            f"\n\nThe CLO must:\n"
            "- Use a measurable Bloom action verb consistent with the stated objective and available material; do not automatically raise its cognitive level\n"
            "- Be specific, measurable, and achievable in one semester\n"
            "- Cite [SOURCE_N] for any content it references\n\n"
            f"Format: '{self._objective_template()}'"
        )
        extra = preferences or "Preserve the course context and academic level; do not assume a national qualification framework."
        result = self._draft(
            task_prompt=task,
            course_id=course_id,
            top_k=8,
            where=TEACHING_ONLY,                                    # not the module manual: it would quote the objective back
            extra_instructions=extra,
            query=objective["text"] if objective else gap.description,
        )
        bloom, _ = classify_text(result.content)
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="clo",
            title=f"Suggested CLO — {(objective.get('code') + ': ' + objective['text']) if objective else gap.description}"[:120],
            content=result.content,
            bloom_level=bloom,
            source_gap_id=gap.gap_id,
            citations=result.citations,
            confidence=self._confidence(result),
        ), result.tokens_used

    # ── Assessment Question ───────────────────────────────────────────────────

    def _gen_assessment_question(self, gap, course_id, state, preferences):
        # Find the CLO's Bloom level for question targeting
        objective = self._objective(gap, state)
        clo_text  = objective["text"] if objective else gap.description
        bloom     = (objective or {}).get("bloom_level") or classify_text(clo_text)[0]
        bloom     = bloom or "apply"
        verbs     = BLOOM_VERBS.get(bloom, ["describe"])[:3]

        task = (
            f"Generate ONE assessment question at the '{bloom.upper()}' level "
            f"of Bloom's Taxonomy (using verbs such as: {', '.join(verbs)}).\n\n"
            f"This question must evaluate the following CLO:\n{clo_text}\n\n"
            "Requirements:\n"
            "- Include clear marking criteria (how many marks, what earns full credit)\n"
            "- Cite [SOURCE_N] for any content referenced in the question\n"
            "- Suitable for a formal university assessment\n\n"
            "Format:\n"
            "Question: ...\nMarks: X\nMarking Criteria: ..."
        )
        result = self._draft(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            where=TEACHING_ONLY,                                    # a question rests on what was taught
            extra_instructions=preferences,
            query=clo_text,
        )
        return GeneratedContentItem(
            item_id=str(uuid.uuid4()),
            content_type="quiz",
            title=f"Assessment Question — {bloom.title()} Level" + (f" — {objective.get('code')}" if objective and objective.get("code") else ""),
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
        result = self._draft(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            where={"artifact_type": {"$in": ["slides", "transcript"]}},
            extra_instructions=preferences,
            query=topic,
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
            f"Format: '{self._objective_template()}'"
        )
        result = self._draft(
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
        result = self._draft(
            task_prompt=task,
            course_id=course_id,
            top_k=6,
            where=TEACHING_ONLY,                                    # the schedule line naming the topic is not material for an exercise
            extra_instructions=preferences,
            query=self._topic(gap) or gap.description,
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
