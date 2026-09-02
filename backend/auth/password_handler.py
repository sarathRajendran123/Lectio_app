"""
LECTIO — Password Hashing
bcrypt with work factor 12 (industry standard for 2024+).
Uses bcrypt directly to avoid passlib/bcrypt 4.x version conflicts.
"""

import bcrypt


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (work factor 12)."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
