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
    from services import trace
    from services.intent import ref as intent_ref
    task_id=f"{state['run_id']}:{agent.name}:{dimension or 'coordination'}"
    scope=trace.context(run_id=state['run_id'],course_id=state['course_id'],agent=agent.name,dimension=dimension,task_id=task_id,
        intent=intent_ref(state.get('course_intent')),constraint_ids=[c['id'] for c in state.get('lecturer_constraints') or []])
    scope.__enter__()
    trace.emit('agent_start',{'step':dimension or 'coordination'})
    from config import settings
    def attempt():
        if dimension and settings.runtime_mode == "live" and settings.llm_ready:
            from agents.live_review import prefetch
            prefetch(agent,state)
        output=agent.run(state)
        if dimension:
            from agents.audit_checks import enrich
            output=enrich(agent,output,dimension)
            if settings.runtime_mode == "live" and settings.llm_ready:
                from agents.live_review import augment
                t0=time.monotonic()
                try:
                    output=augment(agent,output,dimension)
                    logger.info('[%s] live review done in %.1fs', dimension, time.monotonic()-t0)
                except Exception as exc:  # a failed model review must not erase the deterministic findings
                    logger.warning('[%s] live review failed after %.1fs: %s', dimension, time.monotonic()-t0, str(exc)[:200])
                    output['alignment_results'][dimension].findings['live_review_error']=str(exc)[:300]
        return output
    # A Division 1 step that fails is asked for again (bounded) before anything is surfaced; only if it
    # still fails is the dimension reported as failed, with the reason.
    tries=1+(max(0,settings.quality_max_retries) if dimension else 0)
    for number in range(1,tries+1):
        try:
            output=attempt(); error=None
            if number>1: output['alignment_results'][dimension].findings['attempts']=number
            break
        except Exception as exc:
            error=str(exc)[:500]
            if dimension is None: raise
            trace.emit('quality_check',{'check':'dimension_completed','passed':False,'attempt':number,'issues':[error[:200]]})
            if number<tries:
                trace.emit('retry',{'attempt':number+1,'reason':'the step failed: '+error[:160],'adjusted_instructions':False,'switched_model':False})
                continue
            output=agent._log_error(state, error)
            output['alignment_results']={**state.get('alignment_results',{}), dimension: AlignmentResult(
                agent.name,dimension,0.,'failed',findings={'error':error,'attempts':number})}
    if dimension and not error:
        from services.constraints import apply_dismissals
        apply_dismissals(output['alignment_results'][dimension],state.get('dismissed_findings') or {})
    async def log():
        async with AsyncSessionLocal() as db:
            db.add(AgentStep(run_id=uuid.UUID(state['run_id']),agent_name=agent.name,
                step_type=dimension or 'coordination',status='failed' if error else 'completed',
                input_summary='Course '+state['course_id'],output_summary='Node completed' if not error else 'Node failed',
                duration_ms=int((time.monotonic()-started)*1000),error_message=error,
                tokens_used=output.get('total_tokens',0)-state.get('total_tokens',0)))
            await db.commit()
    agent._run_async(log())
    result=(output.get('alignment_results') or {}).get(dimension) if dimension else None
    if result is not None:
        # The agent's own decisions, one per finding it raised and one for the dimension as a whole.
        for gap in result.gaps:
            trace.emit('agent_decision',{'decision':'finding_raised','gap_type':gap.gap_type,'severity':gap.severity,'match_score':gap.score,
                'basis':'model_review' if gap.gap_type.startswith('live_') else 'rule_based_check',
                'evidence_chunk_ids':list(gap.evidence_chunk_ids or [])[:8],'affected_entity_type':gap.affected_entity_type,
                'affected_entity_id':gap.affected_entity_id,'previously_dismissed_by':gap.dismissed_by},subject=('gap',gap.gap_id))
        trace.emit('agent_decision',{'decision':'dimension_assessed','score':result.overall_score,'status':result.status,
            'findings':len(result.gaps),'not_assessable_reason':(result.findings or {}).get('reason'),
            'model_review':'failed' if (result.findings or {}).get('live_review_error') else 'done' if (result.findings or {}).get('live_review') else 'not_run'})
    trace.emit('agent_failed' if error else 'agent_complete',{'step':dimension or 'coordination','error':error,
        'duration_ms':int((time.monotonic()-started)*1000),'tokens':output.get('total_tokens',0)-state.get('total_tokens',0),
        'intent':intent_ref(output.get('course_intent')),'score':getattr(result,'overall_score',None),'status':getattr(result,'status',None),
        'gaps':len(getattr(result,'gaps',[]) or []),'model_review_error':(getattr(result,'findings',{}) or {}).get('live_review_error')})
    scope.__exit__(None,None,None)
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
