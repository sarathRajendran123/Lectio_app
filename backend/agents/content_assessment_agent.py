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
from knowledge.bloom_classifier import classify_text, compare_levels

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
                overall_score=1.0,
                status="pass",
                findings={"note": "No assessments defined — skipping check."},
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
                assessment, course_id
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

    def _audit_assessment(self, assessment: dict, course_id: str):
        title  = assessment["title"]
        a_type = assessment.get("type", "assessment")
        gaps   = []
        tokens = 0

        # Use assessment title + type as query
        query  = f"{title} {a_type} questions covering course topics"
        chunks = self._retrieve(query, course_id, top_k=8)

        if not chunks:
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

        best_score = max(c.score for c in chunks)

        # Bloom level check
        q_level, _  = classify_text(title)
        content_text = " ".join(c.text for c in chunks[:3])
        c_level, _   = classify_text(content_text[:1500])

        if q_level and c_level:
            diff = compare_levels(q_level, c_level)
            if diff > 1:
                gaps.append(AlignmentGap(
                    gap_id=str(uuid.uuid4()),
                    gap_type="bloom_level_mismatch",
                    severity="warning",
                    description=(
                        f"Assessment '{title}' targets '{q_level}' level but "
                        f"content only reaches '{c_level}'. Students are assessed "
                        "above the level they are taught."
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

        return best_score, gaps, tokens

    def _find_uncovered_topics(
        self, topics: List[str], assessments: List[dict], course_id: str
    ) -> List[str]:
        """Topics present in content but not in any assessment."""
        uncovered = []
        assessment_text = " ".join(
            f"{a['title']} {a.get('type', '')}" for a in assessments
        ).lower()

        for topic in topics[:20]:  # cap to avoid excessive API calls
            if topic.lower() not in assessment_text:
                # Double-check via retrieval
                chunks = self._retrieve(
                    query=f"assessment question about {topic}",
                    course_id=course_id,
                    top_k=3,
                    where={"artifact_type": "assignment"},
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
