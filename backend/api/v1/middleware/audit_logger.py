"""
LECTIO — Audit Log Middleware & ORM Model
Every mutating request (POST / PATCH / PUT / DELETE) is logged
to the audit_logs table with user, action, resource, and IP.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Request, Response
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from db.base import Base
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ── ORM Model ─────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id:            Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:       Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action:        Mapped[str]             = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]]   = mapped_column(String(100))
    resource_id:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ip_address:    Mapped[Optional[str]]   = mapped_column(INET)   # DB column is INET, not VARCHAR
    user_agent:    Mapped[Optional[str]]   = mapped_column(Text)
    metadata_:     Mapped[Optional[dict]]  = mapped_column("metadata", JSONB)
    created_at:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Repository ────────────────────────────────────────────────────────────────

class AuditLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def write(
        self,
        action: str,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        log = AuditLog(
            user_id=uuid.UUID(user_id) if user_id else None,
            action=action,
            resource_type=resource_type,
            resource_id=uuid.UUID(resource_id) if resource_id else None,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_=metadata or {},
        )
        self.db.add(log)
        # No flush here — caller commits

    async def list_recent(
        self,
        limit: int = 100,
        skip: int = 0,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ):
        from sqlalchemy import select
        q = select(AuditLog).order_by(AuditLog.created_at.desc())
        if user_id:
            q = q.where(AuditLog.user_id == uuid.UUID(user_id))
        if action:
            q = q.where(AuditLog.action == action)
        result = await self.db.execute(q.offset(skip).limit(limit))
        return list(result.scalars().all())


# ── Middleware ─────────────────────────────────────────────────────────────────

AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PATHS      = {"/health", "/docs", "/redoc", "/openapi.json"}


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Logs every state-changing HTTP request to audit_logs.
    Extracts the user from the JWT in the Authorization header (best-effort).
    Does not block requests if logging fails.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        if request.method not in AUDITED_METHODS:
            return response
        if request.url.path in SKIP_PATHS:
            return response

        try:
            await self._log(request, response)
        except Exception as exc:
            logger.warning(f"AuditMiddleware: failed to write log — {exc}")

        return response

    async def _log(self, request: Request, response: Response) -> None:
        user_id = self._extract_user_id(request)
        action  = f"{request.method} {request.url.path}"
        resource_type, resource_id = self._parse_resource(request.url.path)

        async with AsyncSessionLocal() as db:
            repo = AuditLogRepository(db)
            await repo.write(
                action=action,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=self._get_ip(request),
                user_agent=request.headers.get("user-agent"),
                metadata={
                    "status_code": response.status_code,
                    "query_params": str(request.query_params),
                },
            )
            await db.commit()

    def _extract_user_id(self, request: Request) -> Optional[str]:
        """Best-effort JWT parse — does not validate; that's the auth layer's job."""
        try:
            from auth.jwt_handler import decode_access_token
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                payload = decode_access_token(auth[7:])
                return payload.user_id
        except Exception:
            pass
        return None

    def _get_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _parse_resource(self, path: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract resource type and ID from URL patterns like:
          /api/v1/courses/{uuid}  →  ("course", "{uuid}")
          /api/v1/courses/{uuid}/artifacts/{uuid}  →  ("artifact", "{uuid}")
        """
        parts = [p for p in path.split("/") if p]
        resource_type = None
        resource_id   = None

        for i, part in enumerate(parts):
            if part in ("courses", "artifacts", "users", "runs", "reports", "approvals"):
                resource_type = part.rstrip("s")   # crude singularisation
                if i + 1 < len(parts):
                    candidate = parts[i + 1]
                    if len(candidate) == 36:        # looks like a UUID
                        resource_id = candidate

        return resource_type, resource_id
