"""
LECTIO — LangGraph Compiled Workflow

Graph structure:
  START → course_director → [alignment agents] → course_director
        → content_generation → course_director → stakeholder → END

The Course Director is the hub — all agents return to it after completing,
and it decides where to route next based on workflow state.
"""

import logging

from langgraph.graph import END, START, StateGraph

from agents.graph.state import LectioWorkflowState, Node
from agents.course_director import CourseDirectorAgent
from agents.metadata_content_agent import MetadataContentAlignmentAgent
from agents.alignment_agents import (
    MetadataAssessmentAlignmentAgent,
    ContentDeliveryAlignmentAgent,
)
from agents.content_assessment_agent import ContentAssessmentAlignmentAgent
from agents.content_generation_agent import ContentGenerationAgent
from agents.stakeholder_agent import StakeholderAgent

logger = logging.getLogger(__name__)

# ── Instantiate agents (singletons) ──────────────────────────────────────────
_director     = CourseDirectorAgent()
_meta_content = MetadataContentAlignmentAgent()
_cont_assess  = ContentAssessmentAlignmentAgent()
_meta_assess  = MetadataAssessmentAlignmentAgent()
_cont_deliver = ContentDeliveryAlignmentAgent()
_generation   = ContentGenerationAgent()
_stakeholder  = StakeholderAgent()


# ── Node wrappers (LangGraph expects plain functions) ─────────────────────────

def director_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _director.run(state)

def meta_content_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _meta_content.run(state)

def content_assessment_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _cont_assess.run(state)

def meta_assessment_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _meta_assess.run(state)

def content_delivery_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _cont_deliver.run(state)

def generation_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _generation.run(state)

def stakeholder_node(state: LectioWorkflowState) -> LectioWorkflowState:
    return _stakeholder.run(state)


# ── Conditional edge: Director decides where to go next ──────────────────────

def director_router(state: LectioWorkflowState) -> str:
    """Return the name of the next node based on current_node set by Director."""
    target = state.get("current_node", Node.END)

    routing_map = {
        Node.META_CONTENT:       Node.META_CONTENT,
        Node.CONTENT_ASSESSMENT: Node.CONTENT_ASSESSMENT,
        Node.META_ASSESSMENT:    Node.META_ASSESSMENT,
        Node.CONTENT_DELIVERY:   Node.CONTENT_DELIVERY,
        Node.CONTENT_GENERATION: Node.CONTENT_GENERATION,
        Node.STAKEHOLDER:        Node.STAKEHOLDER,
        Node.END:                END,
    }

    route = routing_map.get(target, END)
    logger.debug(f"[Router] Director → {route}")
    return route


# ── Build the graph ───────────────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    """Compile and return the LECTIO LangGraph workflow."""

    graph = StateGraph(LectioWorkflowState)

    # Register nodes
    graph.add_node(Node.DIRECTOR,           director_node)
    graph.add_node(Node.META_CONTENT,       meta_content_node)
    graph.add_node(Node.CONTENT_ASSESSMENT, content_assessment_node)
    graph.add_node(Node.META_ASSESSMENT,    meta_assessment_node)
    graph.add_node(Node.CONTENT_DELIVERY,   content_delivery_node)
    graph.add_node(Node.CONTENT_GENERATION, generation_node)
    graph.add_node(Node.STAKEHOLDER,        stakeholder_node)

    # Entry point
    graph.add_edge(START, Node.DIRECTOR)

    # Director uses a conditional edge to route dynamically
    graph.add_conditional_edges(
        Node.DIRECTOR,
        director_router,
        {
            Node.META_CONTENT:       Node.META_CONTENT,
            Node.CONTENT_ASSESSMENT: Node.CONTENT_ASSESSMENT,
            Node.META_ASSESSMENT:    Node.META_ASSESSMENT,
            Node.CONTENT_DELIVERY:   Node.CONTENT_DELIVERY,
            Node.CONTENT_GENERATION: Node.CONTENT_GENERATION,
            Node.STAKEHOLDER:        Node.STAKEHOLDER,
            END:                     END,
        },
    )

    # All agents return to Director after completing
    for node in [
        Node.META_CONTENT,
        Node.CONTENT_ASSESSMENT,
        Node.META_ASSESSMENT,
        Node.CONTENT_DELIVERY,
        Node.CONTENT_GENERATION,
    ]:
        graph.add_edge(node, Node.DIRECTOR)

    # Stakeholder → END (HITL pause or completion)
    graph.add_edge(Node.STAKEHOLDER, END)

    return graph.compile()


# ── Module-level compiled app (import once, reuse everywhere) ─────────────────
workflow_app = build_workflow()
