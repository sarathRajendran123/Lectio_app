"""Course intent: what the lecturer wants the course to achieve, versioned and passed to every agent task."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from db.models.governance import CourseIntent

BLOOM_LEVELS = ["remember", "understand", "apply", "analyse", "evaluate", "create"]


def as_dict(row: Optional[CourseIntent]) -> Optional[dict]:
    if row is None:
        return None
    return {"id": str(row.id), "course_id": str(row.course_id), "version": row.version, "goals": row.goals,
            "cognitive_levels": list(row.cognitive_levels or []), "audience": row.audience or "", "scope": row.scope or "",
            "constraints": row.constraints or "", "created_at": row.created_at.isoformat() if row.created_at else None}


def ref(intent: Optional[dict]) -> Optional[dict]:
    """The identifier recorded on every task and trace event."""
    return {"id": intent["id"], "version": intent["version"]} if intent else None


async def active(db, course_id) -> Optional[dict]:
    row = await db.scalar(select(CourseIntent).where(CourseIntent.course_id == UUID(str(course_id)))
                          .order_by(CourseIntent.version.desc()).limit(1))
    return as_dict(row)


async def by_id(db, intent_id) -> Optional[dict]:
    return as_dict(await db.get(CourseIntent, UUID(str(intent_id)))) if intent_id else None


async def history(db, course_id) -> list:
    rows = (await db.scalars(select(CourseIntent).where(CourseIntent.course_id == UUID(str(course_id)))
                             .order_by(CourseIntent.version.desc()))).all()
    return [as_dict(r) for r in rows]


async def save(db, course_id, user_id, *, goals: str, cognitive_levels=(), audience="", scope="", constraints="") -> dict:
    """A save never edits: it adds the next version, so earlier tasks keep pointing at what was active then."""
    levels = [level for level in cognitive_levels if level in BLOOM_LEVELS]
    latest = await db.scalar(select(func.max(CourseIntent.version)).where(CourseIntent.course_id == UUID(str(course_id)))) or 0
    row = CourseIntent(course_id=UUID(str(course_id)), version=latest + 1, goals=goals.strip(), cognitive_levels=levels,
                       audience=audience.strip() or None, scope=scope.strip() or None, constraints=constraints.strip() or None,
                       created_by=UUID(str(user_id)) if user_id else None)
    db.add(row)
    await db.flush()
    return as_dict(row)


def block(intent: Optional[dict]) -> str:
    """The text every model context carries. Says so plainly when the lecturer has stated no intent."""
    if not intent:
        return "COURSE INTENT: the lecturer has not stated one. Do not assume goals beyond the supplied sources."
    lines = [f"COURSE INTENT (version {intent['version']}, stated by the lecturer; follow it):", f"- Goals: {intent['goals']}"]
    if intent.get("cognitive_levels"):
        lines.append(f"- Intended cognitive levels (Bloom): {', '.join(intent['cognitive_levels'])}")
    for label, key in (("Audience", "audience"), ("Scope", "scope"), ("Constraints", "constraints")):
        if intent.get(key):
            lines.append(f"- {label}: {intent[key]}")
    return "\n".join(lines)
