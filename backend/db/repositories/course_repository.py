"""
LECTIO — Course Repository
All DB access for courses, modules, weeks, topics, CLOs, and assessments.
Role-aware: lecturers see only their courses; coordinators+ see all.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.course import (
    Assessment, Course, LearningObjective,
    Module, Topic, Week,
)
from db.models.artifact import CourseArtifact
from schemas.course import (
    AssessmentCreate, CourseCreate, CourseUpdate,
    LearningObjectiveCreate, ModuleCreate, TopicCreate, WeekCreate,
)


class CourseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Courses ───────────────────────────────────────────────────────────────

    async def create(self, data: CourseCreate, coordinator_id: UUID) -> Course:
        course = Course(
            **data.model_dump(exclude_none=True),
            coordinator_id=coordinator_id,
        )
        self.db.add(course)
        await self.db.flush()
        return course

    async def get_by_id(self, course_id: UUID) -> Optional[Course]:
        result = await self.db.execute(
            select(Course).where(Course.id == course_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_modules(self, course_id: UUID) -> Optional[Course]:
        result = await self.db.execute(
            select(Course)
            .options(
                selectinload(Course.modules)
                .selectinload(Module.weeks)
                .selectinload(Week.topics),
                selectinload(Course.modules)
                .selectinload(Module.learning_objectives),
                selectinload(Course.assessments),
            )
            .where(Course.id == course_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        roles: List[str],
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[int, List[Course]]:
        """
        Lecturers see only courses they coordinate or teach.
        Coordinators, dept_heads, admins see all courses.
        """
        q = select(Course)

        privileged = {"coordinator", "dept_head", "admin"}
        if not any(r in privileged for r in roles):
            # Lecturer: only own courses
            q = q.where(Course.coordinator_id == user_id)

        total_result = await self.db.execute(
            select(func.count()).select_from(q.subquery())
        )
        total = total_result.scalar_one()

        result = await self.db.execute(
            q.order_by(Course.created_at.desc()).offset(skip).limit(limit)
        )
        return total, list(result.scalars().all())

    async def update(self, course_id: UUID, data: CourseUpdate) -> Optional[Course]:
        course = await self.get_by_id(course_id)
        if not course:
            return None
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(course, field, value)
        await self.db.flush()
        return course

    async def delete(self, course_id: UUID) -> bool:
        course = await self.get_by_id(course_id)
        if not course:
            return False
        await self.db.delete(course)
        await self.db.flush()
        return True

    async def count_artifacts(self, course_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(CourseArtifact.id))
            .where(CourseArtifact.course_id == course_id)
        )
        return result.scalar_one()
    
    async def count_modules(self, course_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Module.id))
            .where(Module.course_id == course_id)
        )
        return result.scalar_one()

    # ── Modules ───────────────────────────────────────────────────────────────

    async def create_module(self, course_id: UUID, data: ModuleCreate) -> Module:
        module = Module(course_id=course_id, **data.model_dump(exclude_none=True))
        self.db.add(module)
        await self.db.flush()
        return module

    async def get_modules(self, course_id: UUID) -> List[Module]:
        result = await self.db.execute(
            select(Module)
            .where(Module.course_id == course_id)
            .order_by(Module.sequence_number)
        )
        return list(result.scalars().all())

    async def get_module(self, module_id: UUID) -> Optional[Module]:
        result = await self.db.execute(
            select(Module).where(Module.id == module_id)
        )
        return result.scalar_one_or_none()

    # ── Weeks ─────────────────────────────────────────────────────────────────

    async def create_week(self, module_id: UUID, data: WeekCreate) -> Week:
        week = Week(module_id=module_id, **data.model_dump(exclude_none=True))
        self.db.add(week)
        await self.db.flush()
        return week

    async def get_weeks(self, module_id: UUID) -> List[Week]:
        result = await self.db.execute(
            select(Week).where(Week.module_id == module_id).order_by(Week.week_number)
        )
        return list(result.scalars().all())

    # ── Topics ────────────────────────────────────────────────────────────────

    async def create_topic(self, week_id: UUID, data: TopicCreate) -> Topic:
        topic = Topic(week_id=week_id, **data.model_dump(exclude_none=True))
        self.db.add(topic)
        await self.db.flush()
        return topic

    async def get_topics(self, week_id: UUID) -> List[Topic]:
        result = await self.db.execute(
            select(Topic).where(Topic.week_id == week_id).order_by(Topic.sequence_order)
        )
        return list(result.scalars().all())

    # ── Learning Objectives (CLOs) ────────────────────────────────────────────

    async def create_clo(self, module_id: UUID, data: LearningObjectiveCreate) -> LearningObjective:
        clo = LearningObjective(module_id=module_id, **data.model_dump(exclude_none=True))
        self.db.add(clo)
        await self.db.flush()
        return clo

    async def get_clos(self, module_id: UUID) -> List[LearningObjective]:
        result = await self.db.execute(
            select(LearningObjective)
            .where(LearningObjective.module_id == module_id)
            .order_by(LearningObjective.created_at)
        )
        return list(result.scalars().all())

    # ── Assessments ───────────────────────────────────────────────────────────

    async def create_assessment(self, course_id: UUID, data: AssessmentCreate) -> Assessment:
        assessment = Assessment(course_id=course_id, **data.model_dump(exclude_none=True))
        self.db.add(assessment)
        await self.db.flush()
        return assessment

    async def get_assessments(self, course_id: UUID) -> List[Assessment]:
        result = await self.db.execute(
            select(Assessment).where(Assessment.course_id == course_id)
        )
        return list(result.scalars().all())

    # ── Ownership check ───────────────────────────────────────────────────────

    async def user_can_access(
        self,
        course_id: UUID,
        user_id: UUID,
        roles: List[str],
    ) -> bool:
        """Returns True if user has access to this course."""
        privileged = {"coordinator", "dept_head", "admin"}
        if any(r in privileged for r in roles):
            return True
        course = await self.get_by_id(course_id)
        return course is not None and course.coordinator_id == user_id
