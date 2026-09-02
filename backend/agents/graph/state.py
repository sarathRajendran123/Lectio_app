"""
LECTIO — LangGraph Workflow State
The single TypedDict that flows through every node in the agent graph.
LangGraph passes this by value between nodes; each node returns an updated copy.

Design rationale:
  - One state object = one source of truth per workflow run
  - All agents read from and write to this — no inter-agent messaging
  - Serialisable to JSON for checkpointing to PostgreSQL
  - `current_node` drives the Course Director's routing decisions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Enums ─────────────────────────────────────────────────────────────────────

class WorkflowStatus(str, Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    WAITING    = "waiting_for_human"   # HITL pause point
    COMPLETED  = "completed"
    FAILED     = "failed"


class AlignmentSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"
    PASS     = "pass"


class ApprovalDecisionType(str, Enum):
    APPROVED = "approved"
    REVISED  = "revised"
    REJECTED = "rejected"


# ── Sub-models (plain dataclasses for JSON serialisability) ───────────────────

@dataclass
class AlignmentGap:
    gap_id:              str
    gap_type:            str          # clo_not_covered | assessment_missing | sequencing_error | …
    severity:            str          # AlignmentSeverity value
    description:         str
    affected_entity_type: str         # clo | topic | assessment | week
    affected_entity_id:  Optional[str]
    score:               float        # 0.0 – 1.0 (lower = worse alignment)
    recommendation:      str
    evidence_chunk_ids:  List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class AlignmentResult:
    agent_name:    str
    report_type:   str    # metadata_content | content_assessment | metadata_assessment | content_delivery
    overall_score: float
    status:        str    # pass | warning | fail
    gaps:          List[AlignmentGap] = field(default_factory=list)
    findings:      dict   = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent_name":    self.agent_name,
            "report_type":   self.report_type,
            "overall_score": self.overall_score,
            "status":        self.status,
            "gaps":          [g.to_dict() for g in self.gaps],
            "findings":      self.findings,
            "recommendations": self.recommendations,
        }


@dataclass
class GeneratedContentItem:
    item_id:       str
    content_type:  str    # clo | description | exercise | quiz | assessment_suggestion
    title:         str
    content:       str
    bloom_level:   Optional[str]
    source_gap_id: Optional[str]
    citations:     List[dict] = field(default_factory=list)
    confidence:    float = 0.0
    approval_status: str = "pending"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ApprovalRequest:
    request_id:    str
    content_item_id: str
    content_type:  str
    title:         str
    content:       str
    reviewer_id:   Optional[str]
    created_at:    str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ApprovalDecision:
    request_id:  str
    decision:    str    # ApprovalDecisionType value
    reviewer_id: str
    comment:     Optional[str]
    revision:    Optional[str]
    decided_at:  str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class WorkflowError:
    agent:   str
    message: str
    ts:      str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Main State TypedDict ───────────────────────────────────────────────────────

class LectioWorkflowState(TypedDict, total=False):
    # Identity
    run_id:          str
    course_id:       str
    initiated_by:    str        # user UUID

    # Workflow control
    current_node:    str        # which node to execute next
    workflow_status: str        # WorkflowStatus value
    iteration:       int        # safety counter (prevents infinite loops)
    max_iterations:  int

    # Course context (loaded at start)
    course_metadata: Dict[str, Any]   # code, title, level, credits, semester …
    modules:         List[Dict]       # [{id, title, sequence_number, clos: [...]}]
    assessments:     List[Dict]       # [{id, title, type, weight_percent, questions: [...]}]
    artifact_ids:    List[str]        # IDs of uploaded + processed artifacts

    # Alignment results (populated by alignment agents)
    alignment_results: Dict[str, AlignmentResult]
    # Keys: "metadata_content" | "content_assessment" | "metadata_assessment" | "content_delivery"

    # Consolidated gaps (merged by Course Director)
    all_gaps:        List[AlignmentGap]

    # Generation outputs
    generated_items: List[GeneratedContentItem]

    # HITL
    pending_approvals:   List[ApprovalRequest]
    completed_approvals: List[ApprovalDecision]
    reviewer_preferences: str     # Extracted from episodic memory

    # Errors
    error_log:   List[WorkflowError]

    # Tokens consumed (for cost tracking)
    total_tokens: int


# ── Node names (constants used in graph edges) ────────────────────────────────

class Node:
    DIRECTOR              = "course_director"
    META_CONTENT          = "metadata_content_agent"
    CONTENT_ASSESSMENT    = "content_assessment_agent"
    META_ASSESSMENT       = "metadata_assessment_agent"
    CONTENT_DELIVERY      = "content_delivery_agent"
    CONTENT_GENERATION    = "content_generation_agent"
    STAKEHOLDER           = "stakeholder_agent"
    END                   = "__end__"


def initial_state(
    run_id:       str,
    course_id:    str,
    initiated_by: str,
) -> LectioWorkflowState:
    """Create a fresh workflow state."""
    return LectioWorkflowState(
        run_id=run_id,
        course_id=course_id,
        initiated_by=initiated_by,
        current_node=Node.DIRECTOR,
        workflow_status=WorkflowStatus.RUNNING,
        iteration=0,
        max_iterations=20,
        course_metadata={},
        modules=[],
        assessments=[],
        artifact_ids=[],
        alignment_results={},
        all_gaps=[],
        generated_items=[],
        pending_approvals=[],
        completed_approvals=[],
        reviewer_preferences="",
        error_log=[],
        total_tokens=0,
    )
