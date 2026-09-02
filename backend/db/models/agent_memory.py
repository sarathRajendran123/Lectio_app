"""LECTIO — AgentMemory ORM Model"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id:          Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_type: Mapped[str]                = mapped_column(String(100), nullable=False)
    user_id:     Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    course_id:   Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"))
    content:     Mapped[dict]               = mapped_column(JSONB, nullable=False, default=dict)
    chroma_id:   Mapped[Optional[str]]      = mapped_column(String(255))
    created_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
