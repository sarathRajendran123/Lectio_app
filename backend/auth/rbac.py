"""
LECTIO — Role-Based Access Control
FastAPI dependencies that enforce role requirements at route level.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt_handler import TokenPayload, decode_access_token

# Role hierarchy (index = power level)
ROLE_HIERARCHY = ["lecturer", "coordinator", "dept_head", "admin"]

bearer_scheme = HTTPBearer()


class CurrentUser:
    """Injected into route handlers via Depends(get_current_user)."""
    def __init__(self, payload: TokenPayload):
        self.id:            str            = payload.user_id
        self.email:         str            = payload.email
        self.roles:         list[str]      = payload.roles
        self.department_id: Optional[str]  = payload.department_id

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_min_role(self, min_role: str) -> bool:
        """True if the user has at least min_role in the hierarchy."""
        min_level = ROLE_HIERARCHY.index(min_role) if min_role in ROLE_HIERARCHY else 0
        user_level = max(
            (ROLE_HIERARCHY.index(r) for r in self.roles if r in ROLE_HIERARCHY),
            default=-1,
        )
        return user_level >= min_level

    @property
    def is_admin(self) -> bool:
        return self.has_role("admin")


# ── Core dependency ───────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    """Extract and validate the JWT; return the current user."""
    try:
        payload = decode_access_token(credentials.credentials)
        return CurrentUser(payload)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Role-specific dependencies ────────────────────────────────────────────────

def require_role(min_role: str):
    """
    Factory: returns a FastAPI dependency that enforces a minimum role.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user = Depends(require_role("admin"))):
            ...
    """
    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_min_role(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires at least the '{min_role}' role.",
            )
        return user
    return dependency


# ── Convenience aliases ───────────────────────────────────────────────────────
RequireLecturer    = Depends(require_role("lecturer"))
RequireCoordinator = Depends(require_role("coordinator"))
RequireDeptHead    = Depends(require_role("dept_head"))
RequireAdmin       = Depends(require_role("admin"))
