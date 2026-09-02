"""
LECTIO — Admin Bootstrap
Ensures a default admin account exists on startup. Replaces the old
manual `scripts/seed_db.py` step — this now runs automatically every
time the backend starts, and safely does nothing if the admin (or the
role) already exists.
"""

import logging

from sqlalchemy import select

from config import settings
from db.session import AsyncSessionLocal
from db.models.user import Role, User, UserRole
from auth.password_handler import hash_password

logger = logging.getLogger(__name__)


async def ensure_admin_user() -> None:
    """Create the default admin user + admin role if they don't exist yet."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == settings.admin_email))
        if result.scalar_one_or_none():
            logger.info(f"Admin user {settings.admin_email} already exists — skipping bootstrap.")
            return

        result = await db.execute(select(Role).where(Role.name == "admin"))
        admin_role = result.scalar_one_or_none()
        if not admin_role:
            admin_role = Role(name="admin", description="System administrator")
            db.add(admin_role)
            await db.flush()

        admin = User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            full_name=settings.admin_full_name,
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        await db.flush()

        db.add(UserRole(user_id=admin.id, role_id=admin_role.id))
        await db.commit()

        logger.warning(
            f"Bootstrapped admin user '{settings.admin_email}' with the default password "
            f"from ADMIN_PASSWORD. Log in and change it immediately."
        )
