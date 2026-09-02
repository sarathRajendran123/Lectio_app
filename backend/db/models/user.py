"""
LECTIO — User, Role, Department ORM Models
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Department(Base):
    __tablename__ = "departments"

    id:         Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name:       Mapped[str]             = mapped_column(String(255), nullable=False)
    code:       Mapped[str]             = mapped_column(String(20), unique=True, nullable=False)
    faculty:    Mapped[Optional[str]]   = mapped_column(String(255))
    created_at: Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())

    users:   Mapped[List["User"]]   = relationship(back_populates="department")


class Role(Base):
    __tablename__ = "roles"

    id:          Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name:        Mapped[str]           = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    created_at:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    user_roles: Mapped[List["UserRole"]] = relationship(back_populates="role")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id:    Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id:    Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())

    role: Mapped["Role"] = relationship(back_populates="user_roles")


class User(Base):
    __tablename__ = "users"

    id:                     Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email:                  Mapped[str]                 = mapped_column(String(255), unique=True, nullable=False)
    hashed_password:        Mapped[str]                 = mapped_column(String(255), nullable=False)
    full_name:              Mapped[str]                 = mapped_column(String(255), nullable=False)
    is_active:              Mapped[bool]                = mapped_column(Boolean, default=True)
    is_verified:            Mapped[bool]                = mapped_column(Boolean, default=False)
    department_id:          Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"))
    created_at:             Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:             Mapped[datetime]            = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login:             Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))
    failed_login_attempts:  Mapped[int]                 = mapped_column(Integer, default=0)
    locked_until:           Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))

    department: Mapped[Optional["Department"]] = relationship(back_populates="users")
    user_roles: Mapped[List["UserRole"]]       = relationship(
        foreign_keys="UserRole.user_id",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def roles(self) -> List[str]:
        return [ur.role.name for ur in self.user_roles if ur.role]

    @property
    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        return datetime.now(timezone.utc) < self.locked_until


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id:           Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:      Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    token_hash:   Mapped[str]                = mapped_column(String(64), nullable=False)
    issued_at:    Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at:   Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[Optional[str]]     = mapped_column(String(50))

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and datetime.now(timezone.utc) < self.expires_at
