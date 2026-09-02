"""LECTIO — AgentRun, GeneratedContent, Approval ORM Models"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id:               Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id:        Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    initiated_by:     Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    workflow_type:    Mapped[str]                 = mapped_column(String(100), nullable=False)
    status:           Mapped[str]                 = mapped_column(String(50), nullable=False, default="running")
    langgraph_run_id: Mapped[Optional[str]]       = mapped_column(String(255))
    langsmith_run_id: Mapped[Optional[str]]       = mapped_column(String(255))
    workflow_state:   Mapped[Optional[dict]]      = mapped_column(JSONB)
    error_message:    Mapped[Optional[str]]       = mapped_column(Text)
    started_at:       Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at:     Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))
    total_tokens_used: Mapped[Optional[int]]      = mapped_column(Integer)
    total_cost_usd:   Mapped[Optional[Decimal]]   = mapped_column(Numeric(10, 6))

    steps:    Mapped[List["AgentStep"]]           = relationship(back_populates="run", cascade="all, delete-orphan")
    reports:  Mapped[List["AlignmentReport"]]     = relationship(  # type: ignore[name-defined]
        "AlignmentReport", foreign_keys="AlignmentReport.run_id",
        primaryjoin="AgentRun.id == AlignmentReport.run_id",
        lazy="select",
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id:               Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id:           Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    agent_name:       Mapped[str]           = mapped_column(String(100), nullable=False)
    step_type:        Mapped[Optional[str]] = mapped_column(String(100))
    input_summary:    Mapped[Optional[str]] = mapped_column(Text)
    output_summary:   Mapped[Optional[str]] = mapped_column(Text)
    tokens_used:      Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms:      Mapped[Optional[int]] = mapped_column(Integer)
    status:           Mapped[Optional[str]] = mapped_column(String(50))
    error_message:    Mapped[Optional[str]] = mapped_column(Text)
    created_at:       Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["AgentRun"] = relationship(back_populates="steps")


class GeneratedContentRecord(Base):
    __tablename__ = "generated_content"

    id:                  Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id:              Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    course_id:           Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    content_type:        Mapped[Optional[str]]       = mapped_column(String(100))
    title:               Mapped[Optional[str]]       = mapped_column(String(500))
    content:             Mapped[str]                 = mapped_column(Text, nullable=False)
    bloom_level:         Mapped[Optional[str]]       = mapped_column(String(50))
    source_gap_id:       Mapped[Optional[str]]       = mapped_column(String(255))
    citations:           Mapped[Optional[list]]      = mapped_column(JSONB)
    confidence_score:    Mapped[Optional[Decimal]]   = mapped_column(Numeric(5, 4))
    model_used:          Mapped[Optional[str]]       = mapped_column(String(100))
    approval_status:     Mapped[str]                 = mapped_column(String(50), default="pending")
    created_at:          Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())

    approvals: Mapped[List["ApprovalRecord"]] = relationship(back_populates="content", cascade="all, delete-orphan")


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id:            Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_id:    Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("generated_content.id", ondelete="CASCADE"), nullable=False)
    reviewer_id:   Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    decision:      Mapped[str]           = mapped_column(String(20), nullable=False)
    comment:       Mapped[Optional[str]] = mapped_column(Text)
    revision_text: Mapped[Optional[str]] = mapped_column(Text)
    decided_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_final:      Mapped[bool]          = mapped_column(Boolean, default=True)

    content: Mapped["GeneratedContentRecord"] = relationship(back_populates="approvals")
