"""
LECTIO — Admin Router
GET/POST/PATCH/DELETE /api/v1/admin/users
GET                   /api/v1/admin/audit-logs
GET                   /api/v1/admin/system-stats
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import CurrentUser, require_role
from db.models.user import Role, User, UserRole
from db.repositories.user_repository import UserRepository
from db.session import get_db
from api.v1.middleware.audit_logger import AuditLog, AuditLogRepository
from schemas.admin import (
    AuditLogListResponse, AuditLogResponse,
    RoleAssignRequest,
    SystemStatsResponse,
    UserAdminResponse, UserCreateRequest,
    UserListResponse, UserUpdateRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# All admin routes require admin role
AdminUser = Depends(require_role("admin"))


# ═══════════════════════════════════════
# USER MANAGEMENT
# ═══════════════════════════════════════

@router.get("/users", response_model=UserListResponse)
async def list_users(
    skip:   int = Query(0, ge=0),
    limit:  int = Query(50, ge=1, le=200),
    user:   CurrentUser  = AdminUser,
    db:     AsyncSession = Depends(get_db),
):
    """List all users with their roles."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
        .order_by(User.created_at.desc())
        .offset(skip).limit(limit)
    )
    users = list(result.scalars().all())

    count_result = await db.execute(select(func.count(User.id)))
    total = count_result.scalar_one()

    return UserListResponse(
        total=total,
        users=[_user_to_response(u) for u in users],
    )


@router.post("/users", response_model=UserAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    user: CurrentUser  = AdminUser,
    db:   AsyncSession = Depends(get_db),
):
    """Create a new user with a specified role."""
    repo = UserRepository(db)
    existing = await repo.get_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered.")

    new_user = await repo.create(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        department_id=body.department_id,
        role_name=body.role,
    )
    # Re-fetch with roles loaded
    new_user = await repo.get_by_id(new_user.id)
    logger.info(f"Admin {user.email} created user {new_user.email} with role={body.role}")
    return _user_to_response(new_user)


@router.get("/users/{user_id}", response_model=UserAdminResponse)
async def get_user(
    user_id: UUID,
    user:    CurrentUser  = AdminUser,
    db:      AsyncSession = Depends(get_db),
):
    repo     = UserRepository(db)
    target   = await repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_to_response(target)


@router.patch("/users/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: UUID,
    body:    UserUpdateRequest,
    user:    CurrentUser  = AdminUser,
    db:      AsyncSession = Depends(get_db),
):
    """Update user name, active status, or department."""
    repo   = UserRepository(db)
    target = await repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.full_name    is not None: target.full_name    = body.full_name
    if body.is_active    is not None: target.is_active    = body.is_active
    if body.department_id is not None: target.department_id = body.department_id

    await db.flush()
    target = await repo.get_by_id(user_id)
    return _user_to_response(target)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    user:    CurrentUser  = AdminUser,
    db:      AsyncSession = Depends(get_db),
):
    """Soft-delete: set is_active = False and revoke all refresh tokens."""
    if str(user_id) == user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account.")

    repo   = UserRepository(db)
    target = await repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    target.is_active = False
    await repo.revoke_all_user_tokens(user_id)
    await db.flush()
    logger.info(f"Admin {user.email} deactivated user {target.email}")


# ═══════════════════════════════════════
# ROLE MANAGEMENT
# ═══════════════════════════════════════

@router.post("/users/{user_id}/roles", response_model=UserAdminResponse, status_code=200)
async def assign_role(
    user_id: UUID,
    body:    RoleAssignRequest,
    user:    CurrentUser  = AdminUser,
    db:      AsyncSession = Depends(get_db),
):
    """Assign a role to a user. Existing roles are preserved."""
    repo   = UserRepository(db)
    target = await repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    # Get role entity
    result = await db.execute(select(Role).where(Role.name == body.role))
    role   = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{body.role}' not found.")

    # Check not already assigned
    existing_roles = [ur.role.name for ur in target.user_roles if ur.role]
    if body.role in existing_roles:
        raise HTTPException(status_code=409, detail=f"User already has role '{body.role}'.")

    db.add(UserRole(user_id=target.id, role_id=role.id, granted_by=UUID(user.id)))
    await db.flush()

    target = await repo.get_by_id(user_id)
    logger.info(f"Admin {user.email} assigned role '{body.role}' to {target.email}")
    return _user_to_response(target)


@router.delete("/users/{user_id}/roles/{role_name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role(
    user_id:   UUID,
    role_name: str,
    user:      CurrentUser  = AdminUser,
    db:        AsyncSession = Depends(get_db),
):
    """Remove a specific role from a user."""
    from sqlalchemy import delete as sql_delete
    result = await db.execute(
        select(Role).where(Role.name == role_name)
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found.")

    await db.execute(
        sql_delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
        )
    )


# ═══════════════════════════════════════
# AUDIT LOGS
# ═══════════════════════════════════════

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    skip:      int           = Query(0, ge=0),
    limit:     int           = Query(100, ge=1, le=500),
    user_id:   UUID | None   = Query(None),
    action:    str | None    = Query(None),
    user:      CurrentUser   = Depends(require_role("dept_head")),
    db:        AsyncSession  = Depends(get_db),
):
    """Retrieve audit logs. Dept heads and above can access."""
    repo = AuditLogRepository(db)
    logs = await repo.list_recent(
        limit=limit,
        skip=skip,
        user_id=str(user_id) if user_id else None,
        action=action,
    )
    count_result = await db.execute(select(func.count(AuditLog.id)))
    total        = count_result.scalar_one()

    return AuditLogListResponse(
        total=total,
        logs=[
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                ip_address=log.ip_address,
                metadata=log.metadata_,
                created_at=log.created_at,
            )
            for log in logs
        ],
    )


# ═══════════════════════════════════════
# SYSTEM STATS
# ═══════════════════════════════════════

@router.get("/system-stats", response_model=SystemStatsResponse)
async def system_stats(
    user: CurrentUser  = AdminUser,
    db:   AsyncSession = Depends(get_db),
):
    """High-level system counts for the admin dashboard."""
    from db.models.artifact import CourseArtifact
    from db.models.course import Course

    total_users     = (await db.execute(select(func.count(User.id)))).scalar_one()
    total_courses   = (await db.execute(select(func.count(Course.id)))).scalar_one()
    total_artifacts = (await db.execute(select(func.count(CourseArtifact.id)))).scalar_one()

    return SystemStatsResponse(
        total_users=total_users,
        total_courses=total_courses,
        total_artifacts=total_artifacts,
        total_runs=0,           # Populated in Phase 4
        pending_approvals=0,    # Populated in Phase 4
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _user_to_response(user: User) -> UserAdminResponse:
    return UserAdminResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=user.roles,
        department_id=user.department_id,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        last_login=user.last_login,
    )
