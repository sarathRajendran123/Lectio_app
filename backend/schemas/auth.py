"""
LECTIO — Auth Pydantic Schemas
Request/response models for authentication endpoints.
"""

from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


# ── Request Schemas ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

    class Config:
        json_schema_extra = {
            "example": {
                "email":    "lecturer@university.ac.za",
                "password": "SecurePass123!",
            }
        }


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token:        str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


# ── Response Schemas ───────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int       # seconds


class UserProfileResponse(BaseModel):
    id:            str
    email:         str
    full_name:     str
    roles:         list[str]
    department_id: Optional[str]
    is_active:     bool

    class Config:
        from_attributes = True
