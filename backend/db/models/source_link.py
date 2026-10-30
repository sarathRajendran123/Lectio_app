"""Provenance links for extracted assessment tasks and automatic candidates."""
import uuid
from sqlalchemy import ForeignKey,String
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base

class AssessmentSource(Base):
    __tablename__='assessment_sources'
    assessment_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('assessments.id',ondelete='CASCADE'),primary_key=True)
    artifact_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('course_artifacts.id',ondelete='CASCADE'))
    chunk_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey('chunks.id',ondelete='CASCADE'))
    extraction_method:Mapped[str]=mapped_column(String(60),default='source_text_candidate')
