"""Lecturer decisions as explicit, structured constraints.

A rejection or an edit with a comment becomes a constraint for that course; the lecturer can also add
general preferences that follow them across courses. Nothing is edited or deleted: a constraint is
replaced or retired by a later row that points at it, so the history stays readable.
"""
import hashlib
import re
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select

from db.models.governance import LecturerConstraint

KINDS = ("avoid", "prefer", "require")
NO_REASON = "The lecturer rejected this draft without a stated reason."
NO_FINDING_REASON = "The lecturer dismissed this finding without a stated reason."


def content_fingerprint(text: str) -> str:
    """Same wording, ignoring case, spacing and punctuation, gives the same fingerprint."""
    return hashlib.sha256(" ".join(re.findall(r"\w+", (text or "").lower())).encode("utf-8")).hexdigest()


def finding_fingerprint(gap_type: str, entity_id, description: str = "") -> str:
    """Identity of a finding across audits: its kind plus the course item it is about. Findings without a
    stored item fall back to their wording with numbers removed (scores change from run to run)."""
    key = str(entity_id) if entity_id else " ".join(re.findall(r"[^\W\d]+", (description or "").lower()))
    return hashlib.sha256(f"finding|{gap_type}|{key}".encode("utf-8")).hexdigest()


def as_dict(row: LecturerConstraint) -> dict:
    return {"id": str(row.id), "scope": row.scope, "kind": row.kind, "text": row.text, "source_type": row.source_type,
            "source_id": row.source_id, "decision": row.decision, "course_id": str(row.course_id) if row.course_id else None,
            "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _rows(db, user_id, course_id=None) -> list:
    """This lecturer's general constraints plus the ones for this course, oldest first."""
    conditions = [LecturerConstraint.scope == "general"]
    if course_id:
        conditions.append(LecturerConstraint.course_id == UUID(str(course_id)))
    rows = (await db.scalars(select(LecturerConstraint).where(LecturerConstraint.user_id == UUID(str(user_id)), or_(*conditions))
                             .order_by(LecturerConstraint.created_at, LecturerConstraint.id))).all()
    return list(rows)


async def active(db, user_id, course_id=None) -> list:
    """Constraints in force: not superseded by a later row and not a retirement marker.
    General ones come first and course-specific ones last, so the course-specific wording wins."""
    if not user_id:
        return []
    rows = await _rows(db, user_id, course_id)
    superseded = {r.supersedes_id for r in rows if r.supersedes_id}
    live = [r for r in rows if r.id not in superseded and r.kind != "retired"]
    return [as_dict(r) for r in sorted(live, key=lambda r: r.scope == "course")]


async def history(db, user_id, course_id=None) -> list:
    return [as_dict(r) for r in await _rows(db, user_id, course_id)]


async def rejected_fingerprints(db, course_id) -> set:
    rows = await db.scalars(select(LecturerConstraint.rejected_fingerprint).where(
        LecturerConstraint.course_id == UUID(str(course_id)), LecturerConstraint.rejected_fingerprint.is_not(None),
        LecturerConstraint.source_type == "draft_decision"))
    return set(rows.all())


async def dismissed_findings(db, course_id) -> dict:
    """fingerprint -> {constraint_id, reason} for findings the lecturer dismissed and has not reinstated
    (a dismissal that was superseded or retired no longer applies)."""
    rows = (await db.scalars(select(LecturerConstraint).where(LecturerConstraint.course_id == UUID(str(course_id)))
                             .order_by(LecturerConstraint.created_at, LecturerConstraint.id))).all()
    superseded = {r.supersedes_id for r in rows if r.supersedes_id}
    return {r.rejected_fingerprint: {"constraint_id": str(r.id), "reason": r.text}
            for r in rows if r.source_type == "finding_decision" and r.rejected_fingerprint and r.id not in superseded}


def apply_dismissals(result, dismissed: dict) -> list:
    """Mark findings the lecturer already dismissed: kept visible, lowered to information, never drafted for.
    Returns the marked findings. The dimension score is left as the agent computed it."""
    marked = []
    for gap in getattr(result, "gaps", []) or []:
        hit = (dismissed or {}).get(finding_fingerprint(gap.gap_type, gap.affected_entity_id, gap.description))
        if hit:
            gap.dismissed_by = hit["constraint_id"]
            gap.severity = "info"
            gap.recommendation = f"You dismissed this finding before ({hit['reason']}). It is listed for completeness; reinstate it by retiring that rule."
            marked.append(gap)
    if marked:
        result.findings["previously_dismissed"] = [g.gap_id for g in marked]
    return marked


async def add(db, user_id, *, text: str, kind: str = "prefer", scope: str = "course", course_id=None, source_type: str = "manual",
              source_id: Optional[str] = None, decision: Optional[str] = None, rejected_text: Optional[str] = None,
              supersedes_id=None, fingerprint: Optional[str] = None) -> dict:
    if scope == "course" and not course_id:
        raise ValueError("A course constraint needs a course.")
    row = LecturerConstraint(user_id=UUID(str(user_id)), course_id=UUID(str(course_id)) if course_id and scope == "course" else None,
                             scope=scope, kind=kind, text=text.strip(), source_type=source_type, source_id=source_id, decision=decision,
                             rejected_fingerprint=fingerprint or (content_fingerprint(rejected_text) if rejected_text else None),
                             supersedes_id=UUID(str(supersedes_id)) if supersedes_id else None)
    db.add(row)
    await db.flush()
    return as_dict(row)


async def from_draft_decision(db, user_id, course_id, content_id, decision: str, comment: Optional[str], draft_text: str) -> Optional[dict]:
    """Rejected: remember the exact draft so it is not offered again, and keep the reason as an 'avoid' rule.
    Edited: keep the reason as a 'prefer' rule. Approvals need no constraint."""
    comment = (comment or "").strip()
    if decision == "rejected":
        return await add(db, user_id, text=comment or NO_REASON, kind="avoid", scope="course", course_id=course_id,
                         source_type="draft_decision", source_id=str(content_id), decision=decision, rejected_text=draft_text)
    if decision == "revised" and comment:
        return await add(db, user_id, text=comment, kind="prefer", scope="course", course_id=course_id,
                         source_type="draft_decision", source_id=str(content_id), decision=decision)
    return None


async def from_finding_decision(db, user_id, course_id, gap, decision: str, rationale: Optional[str],
                                revised_recommendation: Optional[str] = None) -> Optional[dict]:
    """Rejected: the finding is remembered by its identity, so later audits mark it instead of raising it as new,
    and the reason becomes an 'avoid' rule. Revised: the lecturer's own recommendation becomes a 'prefer' rule.
    Approving a finding or asking for more review creates no constraint."""
    rationale = (rationale or "").strip()
    what = gap.gap_type.replace("_", " ")
    if decision == "rejected":
        return await add(db, user_id, text=f"Dismissed finding ({what}): {rationale}" if rationale else NO_FINDING_REASON,
                         kind="avoid", scope="course", course_id=course_id, source_type="finding_decision", source_id=str(gap.id),
                         decision=decision, fingerprint=finding_fingerprint(gap.gap_type, gap.affected_entity_id, gap.description))
    if decision == "revised" and (revised_recommendation or "").strip():
        return await add(db, user_id, text=f"For findings about {what}, the lecturer's preferred action: {revised_recommendation.strip()[:600]}",
                         kind="prefer", scope="course", course_id=course_id, source_type="finding_decision", source_id=str(gap.id),
                         decision=decision)
    return None


def block(items: list) -> str:
    """Constraints as prompt text. Empty when there are none."""
    stated = [c for c in items if c.get("kind") in KINDS and c["text"] not in (NO_REASON, NO_FINDING_REASON)]
    if not stated:
        return ""
    label = {"avoid": "Avoid", "prefer": "Prefer", "require": "Required"}
    return "LECTURER CONSTRAINTS (from earlier decisions; later lines override earlier ones):\n" + "\n".join(
        f"- {label[c['kind']]} ({'this course' if c['scope'] == 'course' else 'general'}): {c['text']}" for c in stated[-12:])


def guidance(intent: Optional[dict], items: list) -> str:
    from services.intent import block as intent_block
    return "\n\n".join(part for part in (intent_block(intent), block(items)) if part)
