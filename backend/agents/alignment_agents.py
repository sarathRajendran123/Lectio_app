"""
LECTIO — Metadata-Assessment Alignment Agent

Directly cross-references CLOs ↔ Assessments, bypassing content.
Catches: CLOs with no assessment, assessments testing unstated objectives.
"""

import logging
import uuid
from typing import List

from agents.base_agent import BaseAgent
from agents.graph.state import (
    AlignmentGap, AlignmentResult, LectioWorkflowState, Node,
)
from knowledge.bloom_classifier import classify_text

logger = logging.getLogger(__name__)


class MetadataAssessmentAlignmentAgent(BaseAgent):
    name = "metadata_assessment_agent"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        modules     = state.get("modules", [])
        assessments = state.get("assessments", [])
        course_id   = state["course_id"]

        all_clos = []
        for mod in modules:
            for clo in mod.get("clos", []):
                all_clos.append(clo)

        if not all_clos or not assessments:
            return self._store(state, AlignmentResult(
                agent_name=self.name,
                report_type="metadata_assessment",
                overall_score=1.0,
                status="pass",
                findings={"note": "Insufficient data (no CLOs or no assessments)."},
            ))

        gaps:     List[AlignmentGap] = []
        scores:   List[float]        = []
        findings: dict               = {"clo_assessment_map": []}

        assessment_text = " ".join(
            f"{a['title']} {a.get('type','')}" for a in assessments
        ).lower()

        for clo in all_clos:
            clo_text  = clo["text"]
            clo_code  = clo.get("code", "CLO?")

<<<<<<< HEAD
            # Retrieve from assessment artifacts ONLY. Syllabus/content
            # artifacts must be excluded here: a CLO's own definition always
            # appears in the syllabus (that's where it's stated), so
            # including "syllabus" made every CLO trivially match its own
            # text and register as "assessed" even when no actual assessment
            # tests it. This agent's whole purpose is to check assessments
            # in isolation, bypassing content — the filter needs to match that.
=======
            # Retrieve from assessment artifacts
>>>>>>> 0769384aa5cfe90c2fafe2f4f7f21aeb558648b0
            chunks = self._retrieve(
                query=clo_text,
                course_id=course_id,
                top_k=6,
<<<<<<< HEAD
                where={"artifact_type": {"$in": ["assignment"]}},
=======
                where={"artifact_type": {"$in": ["assignment", "syllabus"]}},
>>>>>>> 0769384aa5cfe90c2fafe2f4f7f21aeb558648b0
            )

            best_score = max((c.score for c in chunks), default=0.0)
            covered    = best_score >= 0.55 or clo_text[:30].lower() in assessment_text

            scores.append(1.0 if covered else 0.0)
            findings["clo_assessment_map"].append({
                "code":    clo_code,
                "text":    clo_text[:100],
                "covered": covered,
                "score":   round(best_score, 3),
            })

            if not covered:
                # Check Bloom level of CLO vs assessments
                clo_bloom, _ = classify_text(clo_text)
                gaps.append(AlignmentGap(
                    gap_id=str(uuid.uuid4()),
                    gap_type="clo_not_assessed",
                    severity="critical",
                    description=(
                        f"{clo_code} is not evaluated by any assessment. "
                        f"CLO: '{clo_text[:100]}'"
                    ),
                    affected_entity_type="clo",
                    affected_entity_id=clo.get("id"),
                    score=round(best_score, 4),
                    recommendation=(
                        f"Add an assessment item directly testing: {clo_text[:80]}"
                    ),
                    evidence_chunk_ids=[c.chunk_id for c in chunks[:2]],
                ))

        overall = sum(scores) / len(scores) if scores else 1.0
        status  = "pass" if overall >= 0.80 else "warning" if overall >= 0.60 else "fail"

        result = AlignmentResult(
            agent_name=self.name,
            report_type="metadata_assessment",
            overall_score=round(overall, 4),
            status=status,
            gaps=gaps,
            findings=findings,
            recommendations=(
                [f"{len(gaps)} CLO(s) lack direct assessment items."]
                if gaps else []
            ),
        )

        logger.info(f"[MetaAssessment] score={overall:.3f} ({status}) | {len(gaps)} gaps")
        updated = self._store(state, result)
        return updated

    def _store(self, state, result):
        results = dict(state.get("alignment_results", {}))
        results["metadata_assessment"] = result
        return {**state, "alignment_results": results, "current_node": Node.DIRECTOR}


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT-DELIVERY ALIGNMENT AGENT
# ══════════════════════════════════════════════════════════════════════════════

"""
LECTIO — Content-Delivery Alignment Agent

Checks that the lecture delivery (slides, transcripts) covers the module
topics in the correct sequence and with appropriate depth.

Checks:
  1. Topic coverage: every module topic appears in slides/transcripts
  2. Sequencing: prerequisites taught before dependents
     (detected via week_number metadata on chunks)
  3. Slide count vs topic weight (proxy for depth)
"""


