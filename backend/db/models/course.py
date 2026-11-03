"""
LECTIO — Course & Knowledge Model ORM Models
Represents the full course structure: Course → Module → Week → Topic → Subtopic
with Learning Objectives and Assessments attached.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Course(Base):
    __tablename__ = "courses"

    id:             Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code:           Mapped[str]             = mapped_column(String(50), unique=True, nullable=False)
    title:          Mapped[str]             = mapped_column(String(500), nullable=False)
    description:    Mapped[Optional[str]]   = mapped_column(Text)
    credits:        Mapped[Optional[int]]   = mapped_column(Integer)
    level:          Mapped[Optional[str]]   = mapped_column(String(20))      # undergraduate | postgraduate
    nqf_level:      Mapped[Optional[int]]   = mapped_column(Integer)
    department_id:  Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"))
    coordinator_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    year:           Mapped[Optional[int]]   = mapped_column(Integer)
    semester:       Mapped[Optional[str]]   = mapped_column(String(20))
    created_at:     Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:     Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    modules:    Mapped[List["Module"]]         = relationship(back_populates="course", cascade="all, delete-orphan", order_by="Module.sequence_number")
    artifacts:  Mapped[List["CourseArtifact"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    assessments: Mapped[List["Assessment"]]    = relationship(back_populates="course", cascade="all, delete-orphan")


class Module(Base):
    __tablename__ = "modules"

    id:              Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id:       Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title:           Mapped[str]             = mapped_column(String(500), nullable=False)
    description:     Mapped[Optional[str]]   = mapped_column(Text)
    sequence_number: Mapped[int]             = mapped_column(Integer, nullable=False)
    credit_weight:   Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    created_at:      Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())

    course:              Mapped["Course"]                = relationship(back_populates="modules")
    weeks:               Mapped[List["Week"]]            = relationship(back_populates="module", cascade="all, delete-orphan", order_by="Week.week_number")
    learning_objectives: Mapped[List["LearningObjective"]] = relationship(back_populates="module", cascade="all, delete-orphan")


class Week(Base):
    __tablename__ = "weeks"
    __table_args__ = (UniqueConstraint("module_id", "week_number"),)

    id:          Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id:   Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    week_number: Mapped[int]           = mapped_column(Integer, nullable=False)
    title:       Mapped[Optional[str]] = mapped_column(String(500))
    theme:       Mapped[Optional[str]] = mapped_column(Text)

    module: Mapped["Module"]     = relationship(back_populates="weeks")
    topics: Mapped[List["Topic"]] = relationship(back_populates="week", cascade="all, delete-orphan", order_by="Topic.sequence_order")


class Topic(Base):
    __tablename__ = "topics"

    id:             Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    week_id:        Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False)
    title:          Mapped[str]           = mapped_column(String(500), nullable=False)
    description:    Mapped[Optional[str]] = mapped_column(Text)
    sequence_order: Mapped[Optional[int]] = mapped_column(Integer)
    created_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    week:      Mapped["Week"]            = relationship(back_populates="topics")
    subtopics: Mapped[List["Subtopic"]]  = relationship(back_populates="topic", cascade="all, delete-orphan")


class Subtopic(Base):
    __tablename__ = "subtopics"

    id:             Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id:       Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    title:          Mapped[str]           = mapped_column(String(500), nullable=False)
    description:    Mapped[Optional[str]] = mapped_column(Text)
    sequence_order: Mapped[Optional[int]] = mapped_column(Integer)

    topic: Mapped["Topic"] = relationship(back_populates="subtopics")


class LearningObjective(Base):
    __tablename__ = "learning_objectives"

    id:                 Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id:          Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    text:               Mapped[str]                 = mapped_column(Text, nullable=False)
    code:               Mapped[Optional[str]]       = mapped_column(String(50))        # CLO1, CLO2 …
    bloom_level:        Mapped[Optional[str]]       = mapped_column(String(50))        # remember|understand|apply|analyse|evaluate|create
    bloom_verb:         Mapped[Optional[str]]       = mapped_column(String(100))
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("course_artifacts.id", ondelete="SET NULL"))
    is_generated:       Mapped[bool]                = mapped_column(Boolean, default=False)
    created_at:         Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())

    module: Mapped["Module"] = relationship(back_populates="learning_objectives")


class Assessment(Base):
    __tablename__ = "assessments"

    id:                Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id:         Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title:             Mapped[str]                 = mapped_column(String(500), nullable=False)
    type:              Mapped[Optional[str]]       = mapped_column(String(50))     # assignment|quiz|exam|project|practical
    weight_percent:    Mapped[Optional[Decimal]]   = mapped_column(Numeric(5, 2))
    total_marks:       Mapped[Optional[Decimal]]   = mapped_column(Numeric(10, 2))
    week_due:          Mapped[Optional[int]]       = mapped_column(Integer)
    submission_format: Mapped[Optional[str]]       = mapped_column(String(100))
    description:       Mapped[Optional[str]]       = mapped_column(Text)
    created_at:        Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())

    course:    Mapped["Course"]                    = relationship(back_populates="assessments")
    questions: Mapped[List["AssessmentQuestion"]]  = relationship(back_populates="assessment", cascade="all, delete-orphan")
    rubrics:   Mapped[List["Rubric"]]              = relationship(back_populates="assessment", cascade="all, delete-orphan")


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id:            Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    text:          Mapped[str]                 = mapped_column(Text, nullable=False)
    bloom_level:   Mapped[Optional[str]]       = mapped_column(String(50))
    marks:         Mapped[Optional[Decimal]]   = mapped_column(Numeric(10, 2))
    topic_id:      Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"))
    question_type: Mapped[Optional[str]]       = mapped_column(String(50))   # mcq|short_answer|essay|practical

    assessment: Mapped["Assessment"] = relationship(back_populates="questions")


class Rubric(Base):
    __tablename__ = "rubrics"

    id:            Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    title:         Mapped[Optional[str]] = mapped_column(String(500))
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    assessment: Mapped["Assessment"]       = relationship(back_populates="rubrics")
    criteria:   Mapped[List["RubricCriteria"]] = relationship(back_populates="rubric", cascade="all, delete-orphan")


class RubricCriteria(Base):
    __tablename__ = "rubric_criteria"

    id:             Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rubric_id:      Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False)
    criterion_text: Mapped[str]                 = mapped_column(Text, nullable=False)
    weight_percent: Mapped[Optional[Decimal]]   = mapped_column(Numeric(5, 2))
    clo_id:         Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_objectives.id", ondelete="SET NULL"))

    rubric: Mapped["Rubric"] = relationship(back_populates="criteria")


# Import here to avoid circular imports — CourseArtifact is defined in artifact.py
