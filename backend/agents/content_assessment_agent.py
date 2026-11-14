"""
LECTIO — Content-Assessment Alignment Agent

Verifies that assessments evaluate what is actually taught.

Checks:
  1. For each assessment question → retrieve content chunks → score coverage
  2. Topic coverage matrix: which topics have assessment questions?
  3. Bloom level of questions vs content depth (mismatch detection)
  4. Mark weight vs content emphasis (high-mark topics should have more coverage)
"""

import logging
import uuid
from typing import List

from agents.base_agent import BaseAgent
from agents.graph.state import (
    AlignmentGap, AlignmentResult, LectioWorkflowState, Node,
)
from knowledge.bloom_classifier import classify_text, compare_levels, level_to_int

logger = logging.getLogger(__name__)

COVERAGE_THRESHOLD = 0.60


class ContentAssessmentAlignmentAgent(BaseAgent):
    name = "content_assessment_agent"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        course_id   = state["course_id"]
        assessments = state.get("assessments", [])
        modules     = state.get("modules", [])

        if not assessments:
            return self._store(state, AlignmentResult(
                agent_name=self.name,
                report_type="content_assessment",
                overall_score=0.0,
                status="needs_review",
                findings={"reason": "No exam, exercise or quiz uploaded: upload one (type exam or assignment) to compare what is taught with what is tested."},
            ))

        # Collect all topics from modules
        all_topics = []
        for mod in modules:
            for wk in mod.get("weeks", []):
                for t in wk.get("topics", []):
                    all_topics.append(t["title"])

        gaps: List[AlignmentGap]  = []
        scores: List[float]       = []
        findings: dict            = {
            "assessment_scores": [],
            "uncovered_topics":  [],
        }
        total_tokens = 0

        for assessment in assessments:
            score, assessment_gaps, tokens = self._audit_assessment(
                assessment, course_id, [clo for mod in modules for clo in mod.get("clos", [])]
            )
            scores.append(score)
            total_tokens += tokens
            gaps.extend(assessment_gaps)
            findings["assessment_scores"].append({
                "title":  assessment["title"],
                "type":   assessment.get("type", "unknown"),
                "score":  round(score, 3),
                "status": "pass" if score >= COVERAGE_THRESHOLD else "fail",
            })

        # Check for topics with NO assessment coverage
        uncovered = self._find_uncovered_topics(all_topics, assessments, course_id)
        findings["uncovered_topics"] = uncovered
        for topic in uncovered:
            gaps.append(AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="topic_not_assessed",
                severity="warning",
                description=f"Topic '{topic}' has lecture content but no assessment questions.",
                affected_entity_type="topic",
                affected_entity_id=None,
                score=0.0,
                recommendation=(
                    f"Add assessment question(s) covering '{topic}' "
                    "to ensure it is formally evaluated."
                ),
            ))

        overall = sum(scores) / len(scores) if scores else 1.0
        status  = "pass" if overall >= 0.75 else "warning" if overall >= 0.55 else "fail"

        result = AlignmentResult(
            agent_name=self.name,
            report_type="content_assessment",
            overall_score=round(overall, 4),
            status=status,
            gaps=gaps,
            findings=findings,
            recommendations=self._recommendations(gaps, uncovered),
        )

        logger.info(
            f"[ContentAssessment] score={overall:.3f} ({status}) "
            f"| {len(gaps)} gaps | {len(uncovered)} uncovered topics"
        )
        updated = self._store(state, result)
        updated["total_tokens"] = state.get("total_tokens", 0) + total_tokens
        return updated

    def _audit_assessment(self, assessment: dict, course_id: str, objectives=()):
        """Each question is compared with the teaching material on its own; an exam is not one block of text."""
        from config import settings
        from rag.lexical import lexical_score
        title  = assessment["title"]
        gaps   = []
        tokens = 0
        questions = [q["text"] for q in assessment.get("questions", []) if (q.get("text") or "").strip()][:15]
        units = list(enumerate(questions, start=1)) if len(questions) > 1 else [(None, " ".join(questions) or assessment.get("description") or title)]
        where = {"artifact_type": {"$in": ["slides", "transcript", "reading", "other"]}}
        found = [(number, text, self._retrieve(text, course_id, top_k=8, where=where)) for number, text in units]

        if not any(chunks for _, _, chunks in found):
            gap = AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="assessment_no_content",
                severity="warning",
                description=(
                    f"Assessment '{title}' cannot be matched to any course content. "
                    "It may cover topics not present in uploaded materials."
                ),
                affected_entity_type="assessment",
                affected_entity_id=assessment.get("id"),
                score=0.0,
                recommendation="Upload the assessment document and verify topic coverage.",
            )
            return 0.0, [gap], tokens

        scores = []
        for number, text, chunks in found:
            label = f"Assessment {title!r}" + (f", question {number}," if number else "")
            quoted = f' Question: "{text[:120]}"' if number else ""
            best_score = max((c.score for c in chunks), default=0.0)
            scores.append(best_score)

            if best_score < COVERAGE_THRESHOLD:
                gaps.append(AlignmentGap(str(uuid.uuid4()),"assessment_weak_support","warning",
                    f"{label} has weak support in the supplied teaching materials. Confirm missing documents and independent-study expectations before changing it.{quoted}",
                    "assessment",assessment.get("id"),round(best_score,4),
                    "Review the cited materials and the intended assessment scope.",[c.chunk_id for c in chunks[:3]]))

            # Bloom level check. Lecture prose rarely uses the verbs of the level it prepares for, so a question whose
            # level a stated objective on the same subject asks for is not reported.
            q_level, _  = classify_text(text)
            c_level, _  = classify_text(" ".join(c.text for c in chunks[:3])[:1500])
            if q_level and c_level and level_to_int(q_level) - level_to_int(c_level) > 1:
                intended = any(o.get("bloom_level") and level_to_int(o["bloom_level"]) >= level_to_int(q_level) - 1
                               and lexical_score(o["text"], text) >= settings.assessment_objective_match for o in objectives)
                if not intended:
                    gaps.append(AlignmentGap(
                        gap_id=str(uuid.uuid4()),
                        gap_type="bloom_level_mismatch",
                        severity="warning",
                        description=(
                            f"{label} targets '{q_level}' level but "
                            f"content only reaches '{c_level}'. The verb heuristic suggests a possible mismatch "
                            f"requiring lecturer review.{quoted}"
                        ),
                        affected_entity_type="assessment",
                        affected_entity_id=assessment.get("id"),
                        score=round(best_score, 4),
                        recommendation=(
                            f"Either raise content depth to '{q_level}' level or "
                            f"adjust assessment to '{c_level}' level."
                        ),
                        evidence_chunk_ids=[c.chunk_id for c in chunks[:2]],
                    ))

        return sum(scores) / len(scores), gaps, tokens

    def _find_uncovered_topics(
        self, topics: List[str], assessments: List[dict], course_id: str
    ) -> List[str]:
        """Topics present in content but not in any assessment."""
        from rag.lexical import terms
        uncovered = []
        # What the assessments actually ask, not only their titles (a title is often just the file name).
        assessment_text = " ".join(
            " ".join([a["title"], a.get("description") or "", *(q.get("text") or "" for q in a.get("questions", []))])
            for a in assessments
        ).lower()
        asked = {word[:4] for word in terms(assessment_text)}      # 4-letter stems: "sorting" matches "sort", "Hashtabellen" "Hashtabelle"

        for topic in topics[:20]:  # cap to avoid excessive API calls
            stems = {word[:4] for word in terms(topic)}
            named = bool(stems) and len(stems & asked) / len(stems) >= 0.5
            if topic.lower() not in assessment_text and not named:
                # Double-check via retrieval, in every kind of assessment document
                chunks = self._retrieve(
                    query=topic,
                    course_id=course_id,
                    top_k=3,
                    where={"artifact_type": {"$in": ["assignment", "exam", "assessment"]}},
                )
                if not chunks or max(c.score for c in chunks) < 0.5:
                    uncovered.append(topic)

        return uncovered

    def _recommendations(self, gaps, uncovered) -> List[str]:
        recs = []
        bloom_mismatches = [g for g in gaps if g.gap_type == "bloom_level_mismatch"]
        if bloom_mismatches:
            recs.append(
                f"{len(bloom_mismatches)} assessment(s) assess at a higher Bloom's level "
                "than the content supports. Review lecture depth."
            )
        if uncovered:
            recs.append(
                f"{len(uncovered)} topic(s) are taught but never assessed. "
                "Consider adding formative or summative questions."
            )
        return recs

    def _store(self, state: LectioWorkflowState, result: AlignmentResult) -> dict:
        results = dict(state.get("alignment_results", {}))
        results["content_assessment"] = result
        return {**state, "alignment_results": results, "current_node": Node.DIRECTOR}
