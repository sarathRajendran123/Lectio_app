"""LECTIO — Alignment Report ORM Models"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class AlignmentReport(Base):
    __tablename__ = "alignment_reports"

    id:              Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id:          Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    course_id:       Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    report_type:     Mapped[str]               = mapped_column(String(100), nullable=False)
    overall_score:   Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    status:          Mapped[Optional[str]]     = mapped_column(String(50))
    gap_count:       Mapped[int]               = mapped_column(Integer, default=0)
    warning_count:   Mapped[int]               = mapped_column(Integer, default=0)
    findings:        Mapped[dict]              = mapped_column(JSONB, nullable=False)
    recommendations: Mapped[Optional[list]]    = mapped_column(JSONB)
    generated_at:    Mapped[datetime]          = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by:     Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    gaps: Mapped[List["AlignmentGapRecord"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class AlignmentGapRecord(Base):
    __tablename__ = "alignment_gaps"

    id:                   Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id:            Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("alignment_reports.id", ondelete="CASCADE"), nullable=False)
    gap_type:             Mapped[Optional[str]]       = mapped_column(String(100))
    severity:             Mapped[str]                 = mapped_column(String(20), nullable=False)
    description:          Mapped[str]                 = mapped_column(Text, nullable=False)
    affected_entity_type: Mapped[Optional[str]]       = mapped_column(String(100))
    affected_entity_id:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    score:                Mapped[Optional[Decimal]]   = mapped_column(Numeric(5, 4))
    recommendation:       Mapped[Optional[str]]       = mapped_column(Text)
    is_resolved:          Mapped[bool]                = mapped_column(Boolean, default=False)
    resolved_by:          Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at:          Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))

    report: Mapped["AlignmentReport"] = relationship(back_populates="gaps")
