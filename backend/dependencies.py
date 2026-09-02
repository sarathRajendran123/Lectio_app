"""
LECTIO — FastAPI shared dependencies.
Central place for all Depends() used across routes.
"""

from db.session import get_db
from auth.rbac import get_current_user, require_role, CurrentUser

__all__ = [
    "get_db",
    "get_current_user",
    "require_role",
    "CurrentUser",
]
