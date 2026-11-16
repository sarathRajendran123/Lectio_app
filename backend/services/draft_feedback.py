"""Provisional alignment feedback on text the lecturer is still writing. Rules and retrieval only: no model call,
nothing is stored except one trace event, and no audit score changes."""
import asyncio
from uuid import UUID

from sqlalchemy import select

from config import settings
from db.models.artifact import CourseArtifact
from db.models.course import LearningObjective, Module
from knowledge.bloom_classifier import LEVEL_ORDER, classify_detail
from rag.lexical import lexical_score

TEACHING = ["slides", "transcript", "reading", "other"]
ASSESSMENT = ["assignment", "exam", "assessment"]
PRACTICE_TYPES = ("exercise", "quiz", "assessment_suggestion")
NOTICE = ("Provisional check of unsaved text, made with rules and document search only. No model was used. "
          "It is not an audit result and changes no score; run an audit after saving for verified results.")


def _finding(kind, severity, message, uncertainty):
    return {"type": kind, "severity": severity, "message": message, "uncertainty": uncertainty}


def _rank(level):
    return LEVEL_ORDER.index(level) if level in LEVEL_ORDER else None


def _excerpt(chunk):
    return {"chunk_id": chunk.chunk_id, "artifact_id": chunk.artifact_id, "artifact_type": chunk.artifact_type, "page": chunk.page_number,
            "slide": chunk.slide_number, "section": chunk.section_title, "match": round(float(chunk.score), 4),
            "excerpt": chunk.text[:400] + ("…" if len(chunk.text) > 400 else "")}


async def assess(db, course_id, text: str, content_type: str, objective_ids=(), intended_level=None) -> dict:
    from rag.rag_service import RAGService
    from services import intent as course_intent
    course_id = UUID(str(course_id))
    detail = classify_detail(text)
    level = detail["level"]
    findings, not_checked = [], []
    heuristic = "Level from the main action verb; a heuristic, the lecturer's reading decides."
    if detail["ambiguous"]:
        heuristic = f"The verb '{detail['verb']}' is placed at different levels by different authors. " + heuristic

    # ── cognitive level ──────────────────────────────────────────────────────
    intent = await course_intent.active(db, course_id)
    if level is None:
        findings.append(_finding("feedback_level_unclear", "info", "No action verb was recognised, so the cognitive level could not be checked.",
                                 "The verb list is limited; an unusual verb or a demand hidden in a noun is not recognised."))
    elif intended_level and level != intended_level:
        below = _rank(level) < _rank(intended_level)
        findings.append(_finding("feedback_level_below_intended" if below else "feedback_level_above_intended", "warning" if below else "info",
                                 f"The text reads as '{level}' (verb: {detail['verb'] or 'question form'}); the intended level is '{intended_level}'.", heuristic))
    if level and content_type == "clo" and intent and intent.get("cognitive_levels") and level not in intent["cognitive_levels"]:
        findings.append(_finding("feedback_level_outside_intent", "info",
                                 f"The course intent (version {intent['version']}) names the levels {', '.join(intent['cognitive_levels'])}; this objective reads as '{level}'.",
                                 heuristic))

    # ── objectives ───────────────────────────────────────────────────────────
    objectives = list((await db.scalars(select(LearningObjective).join(Module).where(Module.course_id == course_id))).all())
    chosen = {UUID(str(i)) for i in objective_ids}
    scored = sorted(((lexical_score(o.text, text), o) for o in objectives), key=lambda pair: pair[0], reverse=True)
    linked = [(s, o) for s, o in scored if o.id in chosen] if chosen else [(s, o) for s, o in scored if s >= settings.feedback_objective_match][:3]
    word_match = "Matched by shared words; an objective in other wording or in the other language is missed."
    if not objectives:
        not_checked.append("The course has no learning objectives yet, so the text could not be compared with them.")
    elif content_type == "clo":
        if scored[0][0] >= settings.feedback_duplicate_match:
            findings.append(_finding("feedback_similar_objective_exists", "info",
                                     f"An existing objective is very similar: {scored[0][1].code or 'objective'}: {scored[0][1].text[:200]}", word_match))
    else:
        if not linked:
            findings.append(_finding("feedback_no_objective_matched", "info",
                                     "No learning objective of this course shares enough wording with the text. Select the objectives it is meant for to check the level.",
                                     word_match))
        for _, objective in linked:
            if content_type in PRACTICE_TYPES and level and objective.bloom_level and _rank(level) < _rank(objective.bloom_level):
                findings.append(_finding("feedback_level_below_objective", "warning",
                                         f"The task reads as '{level}', below the '{objective.bloom_level}' level of {objective.code or 'the objective'}: {objective.text[:160]}",
                                         heuristic + " The objective's level may itself be a classifier result."))

    # ── evidence in the course documents ─────────────────────────────────────
    present = set((await db.scalars(select(CourseArtifact.artifact_type).where(CourseArtifact.course_id == course_id,
                                                                               CourseArtifact.processing_status == "done"))).all())
    rag = RAGService.get_instance()
    search_note = "Search score, not a probability. A missing document is not proof that the topic is untaught."
    evidence = []
    if not present & set(TEACHING):
        not_checked.append("No processed teaching material (slides, transcript, reading) is uploaded, so support in the teaching material was not checked.")
    else:
        chunks = await asyncio.to_thread(rag.retrieve, text, str(course_id), 5, {"artifact_type": {"$in": TEACHING}})
        evidence = [_excerpt(c) for c in chunks[:3]]
        best = max((float(c.score) for c in chunks), default=0.0)
        if not chunks:
            findings.append(_finding("feedback_no_teaching_evidence", "warning",
                                     "No passage in the uploaded teaching material matches this text. Insufficient evidence that it is covered.", search_note))
        elif best < settings.feedback_support_threshold:
            findings.append(_finding("feedback_weak_teaching_evidence", "info",
                                     "The closest passages in the teaching material match this text only weakly. Check the excerpts.", search_note))
    assessed = []
    if content_type == "clo":
        if not present & set(ASSESSMENT):
            not_checked.append("No processed assessment document is uploaded, so whether this objective is assessed was not checked.")
        else:
            chunks = await asyncio.to_thread(rag.retrieve, text, str(course_id), 3, {"artifact_type": {"$in": ASSESSMENT}})
            assessed = [_excerpt(c) for c in chunks[:2]]
            if not chunks or max(float(c.score) for c in chunks) < settings.feedback_support_threshold:
                findings.append(_finding("feedback_objective_not_assessed", "info",
                                         "No assessment task in the uploaded documents clearly matches this objective.", search_note))

    from services import trace
    await trace.aemit("draft_feedback", {"content_type": content_type, "text_fingerprint": trace.fingerprint(text)[:16], "level": level,
                                         "findings": [f["type"] for f in findings], "evidence_chunk_ids": [e["chunk_id"] for e in evidence]},
                      db=db, subject=("course", course_id), course_id=str(course_id), agent="lecturer")
    return {"provisional": True, "notice": NOTICE, "content_type": content_type,
            "bloom": {"level": level, "verb": detail["verb"], "method": detail["method"], "ambiguous": detail["ambiguous"], "intended": intended_level},
            "objectives": [{"id": str(o.id), "code": o.code, "text": o.text, "bloom_level": o.bloom_level, "match": s, "selected": o.id in chosen} for s, o in linked],
            "findings": findings, "evidence": evidence, "assessment_evidence": assessed, "not_checked": not_checked}
