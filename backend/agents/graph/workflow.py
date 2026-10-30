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

def execute_agent(agent, state, dimension=None):
    import time, uuid
    from db.models.generated_content import AgentStep
    from db.session import AsyncSessionLocal
    from agents.graph.state import AlignmentResult
    started=time.monotonic(); error=None
    try:
        output=agent.run(state)
        if dimension:
            from agents.audit_checks import enrich
            output=enrich(agent,output,dimension)
            from config import settings
            if settings.runtime_mode == "live" and settings.groq_api_key:
                from agents.live_review import augment
                output=augment(agent,output,dimension)
    except Exception as exc:
        error=str(exc)[:500]
        if dimension is None: raise
        output=agent._log_error(state, error)
        output['alignment_results']={**state.get('alignment_results',{}), dimension: AlignmentResult(
            agent.name,dimension,0.,'failed',findings={'error':error})}
    async def log():
        async with AsyncSessionLocal() as db:
            db.add(AgentStep(run_id=uuid.UUID(state['run_id']),agent_name=agent.name,
                step_type=dimension or 'coordination',status='failed' if error else 'completed',
                input_summary='Course '+state['course_id'],output_summary='Node completed' if not error else 'Node failed',
                duration_ms=int((time.monotonic()-started)*1000),error_message=error,
                tokens_used=output.get('total_tokens',0)-state.get('total_tokens',0)))
            await db.commit()
    agent._run_async(log())
    return output

def director_node(state): return execute_agent(_director,state)
def meta_content_node(state): return execute_agent(_meta_content,state,'metadata_content')
def content_assessment_node(state): return execute_agent(_cont_assess,state,'content_assessment')
def meta_assessment_node(state): return execute_agent(_meta_assess,state,'metadata_assessment')
def content_delivery_node(state): return execute_agent(_cont_deliver,state,'content_delivery')
def generation_node(state): return execute_agent(_generation,state)
def stakeholder_node(state): return execute_agent(_stakeholder,state)


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
