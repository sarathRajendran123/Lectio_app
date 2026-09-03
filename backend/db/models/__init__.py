"""LECTIO — ORM Model Registry"""

from db.models.user import Department, RefreshToken, Role, User, UserRole
from db.models.artifact import Chunk, CourseArtifact
from db.models.course import (
    Assessment, AssessmentQuestion, Course, LearningObjective,
    Module, Rubric, RubricCriteria, Subtopic, Topic, Week,
)
from db.models.agent_memory import AgentMemory
from db.models.report import AlignmentGapRecord, AlignmentReport
from db.models.generated_content import (
    AgentRun, AgentStep, ApprovalRecord, GeneratedContentRecord,
)
from api.v1.middleware.audit_logger import AuditLog

__all__ = [
    "Department", "User", "Role", "UserRole", "RefreshToken",
    "Course", "Module", "Week", "Topic", "Subtopic",
    "LearningObjective", "Assessment", "AssessmentQuestion",
    "Rubric", "RubricCriteria", "CourseArtifact", "Chunk",
    "AgentMemory", "AlignmentReport", "AlignmentGapRecord",
    "AgentRun", "AgentStep", "GeneratedContentRecord", "ApprovalRecord",
    "AuditLog",
]

def _resolve():
    pass
