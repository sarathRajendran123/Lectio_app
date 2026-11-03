"""
LECTIO — User Repository
All database access for users, roles, and auth tokens.
Agents and services NEVER query the DB directly — they use repositories.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth.password_handler import hash_password, verify_password
from auth.jwt_handler import hash_refresh_token
from config import settings
from db.models.user import RefreshToken, Role, User, UserRole

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        email: str,
        password: str,
        full_name: str,
        department_id: Optional[UUID] = None,
        role_name: str = "lecturer",
    ) -> User:
        user = User(
            email=email.lower(),
            hashed_password=hash_password(password),
            full_name=full_name,
            department_id=department_id,
        )
        self.db.add(user)
        await self.db.flush()   # Get ID without full commit

        # Assign default role
        role = await self._get_role_by_name(role_name)
        if role:
            self.db.add(UserRole(user_id=user.id, role_id=role.id))

        await self.db.flush()
        return user

    # ── Auth ───────────────────────────────────────────────────────────────────

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Verify credentials; handle lockout and failed attempt tracking."""
        user = await self.get_by_email(email)
        if not user or not user.is_active:
            return None

        if user.is_locked:
            return None

        if not verify_password(password, user.hashed_password):
            await self._record_failed_attempt(user)
            return None

        # Reset failed attempts on success
        await self.db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                failed_login_attempts=0,
                locked_until=None,
                last_login=datetime.now(timezone.utc),
            )
        )
        return user

    async def _record_failed_attempt(self, user: User) -> None:
        attempts = user.failed_login_attempts + 1
        locked_until = None
        if attempts >= MAX_FAILED_ATTEMPTS:
            locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        await self.db.execute(
            update(User)
            .where(User.id == user.id)
            .values(failed_login_attempts=attempts, locked_until=locked_until)
        )

    # ── Refresh Tokens ─────────────────────────────────────────────────────────

    async def save_refresh_token(self, user_id: UUID, raw_token: str) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
        self.db.add(token)
        await self.db.flush()
        return token

    async def get_refresh_token(self, raw_token: str) -> Optional[RefreshToken]:
        token_hash = hash_refresh_token(raw_token)
        result = await self.db.execute(
            select(RefreshToken)
            .options(selectinload(RefreshToken.user).selectinload(User.user_roles).selectinload(UserRole.role))
            .where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token_id: UUID, reason: str = "logout") -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason)
        )

    async def revoke_all_user_tokens(self, user_id: UUID) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc), revoke_reason="revoke_all")
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _get_role_by_name(self, name: str) -> Optional[Role]:
        result = await self.db.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()
