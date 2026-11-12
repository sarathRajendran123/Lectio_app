"""Governance records: course intent (versioned), lecturer constraints, draft reviews and the trace log.

All four are written insert-only by the application: a change is a new row (a new intent version, a
superseding constraint), never an UPDATE. `trace_events` is additionally hash-chained and guarded by
database triggers (see services/trace.py for the exact guarantees).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import JSONB


class CourseIntent(Base):
    """What the lecturer wants the course to achieve. Each save is a new version; the highest version is active."""
    __tablename__ = "course_intents"
    __table_args__ = (UniqueConstraint("course_id", "version", name="uq_course_intent_version"),)

    id:               Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id:        Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    version:          Mapped[int]       = mapped_column(Integer, nullable=False)
    goals:            Mapped[str]       = mapped_column(Text, nullable=False)
    cognitive_levels: Mapped[list]      = mapped_column(JSONB, default=list)      # intended Bloom levels
    audience:         Mapped[Optional[str]] = mapped_column(Text)
    scope:            Mapped[Optional[str]] = mapped_column(Text)
    constraints:      Mapped[Optional[str]] = mapped_column(Text)
    created_by:       Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at:       Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


class LecturerConstraint(Base):
    """An explicit rule derived from a lecturer decision or entered directly.

    scope 'course' applies to one course; 'general' follows the lecturer across courses.
    A constraint is retired or replaced by a later row pointing at it through `supersedes_id`;
    the earlier row stays, so the history is never lost.
    """
    __tablename__ = "lecturer_constraints"

    id:            Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:       Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id:     Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    scope:         Mapped[str]       = mapped_column(String(20), nullable=False)        # course | general
    kind:          Mapped[str]       = mapped_column(String(20), nullable=False)        # avoid | prefer | require | retired
    text:          Mapped[str]       = mapped_column(Text, nullable=False)
    source_type:   Mapped[str]       = mapped_column(String(40), nullable=False)        # draft_decision | finding_decision | manual
    source_id:     Mapped[Optional[str]] = mapped_column(String(64))                    # the draft or finding the decision was about
    decision:      Mapped[Optional[str]] = mapped_column(String(20))                    # rejected | revised | approved | ...
    rejected_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), index=True) # normalised hash of a rejected draft
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("lecturer_constraints.id", ondelete="SET NULL"))
    created_at:    Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


class DraftReview(Base):
    """The Stakeholder agent's quality check of one draft, kept beside the draft."""
    __tablename__ = "draft_reviews"

    content_id:     Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generated_content.id", ondelete="CASCADE"), primary_key=True)
    score:          Mapped[float]     = mapped_column(Float, nullable=False)
    threshold:      Mapped[float]     = mapped_column(Float, nullable=False)
    passed:         Mapped[bool]      = mapped_column(Boolean, nullable=False)
    attempts:       Mapped[int]       = mapped_column(Integer, nullable=False, default=1)
    issues:         Mapped[list]      = mapped_column(JSONB, default=list)
    checks:         Mapped[dict]      = mapped_column(JSONB, default=dict)
    rationale:      Mapped[str]       = mapped_column(Text, nullable=False, default="")
    task_id:        Mapped[Optional[str]] = mapped_column(String(64), index=True)
    intent_id:      Mapped[Optional[str]] = mapped_column(String(64))
    intent_version: Mapped[Optional[int]] = mapped_column(Integer)
    constraint_ids: Mapped[list]      = mapped_column(JSONB, default=list)
    created_at:     Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


class TraceEvent(Base):
    """One append-only event. `hash` covers the event and `prev_hash`, forming a chain per `chain_key`."""
    __tablename__ = "trace_events"
    __table_args__ = (
        UniqueConstraint("chain_key", "seq", name="uq_trace_chain_seq"),
        Index("ix_trace_subject", "subject_type", "subject_id"),
    )

    id:           Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain_key:    Mapped[str]       = mapped_column(String(80), nullable=False, index=True)   # a run id, or "course:<id>"
    seq:          Mapped[int]       = mapped_column(Integer, nullable=False)
    ts:           Mapped[str]       = mapped_column(String(40), nullable=False)               # ISO time, part of the hash
    run_id:       Mapped[Optional[str]] = mapped_column(String(64), index=True)
    course_id:    Mapped[Optional[str]] = mapped_column(String(64), index=True)
    event_type:   Mapped[str]       = mapped_column(String(40), nullable=False, index=True)
    agent:        Mapped[Optional[str]] = mapped_column(String(80))
    task_id:      Mapped[Optional[str]] = mapped_column(String(64), index=True)
    parent_id:    Mapped[Optional[str]] = mapped_column(String(64))
    subject_type: Mapped[Optional[str]] = mapped_column(String(20))                           # gap | draft | course | run
    subject_id:   Mapped[Optional[str]] = mapped_column(String(64))
    payload:      Mapped[dict]      = mapped_column(JSONB, default=dict)
    prev_hash:    Mapped[str]       = mapped_column(String(64), nullable=False)
    hash:         Mapped[str]       = mapped_column(String(64), nullable=False)
