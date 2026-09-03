"""
LECTIO — Courses Router
GET/POST/PATCH/DELETE /api/v1/courses
Nested: /modules, /weeks, /topics, /clos, /assessments
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import CurrentUser, get_current_user, require_role
from db.repositories.course_repository import CourseRepository
from db.session import get_db
from schemas.course import (
    AssessmentCreate, AssessmentResponse,
    CourseCreate, CourseListResponse, CourseResponse, CourseUpdate,
    LearningObjectiveCreate, LearningObjectiveResponse,
    ModuleCreate, ModuleResponse,
    TopicCreate, TopicResponse,
    WeekCreate, WeekResponse,
)

router  = APIRouter()
logger  = logging.getLogger(__name__)


# ── Helper ────────────────────────────────────────────────────────────────────

async def _assert_course_access(
    course_id: UUID,
    user: CurrentUser,
    db: AsyncSession,
) -> None:
    """Raise 404 or 403 if user cannot access this course."""
    repo = CourseRepository(db)
    course = await repo.get_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    if not await repo.user_can_access(course_id, UUID(user.id), user.roles):
        raise HTTPException(status_code=403, detail="Access denied to this course.")


# ═══════════════════════════════════════
# COURSES
# ═══════════════════════════════════════

@router.get("", response_model=CourseListResponse)
async def list_courses(
    skip:  int          = Query(0, ge=0),
    limit: int          = Query(20, ge=1, le=100),
    user:  CurrentUser  = Depends(get_current_user),
    db:    AsyncSession = Depends(get_db),
):
    """List courses visible to the current user (role-filtered)."""
    repo = CourseRepository(db)
    total, courses = await repo.list_for_user(
        user_id=UUID(user.id), roles=user.roles, skip=skip, limit=limit
    )
    responses = []
    for c in courses:
        artifact_count = await repo.count_artifacts(c.id)
        module_count = await repo.count_modules(c.id)
        responses.append(
            CourseResponse(
                **{col: getattr(c, col) for col in CourseResponse.model_fields
                   if hasattr(c, col) and col not in ("module_count", "artifact_count")},
                module_count=module_count,
                artifact_count=artifact_count,
            )
        )
    return CourseListResponse(total=total, courses=responses)


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseCreate,
    user: CurrentUser  = Depends(require_role("coordinator")),
    db:   AsyncSession = Depends(get_db),
):
    """Create a new course. Requires coordinator role or above."""
    repo = CourseRepository(db)
    course = await repo.create(body, coordinator_id=UUID(user.id))
    logger.info(f"Course {course.code} created by {user.email}")
    return CourseResponse(
        **{col: getattr(course, col) for col in CourseResponse.model_fields
           if hasattr(course, col) and col not in ("module_count", "artifact_count")},
        module_count=0,
        artifact_count=0,
    )


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo   = CourseRepository(db)
    course = await repo.get_by_id(course_id)
    artifact_count = await repo.count_artifacts(course_id)
    return CourseResponse(
        **{col: getattr(course, col) for col in CourseResponse.model_fields
           if hasattr(course, col) and col not in ("module_count", "artifact_count")},
        module_count=0,
        artifact_count=artifact_count,
    )


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: UUID,
    body: CourseUpdate,
    user: CurrentUser  = Depends(require_role("coordinator")),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo   = CourseRepository(db)
    course = await repo.update(course_id, body)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    return CourseResponse(
        **{col: getattr(course, col) for col in CourseResponse.model_fields
           if hasattr(course, col) and col not in ("module_count", "artifact_count")},
        module_count=0,
        artifact_count=0,
    )


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: UUID,
    user: CurrentUser  = Depends(require_role("admin")),
    db:   AsyncSession = Depends(get_db),
):
    """Delete a course. Admin only."""
    repo = CourseRepository(db)
    ok   = await repo.delete(course_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Course not found.")


# ═══════════════════════════════════════
# MODULES
# ═══════════════════════════════════════

@router.get("/{course_id}/modules", response_model=List[ModuleResponse])
async def list_modules(
    course_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.get_modules(course_id)


@router.post("/{course_id}/modules", response_model=ModuleResponse, status_code=201)
async def create_module(
    course_id: UUID,
    body: ModuleCreate,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo   = CourseRepository(db)
    module = await repo.create_module(course_id, body)
    return module


# ═══════════════════════════════════════
# WEEKS
# ═══════════════════════════════════════

@router.get("/{course_id}/modules/{module_id}/weeks", response_model=List[WeekResponse])
async def list_weeks(
    course_id: UUID,
    module_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.get_weeks(module_id)


@router.post("/{course_id}/modules/{module_id}/weeks", response_model=WeekResponse, status_code=201)
async def create_week(
    course_id: UUID,
    module_id: UUID,
    body: WeekCreate,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.create_week(module_id, body)


# ═══════════════════════════════════════
# TOPICS
# ═══════════════════════════════════════

@router.get("/{course_id}/modules/{module_id}/weeks/{week_id}/topics", response_model=List[TopicResponse])
async def list_topics(
    course_id: UUID,
    module_id: UUID,
    week_id:   UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.get_topics(week_id)


@router.post("/{course_id}/modules/{module_id}/weeks/{week_id}/topics", response_model=TopicResponse, status_code=201)
async def create_topic(
    course_id: UUID,
    module_id: UUID,
    week_id:   UUID,
    body: TopicCreate,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.create_topic(week_id, body)


# ═══════════════════════════════════════
# LEARNING OBJECTIVES (CLOs)
# ═══════════════════════════════════════

@router.get("/{course_id}/modules/{module_id}/clos", response_model=List[LearningObjectiveResponse])
async def list_clos(
    course_id: UUID,
    module_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.get_clos(module_id)


@router.post("/{course_id}/modules/{module_id}/clos", response_model=LearningObjectiveResponse, status_code=201)
async def create_clo(
    course_id: UUID,
    module_id: UUID,
    body: LearningObjectiveCreate,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.create_clo(module_id, body)


# ═══════════════════════════════════════
# ASSESSMENTS
# ═══════════════════════════════════════

@router.get("/{course_id}/assessments", response_model=List[AssessmentResponse])
async def list_assessments(
    course_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.get_assessments(course_id)


@router.post("/{course_id}/assessments", response_model=AssessmentResponse, status_code=201)
async def create_assessment(
    course_id: UUID,
    body: AssessmentCreate,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo = CourseRepository(db)
    return await repo.create_assessment(course_id, body)
