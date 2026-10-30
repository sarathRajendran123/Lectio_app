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
                status="needs_review",
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
                status="needs_review",
                findings={"error": "No CLOs defined. Add CLOs before auditing."},
            ))

        gaps:   List[AlignmentGap] = []
        scores: List[float] = []
        findings: dict = {"clo_scores": []}
        total_tokens = 0
        translation_failures = False
        translations = {}

        for clo in all_clos:
            from config import settings
            from agents.cross_language import search_translation
            translated, translation_tokens, translation_status = search_translation(
                clo['text'], settings.runtime_mode == 'live' and bool(settings.active_api_key and settings.active_model), self._invoke)
            self.search_query = translated
            score, gap, tokens = self._audit_clo(clo, course_id)
            scores.append(score)
            total_tokens += tokens + translation_tokens
            if translated:
                translations[clo['text']] = translated
            translation_failures = translation_failures or translation_status == 'failed'
            findings["clo_scores"].append({
                "code":    clo.get("code", "?"),
                "text":    clo["text"][:120],
                "score":   round(score, 3),
                "evidence_chunk_ids": getattr(self,"last_evidence",[]),
                "search_translation": translated,
                "translation_status": translation_status,
                "status":  "needs_review" if translation_status == 'failed' else "pass" if score >= PASS_THRESHOLD else
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
        if translation_failures:
            status = 'needs_review'
            findings['translation_notice'] = 'Search translation failed for at least one objective; cross-language coverage is uncertain.'

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
        updated['search_translations'] = translations
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
            top_k=40,
            where={"artifact_type": {"$in": ["slides", "transcript", "reading", "other"]}},
        )
        translated = getattr(self, 'search_query', None)
        if translated:
            translated_chunks = self._retrieve(
                query=translated, course_id=course_id, top_k=40,
                where={"artifact_type": {"$in": ["slides", "transcript", "reading", "other"]}},
            )
            unique = {c.chunk_id: c for c in chunks}
            for chunk in translated_chunks:
                if chunk.chunk_id not in unique or chunk.score > unique[chunk.chunk_id].score:
                    unique[chunk.chunk_id] = chunk
            chunks = sorted(unique.values(), key=lambda c: c.score, reverse=True)

        # Supplement the broad query with short phrases for retrieval only.
        # Their scores are not substituted for the original objective score.
        original_score = max((c.score for c in chunks), default=0.0)
        candidates = list(chunks)
        if translated:
            from agents.evidence_selection import phrase_queries
            for query in phrase_queries(translated):
                candidates.extend(self._retrieve(query=query, course_id=course_id, top_k=40,
                    where={"artifact_type": {"$in": ["slides", "transcript", "reading", "other"]}}))
        from agents.evidence_selection import useful_evidence
        chunks = useful_evidence(candidates, limit=10)

        self.last_evidence = [c.chunk_id for c in chunks[:3]]
        if not chunks:
            gap = AlignmentGap(
                gap_id=str(uuid.uuid4()),
                gap_type="clo_not_covered",
                severity="warning",
                description=f"{clo_code}: No supporting evidence found in the supplied materials; missing documents or independent study may explain this.",
                affected_entity_type="clo",
                affected_entity_id=clo.get("id"),
                score=0.0,
                recommendation="Check the uploaded materials, language, and independent study before making changes.",
            )
            return 0.0, gap, tokens

        # Semantic score — best chunk similarity
        semantic_score = original_score

        # Keyword score — CLO keywords in retrieved texts
        combined_text = " ".join(c.text for c in chunks).lower()
        keyword_groups = [self._extract_keywords(clo_text)]
        if translated:
            keyword_groups.append(self._extract_keywords(translated))
        keyword_score = max(sum(1 for kw in words if kw.lower() in combined_text) / max(len(words), 1)
                            for words in keyword_groups)

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
                    f"Best retrieval match: {semantic_score:.2f}."
                ),
                affected_entity_type="clo",
                affected_entity_id=clo.get("id"),
                score=round(final, 4),
                recommendation=(
                    "Review the evidence, source completeness and translation before changing course content."
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
                f"{len(critical)} CLO(s) have weak retrieved evidence. "
                "Review the sources and extraction before deciding on changes."
            )
        warnings = [g for g in gaps if g.severity == "warning"]
        if warnings:
            recs.append(
                f"{len(warnings)} CLO(s) need evidence review. "
                "Check the uploaded material and independent study."
            )
        return recs

    def _store_result(self, state: LectioWorkflowState, result: AlignmentResult) -> dict:
        results = dict(state.get("alignment_results", {}))
        results["metadata_content"] = result
        return {**state, "alignment_results": results, "current_node": Node.DIRECTOR}
