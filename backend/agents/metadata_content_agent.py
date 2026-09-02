"""
LECTIO — Metadata-Content Alignment Agent

Checks whether the formal course metadata (CLOs from the module manual /
syllabus) is reflected in the actual course content (slides, transcripts,
reading materials).

Scoring per CLO:
  semantic_score   = max cosine similarity across top-10 retrieved chunks
  keyword_score    = fraction of CLO keywords found in retrieved texts
  bloom_score      = 1.0 if content matches CLO Bloom level, 0.5 if adjacent, 0.0 if far
  CLO_score        = 0.4*semantic + 0.3*keyword + 0.3*bloom

Overall = mean(CLO_scores)
PASS    ≥ 0.75
WARNING  0.55 – 0.74
FAIL    < 0.55
"""

import logging
import re
import uuid
from typing import List

from agents.base_agent import BaseAgent
from agents.graph.state import (
    AlignmentGap, AlignmentResult, LectioWorkflowState, Node,
)
from knowledge.bloom_classifier import classify_text

logger = logging.getLogger(__name__)

PASS_THRESHOLD    = 0.75
WARNING_THRESHOLD = 0.55


class MetadataContentAlignmentAgent(BaseAgent):
    name = "metadata_content_agent"

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        course_id = state["course_id"]
        modules   = state.get("modules", [])

        if not modules:
            logger.warning("[MetaContent] No modules in state — skipping")
            return self._store_result(state, AlignmentResult(
                agent_name=self.name,
                report_type="metadata_content",
                overall_score=0.0,
                status="fail",
                findings={"error": "No modules found in course"},
            ))

        all_clos  = []
        for mod in modules:
            for clo in mod.get("clos", []):
                all_clos.append({**clo, "module_title": mod["title"]})

        if not all_clos:
            logger.warning("[MetaContent] No CLOs defined — cannot audit")
            return self._store_result(state, AlignmentResult(
                agent_name=self.name,
                report_type="metadata_content",
                overall_score=0.0,
                status="fail",
                findings={"error": "No CLOs defined. Add CLOs before auditing."},
            ))

        gaps:   List[AlignmentGap] = []
        scores: List[float] = []
        findings: dict = {"clo_scores": []}
        total_tokens = 0

        for clo in all_clos:
            score, gap, tokens = self._audit_clo(clo, course_id)
            scores.append(score)
            total_tokens += tokens
            findings["clo_scores"].append({
                "code":    clo.get("code", "?"),
                "text":    clo["text"][:120],
                "score":   round(score, 3),
                "status":  "pass" if score >= PASS_THRESHOLD else
                           "warning" if score >= WARNING_THRESHOLD else "fail",
            })
            if gap:
                gaps.append(gap)

        overall = sum(scores) / len(scores) if scores else 0.0
        status  = (
            "pass"    if overall >= PASS_THRESHOLD    else
            "warning" if overall >= WARNING_THRESHOLD else
            "fail"
        )

        result = AlignmentResult(
            agent_name=self.name,
            report_type="metadata_content",
            overall_score=round(overall, 4),
            status=status,
            gaps=gaps,
            findings=findings,
            recommendations=self._recommendations(gaps),
        )

        logger.info(
            f"[MetaContent] Score={overall:.3f} ({status}) | "
            f"{len(gaps)} gaps | {len(all_clos)} CLOs checked"
        )
        updated = self._store_result(state, result)
        updated["total_tokens"] = state.get("total_tokens", 0) + total_tokens
        return updated

    # ── Per-CLO audit ─────────────────────────────────────────────────────────

    def _audit_clo(self, clo: dict, course_id: str) -> tuple[float, AlignmentGap | None, int]:
        clo_text  = clo["text"]
        clo_code  = clo.get("code", "CLO?")
        tokens    = 0

        # Retrieve relevant content chunks
        chunks = self._retrieve(
            query=clo_text,
            course_id=course_id,
            top_k=10,
            where={"artifact_type": {"$in": ["slides", "transcript", "module_manual"]}},
        )

        if not chunks:
            gap = AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="clo_not_covered",
                severity="critical",
                description=f"{clo_code}: No course content found covering this objective.",
                affected_entity_type="clo",
                affected_entity_id=clo.get("id"),
                score=0.0,
                recommendation=f"Add lecture content addressing: {clo_text[:100]}",
            )
            return 0.0, gap, tokens

        # Semantic score — best chunk similarity
        semantic_score = max(c.score for c in chunks)

        # Keyword score — CLO keywords in retrieved texts
        keywords      = self._extract_keywords(clo_text)
        combined_text = " ".join(c.text for c in chunks).lower()
        kw_hits       = sum(1 for kw in keywords if kw.lower() in combined_text)
        keyword_score = kw_hits / max(len(keywords), 1)

        # Bloom level score
        clo_bloom     = clo.get("bloom_level") or classify_text(clo_text)[0] or "understand"
        bloom_score   = self._bloom_score(clo_bloom, combined_text)

        final = 0.4 * semantic_score + 0.3 * keyword_score + 0.3 * bloom_score

        gap = None
        if final < WARNING_THRESHOLD:
            sev = "critical" if final < 0.4 else "warning"
            gap = AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="clo_not_covered",
                severity=sev,
                description=(
                    f"{clo_code} coverage score {final:.2f} is below threshold. "
                    f"Keyword coverage: {keyword_score:.0%}. "
                    f"Best semantic match: {semantic_score:.2f}."
                ),
                affected_entity_type="clo",
                affected_entity_id=clo.get("id"),
                score=round(final, 4),
                recommendation=(
                    f"Expand lecture content to explicitly address: {clo_text[:100]}"
                ),
                evidence_chunk_ids=[c.chunk_id for c in chunks[:3]],
            )

        return final, gap, tokens

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from a CLO (strip stop words)."""
        stop = {
            "the", "a", "an", "and", "or", "to", "be", "able", "will",
            "should", "can", "of", "in", "on", "at", "by", "for",
            "with", "this", "that", "is", "are", "students",
        }
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        return [w for w in words if w not in stop]

    def _bloom_score(self, clo_level: str, content_text: str) -> float:
        """Check if course content addresses the CLO's cognitive level."""
        level_map = {
            "remember": 1, "understand": 2, "apply": 3,
            "analyse": 4, "evaluate": 5, "create": 6,
        }
        content_level, _ = classify_text(content_text[:2000])
        if not content_level:
            return 0.5   # Cannot determine — neutral score

        diff = abs(
            level_map.get(clo_level, 3) - level_map.get(content_level, 3)
        )
        return {0: 1.0, 1: 0.7, 2: 0.4}.get(diff, 0.1)

    def _recommendations(self, gaps: List[AlignmentGap]) -> List[str]:
        recs = []
        critical = [g for g in gaps if g.severity == "critical"]
        if critical:
            recs.append(
                f"{len(critical)} CLO(s) have no course content coverage. "
                "Prioritise adding slides or lecture notes for these objectives."
            )
        warnings = [g for g in gaps if g.severity == "warning"]
        if warnings:
            recs.append(
                f"{len(warnings)} CLO(s) have partial coverage. "
                "Review lecture materials to ensure sufficient depth."
            )
        return recs

    def _store_result(self, state: LectioWorkflowState, result: AlignmentResult) -> dict:
        results = dict(state.get("alignment_results", {}))
        results["metadata_content"] = result
        return {**state, "alignment_results": results, "current_node": Node.DIRECTOR}
