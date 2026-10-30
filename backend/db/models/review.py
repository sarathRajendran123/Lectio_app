"""Append-only lecturer decisions for audit findings."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime,ForeignKey,String,Text,func
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy.dialects.postgresql import UUID
from db.types import JSONB
from db.base import Base

class FindingDecision(Base):
    __tablename__='finding_decisions'
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    gap_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('alignment_gaps.id',ondelete='CASCADE'))
    reviewer_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('users.id',ondelete='CASCADE'))
    decision:Mapped[str]=mapped_column(String(30))
    rationale:Mapped[str|None]=mapped_column(Text)
    revised_recommendation:Mapped[str|None]=mapped_column(Text)
    version_context:Mapped[dict]=mapped_column(JSONB,default=dict)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class AppliedSuggestion(Base):
    __tablename__='applied_suggestions'
    content_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('generated_content.id',ondelete='CASCADE'),primary_key=True)
    target_type:Mapped[str]=mapped_column(String(40))
    target_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True))
    applied_by:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('users.id',ondelete='CASCADE'))
    accepted_snapshot:Mapped[str]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