class ContentDeliveryAlignmentAgent(BaseAgent):
    name = "content_delivery_agent"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        course_id = state["course_id"]
        modules   = state.get("modules", [])

        if not modules:
            return self._store(state, AlignmentResult(
                agent_name=self.name,
                report_type="content_delivery",
                overall_score=1.0,
                status="pass",
                findings={"note": "No modules to check."},
            ))

        gaps:     List[AlignmentGap] = []
        scores:   List[float]        = []
        findings: dict               = {
            "topic_coverage":   [],
            "sequencing_issues": [],
        }

        for mod in modules:
            for wk in mod.get("weeks", []):
                week_num = wk["week_number"]
                for topic in wk.get("topics", []):
                    score, gap = self._check_topic_delivery(
                        topic, week_num, course_id
                    )
                    scores.append(score)
                    findings["topic_coverage"].append({
                        "topic":       topic["title"],
                        "week":        week_num,
                        "score":       round(score, 3),
                        "delivered":   score >= 0.5,
                    })
                    if gap:
                        gaps.append(gap)

        # Sequencing check
        seq_issues = self._check_sequencing(modules, course_id)
        findings["sequencing_issues"] = seq_issues
        for issue in seq_issues:
            gaps.append(AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="sequencing_error",
                severity="warning",
                description=issue,
                affected_entity_type="week",
                affected_entity_id=None,
                score=0.5,
                recommendation="Review lecture order to ensure prerequisites are taught first.",
            ))

        overall = sum(scores) / len(scores) if scores else 1.0
        status  = "pass" if overall >= 0.75 else "warning" if overall >= 0.55 else "fail"

        result = AlignmentResult(
            agent_name=self.name,
            report_type="content_delivery",
            overall_score=round(overall, 4),
            status=status,
            gaps=gaps,
            findings=findings,
            recommendations=self._recommendations(gaps),
        )

        logger.info(f"[ContentDelivery] score={overall:.3f} ({status}) | {len(gaps)} gaps")
        return self._store(state, result)

    def _check_topic_delivery(self, topic: dict, week_num: int, course_id: str):
        title  = topic["title"]
        chunks = self._retrieve(
            query=f"lecture slides covering {title}",
            course_id=course_id,
            top_k=6,
            where={"artifact_type": {"$in": ["slides", "transcript"]}},
        )

        if not chunks:
            return 0.0, AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="topic_not_delivered",
                severity="critical",
                description=(
                    f"Week {week_num} topic '{title}' has no corresponding "
                    "slides or transcript content."
                ),
                affected_entity_type="topic",
                affected_entity_id=topic.get("id"),
                score=0.0,
                recommendation=(
                    f"Upload lecture slides or transcript for Week {week_num}: '{title}'"
                ),
            )

        best = max(c.score for c in chunks)
        if best < 0.45:
            return best, AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="topic_shallow_coverage",
                severity="warning",
                description=(
                    f"Week {week_num} topic '{title}' has low delivery coverage "
                    f"(score={best:.2f}). Lecture materials may be insufficient."
                ),
                affected_entity_type="topic",
                affected_entity_id=topic.get("id"),
                score=round(best, 4),
                recommendation=f"Expand lecture materials for '{title}'.",
            )

        return best, None

    def _check_sequencing(self, modules: list, course_id: str) -> List[str]:
        """
        Detect chunks from later weeks referenced in earlier weeks' content.
        Simple heuristic: retrieves chunks with week metadata and checks order.
        """
        issues = []
        # Build week → topics map
        week_topics: dict = {}
        for mod in modules:
            for wk in mod.get("weeks", []):
                wn = wk["week_number"]
                week_topics[wn] = [t["title"] for t in wk.get("topics", [])]

        # For each week, check if later-week topics appear in earlier slides
        for wn, topics in sorted(week_topics.items()):
            if wn <= 1:
                continue
            for future_wn in range(wn + 2, min(wn + 6, max(week_topics) + 1)):
                future_topics = week_topics.get(future_wn, [])
                for ft in future_topics[:2]:   # Check first 2 future topics only
                    chunks = self._retrieve(
                        query=ft,
                        course_id=course_id,
                        top_k=3,
                        where={"week_number": wn},
                    )
                    if chunks and max(c.score for c in chunks) > 0.70:
                        issues.append(
                            f"Week {wn} slides reference '{ft}' which is a "
                            f"Week {future_wn} topic — possible sequencing error."
                        )
                        if len(issues) >= 3:   # Cap to avoid noise
                            return issues
        return issues

    def _recommendations(self, gaps: List[AlignmentGap]) -> List[str]:
        recs = []
        not_delivered = [g for g in gaps if g.gap_type == "topic_not_delivered"]
        if not_delivered:
            recs.append(
                f"{len(not_delivered)} topic(s) have no lecture materials. "
                "Upload slides or transcripts for these weeks."
            )
        seq_issues = [g for g in gaps if g.gap_type == "sequencing_error"]
        if seq_issues:
            recs.append(
                f"{len(seq_issues)} potential sequencing issue(s) detected. "
                "Review lecture order for prerequisite dependencies."
            )
        return recs

    def _store(self, state, result):
        results = dict(state.get("alignment_results", {}))
        results["content_delivery"] = result
        return {**state, "alignment_results": results, "current_node": Node.DIRECTOR}
