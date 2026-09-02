"""
LECTIO — Authentication Router
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt_handler import create_access_token, create_refresh_token
from auth.rbac import CurrentUser, get_current_user
from config import settings
from db.repositories.user_repository import UserRepository
from db.session import get_db
from schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserProfileResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── POST /login ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
    body:    LoginRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate with email + password.
    Returns an access token (15 min) and refresh token (7 days).
    """
    repo = UserRepository(db)
    user = await repo.authenticate(email=body.email, password=body.password)

    if not user:
        logger.warning(f"Failed login attempt for {body.email} from {request.client.host}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Generate tokens
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        roles=user.roles,
        department_id=str(user.department_id) if user.department_id else None,
    )
    raw_refresh, _ = create_refresh_token()
    await repo.save_refresh_token(user.id, raw_refresh)

    logger.info(f"User {user.email} logged in successfully.")

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── POST /refresh ──────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh_token(
    body: RefreshRequest,
    db:   AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange a valid refresh token for new access + refresh tokens.
    Old refresh token is revoked (rotation).
    """
    repo = UserRepository(db)
    stored = await repo.get_refresh_token(body.refresh_token)

    if not stored or not stored.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired.",
        )

    user = stored.user

    # Revoke old refresh token (rotation)
    await repo.revoke_refresh_token(stored.id, reason="rotated")

    # Issue new tokens
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        roles=user.roles,
        department_id=str(user.department_id) if user.department_id else None,
    )
    raw_refresh, _ = create_refresh_token()
    await repo.save_refresh_token(user.id, raw_refresh)

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── POST /logout ───────────────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body:         RefreshRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> None:
    """Revoke the provided refresh token. Access token expires naturally."""
    repo = UserRepository(db)
    stored = await repo.get_refresh_token(body.refresh_token)
    if stored and stored.user_id == current_user.id:  # type: ignore
        await repo.revoke_refresh_token(stored.id, reason="logout")


# ── GET /me ────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfileResponse, status_code=status.HTTP_200_OK)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    """Return the current authenticated user's profile."""
    repo = UserRepository(db)
    user = await repo.get_by_id(current_user.id)  # type: ignore
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        roles=user.roles,
        department_id=str(user.department_id) if user.department_id else None,
        is_active=user.is_active,
    )
