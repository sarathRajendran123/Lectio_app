"""
LECTIO — Course Pydantic Schemas
Request/response models for course, module, week, topic, assessment endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════
# COURSE
# ═══════════════════════════════════════

class CourseCreate(BaseModel):
    code:          str         = Field(..., min_length=2, max_length=50, examples=["CS301"])
    title:         str         = Field(..., min_length=3, max_length=500, examples=["Data Structures"])
    description:   Optional[str] = None
    credits:       Optional[int] = Field(None, ge=1, le=120)
    level:         Optional[str] = Field(None, pattern="^(undergraduate|postgraduate)$")
    nqf_level:     Optional[int] = Field(None, ge=1, le=10)
    department_id: Optional[UUID] = None
    year:          Optional[int] = Field(None, ge=2020, le=2035)
    semester:      Optional[str] = Field(None, pattern="^(S1|S2|Full Year|Q1|Q2|Q3|Q4)$")

    @field_validator("code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.strip().upper()


class CourseUpdate(BaseModel):
    title:         Optional[str] = Field(None, min_length=3, max_length=500)
    description:   Optional[str] = None
    credits:       Optional[int] = Field(None, ge=1, le=120)
    level:         Optional[str] = Field(None, pattern="^(undergraduate|postgraduate)$")
    nqf_level:     Optional[int] = None
    year:          Optional[int] = None
    semester:      Optional[str] = None
    coordinator_id: Optional[UUID] = None


class CourseResponse(BaseModel):
    id:             UUID
    code:           str
    title:          str
    description:    Optional[str]
    credits:        Optional[int]
    level:          Optional[str]
    nqf_level:      Optional[int]
    department_id:  Optional[UUID]
    coordinator_id: Optional[UUID]
    year:           Optional[int]
    semester:       Optional[str]
    created_at:     datetime
    updated_at:     datetime
    # Aggregates populated by repository
    module_count:   int = 0
    artifact_count: int = 0

    class Config:
        from_attributes = True


class CourseListResponse(BaseModel):
    total:   int
    courses: List[CourseResponse]


# ═══════════════════════════════════════
# MODULE
# ═══════════════════════════════════════

class ModuleCreate(BaseModel):
    title:           str           = Field(..., min_length=2, max_length=500)
    description:     Optional[str] = None
    sequence_number: int           = Field(..., ge=1)
    credit_weight:   Optional[Decimal] = Field(None, ge=0, le=100)


class ModuleResponse(BaseModel):
    id:              UUID
    course_id:       UUID
    title:           str
    description:     Optional[str]
    sequence_number: int
    credit_weight:   Optional[Decimal]
    created_at:      datetime

    class Config:
        from_attributes = True


# ═══════════════════════════════════════
# WEEK
# ═══════════════════════════════════════

class WeekCreate(BaseModel):
    week_number: int           = Field(..., ge=1, le=52)
    title:       Optional[str] = None
    theme:       Optional[str] = None


class WeekResponse(BaseModel):
    id:          UUID
    module_id:   UUID
    week_number: int
    title:       Optional[str]
    theme:       Optional[str]

    class Config:
        from_attributes = True


# ═══════════════════════════════════════
# TOPIC
# ═══════════════════════════════════════

class TopicCreate(BaseModel):
    title:          str           = Field(..., min_length=2, max_length=500)
    description:    Optional[str] = None
    sequence_order: Optional[int] = None


class TopicResponse(BaseModel):
    id:             UUID
    week_id:        UUID
    title:          str
    description:    Optional[str]
    sequence_order: Optional[int]

    class Config:
        from_attributes = True


# ═══════════════════════════════════════
# LEARNING OBJECTIVE (CLO)
# ═══════════════════════════════════════

BLOOM_LEVELS = {"remember", "understand", "apply", "analyse", "evaluate", "create"}


class LearningObjectiveCreate(BaseModel):
    text:        str           = Field(..., min_length=10)
    code:        Optional[str] = Field(None, max_length=50, examples=["CLO1"])
    bloom_level: Optional[str] = None
    bloom_verb:  Optional[str] = None

    @field_validator("bloom_level")
    @classmethod
    def validate_bloom(cls, v: Optional[str]) -> Optional[str]:
        if v and v.lower() not in BLOOM_LEVELS:
            raise ValueError(f"bloom_level must be one of {BLOOM_LEVELS}")
        return v.lower() if v else v


class LearningObjectiveResponse(BaseModel):
    id:           UUID
    module_id:    UUID
    text:         str
    code:         Optional[str]
    bloom_level:  Optional[str]
    bloom_verb:   Optional[str]
    is_generated: bool
    created_at:   datetime

    class Config:
        from_attributes = True


# ═══════════════════════════════════════
# ASSESSMENT
# ═══════════════════════════════════════

ASSESSMENT_TYPES = {"assignment", "quiz", "exam", "project", "practical"}


class AssessmentCreate(BaseModel):
    title:             str             = Field(..., min_length=2, max_length=500)
    type:              Optional[str]   = None
    weight_percent:    Optional[Decimal] = Field(None, ge=0, le=100)
    total_marks:       Optional[Decimal] = Field(None, ge=0)
    week_due:          Optional[int]   = Field(None, ge=1, le=52)
    submission_format: Optional[str]   = None
    description:       Optional[str]   = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v and v.lower() not in ASSESSMENT_TYPES:
            raise ValueError(f"type must be one of {ASSESSMENT_TYPES}")
        return v.lower() if v else v


class AssessmentResponse(BaseModel):
    id:                UUID
    course_id:         UUID
    title:             str
    type:              Optional[str]
    weight_percent:    Optional[Decimal]
    total_marks:       Optional[Decimal]
    week_due:          Optional[int]
    submission_format: Optional[str]
    description:       Optional[str]
    created_at:        datetime

    class Config:
        from_attributes = True
