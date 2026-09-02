"""
LECTIO — JWT Access Token Handler
Creates and validates short-lived JWT access tokens.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt

from config import settings


# ── Token Creation ─────────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    email: str,
    roles: list[str],
    department_id: Optional[str] = None,
) -> str:
    """Create a signed JWT access token (15-minute lifetime)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub":           user_id,
        "email":         email,
        "roles":         roles,
        "department_id": department_id,
        "iat":           now,
        "exp":           now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti":           secrets.token_hex(16),   # Unique token ID
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> tuple[str, str]:
    """
    Generate a secure opaque refresh token.
    Returns (raw_token, hash_to_store_in_db).
    Store only the hash — never the raw token.
    """
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, token_hash


# ── Token Validation ───────────────────────────────────────────────────────────

class TokenPayload:
    def __init__(self, payload: dict):
        self.user_id: str       = payload["sub"]
        self.email: str         = payload["email"]
        self.roles: list[str]   = payload.get("roles", [])
        self.department_id: Optional[str] = payload.get("department_id")
        self.jti: str           = payload.get("jti", "")


def decode_access_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT access token.
    Raises JWTError on invalid/expired tokens.
    """
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    return TokenPayload(payload)


def hash_refresh_token(raw_token: str) -> str:
    """Hash a raw refresh token for DB lookup."""
    return hashlib.sha256(raw_token.encode()).hexdigest()
