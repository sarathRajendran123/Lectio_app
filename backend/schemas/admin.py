"""
LECTIO — Admin Pydantic Schemas
User management, role assignment, audit log queries.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreateRequest(BaseModel):
    email:         EmailStr
    password:      str       = Field(..., min_length=8)
    full_name:     str       = Field(..., min_length=2, max_length=255)
    role:          str       = Field(default="lecturer")
    department_id: Optional[UUID] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid = {"admin", "dept_head", "coordinator", "lecturer"}
        if v not in valid:
            raise ValueError(f"role must be one of {valid}")
        return v


class UserUpdateRequest(BaseModel):
    full_name:     Optional[str]  = Field(None, min_length=2, max_length=255)
    is_active:     Optional[bool] = None
    department_id: Optional[UUID] = None


class UserAdminResponse(BaseModel):
    id:            UUID
    email:         str
    full_name:     str
    roles:         List[str]
    department_id: Optional[UUID]
    is_active:     bool
    is_verified:   bool
    created_at:    datetime
    last_login:    Optional[datetime]

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    total: int
    users: List[UserAdminResponse]


class RoleAssignRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid = {"admin", "dept_head", "coordinator", "lecturer"}
        if v not in valid:
            raise ValueError(f"role must be one of {valid}")
        return v


class AuditLogResponse(BaseModel):
    id:            UUID
    user_id:       Optional[UUID]
    action:        str
    resource_type: Optional[str]
    resource_id:   Optional[UUID]
    ip_address:    Optional[str]
    metadata:      Optional[Dict[str, Any]]
    created_at:    datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    total:  int
    logs:   List[AuditLogResponse]


class SystemStatsResponse(BaseModel):
    total_users:     int
    total_courses:   int
    total_artifacts: int
    total_runs:      int
    pending_approvals: int
