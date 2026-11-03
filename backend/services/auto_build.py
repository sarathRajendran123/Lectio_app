"""Automatic course-structure build.

Trigger: called once per artifact right after ingestion finishes. If the
course still has no Learning Objectives at that point, it runs the same
deterministic extraction the manual "extract-model" endpoint uses, so a
lecturer who never visits Course Structure still ends up with CLOs,
assessments and a weekly schedule derived from whatever they uploaded.

Deliberately best-effort: a failure here must never fail the artifact's own
ingestion, which already succeeded by the time this runs.
"""
import logging
from uuid import UUID
from sqlalchemy import func, select
from db.models.course import LearningObjective, Module

logger = logging.getLogger(__name__)


async def maybe_auto_extract(course_id, db) -> dict | None:
    if isinstance(course_id, str):
        course_id = UUID(course_id)

    has_objectives = await db.scalar(
        select(func.count(LearningObjective.id))
        .join(Module, LearningObjective.module_id == Module.id)
        .where(Module.course_id == course_id)
    )
    if has_objectives:
        return None  # lecturer (or an earlier upload) already has CLOs -- never overwrite

    from services.course_model import extract_course_model
    try:
        result = await extract_course_model(course_id, db)
    except Exception:
        logger.exception("auto_build: extraction failed for course %s", course_id)
        return None

    if result["objectives_added"]:
        logger.info(
            "auto_build: course %s had no CLOs -- auto-extracted %d objective(s), "
            "%d assessment(s), %d week(s) from uploaded files",
            course_id, result["objectives_added"], result["assessments_added"], result["weeks_added"],
        )
    return result
