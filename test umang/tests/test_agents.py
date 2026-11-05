from agents.graph.state import AlignmentResult,AlignmentGap,Node
from agents.course_director import CourseDirectorAgent
from agents.live_review import augment
from rag.chunking.chunk_models import RetrievedChunk
from scripts.evaluate import evaluate
import pytest

def test_director_merges_before_generation_route(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings,'generation_auto_enabled',True)
    gap=AlignmentGap('g','clo_not_covered','warning','Missing topic','clo',None,0.,'Review sources')
    state={'course_id':'x','course_metadata':{'title':'x'},'alignment_results':{
        dimension:AlignmentResult('a',dimension,.5,'warning',[gap] if dimension=='metadata_content' else [])
        for dimension in ('metadata_content','content_assessment','metadata_assessment','content_delivery')},'all_gaps':[]}
    result=CourseDirectorAgent().run(state)
    assert result['current_node']==Node.CONTENT_GENERATION
    assert len(result['all_gaps'])==1

def test_live_review_rejects_unretrieved_evidence():
    import json
    class Agent:
        def _retrieve(self,*a,**k):return [RetrievedChunk('real','Real source excerpt',.8,'a','slides','c',1,None,None,None)]
        def _invoke(self,*a,**k):return json.dumps({'findings':[{'title':'Finding','description':'An unsupported conclusion','severity':'warning','rationale':'Rationale here','correction':'Review this issue','evidence_ids':['invented'],'evidence_strength':'strong'}],'limitations':'Unverified'}),10
        def _parse_json(self,text):return json.loads(text)
    state={'course_id':'c','modules':[],'course_metadata':{'title':'Topic'},'alignment_results':{'metadata_content':AlignmentResult('a','metadata_content',.5,'warning')}}
    augment(Agent(),state,'metadata_content')
    result=state['alignment_results']['metadata_content']
    assert result.gaps==[] and result.findings['live_review']['discarded_unverifiable']==1   # invented evidence never surfaces

def test_evaluation_is_ground_truth_based():
    result=evaluate([{'predicted':'1','actual':'1','accepted':'1','quality':'4'}, {'predicted':'1','actual':'0','accepted':'0'}, {'predicted':'0','actual':'1'}])
    assert result['precision']==.5 and result['recall']==.5 and result['acceptance_rate']==.5

def test_generation_marks_empty_action_list_attempted():
    from agents.content_generation_agent import ContentGenerationAgent
    state={'course_id':'x','all_gaps':[AlignmentGap('g','objective_not_measurable','warning','Vague verb','clo',None,.2,'Review verb')]}
    result=ContentGenerationAgent().run(state)
    assert result['generation_attempted'] is True


def test_live_reviews_are_prefetched_concurrently_and_called_once_each():
    import json, threading
    from agents.live_review import DIMENSIONS, augment, prefetch
    calls = []
    class Agent:
        def _retrieve(self, *a, **k): return [RetrievedChunk('real', 'Real source excerpt', .8, 'a', 'slides', 'c', 1, None, None, None)]
        def _invoke(self, *a, **k):
            calls.append(threading.current_thread().name)
            return json.dumps({'findings': [], 'limitations': 'None found'}), 5
        def _parse_json(self, text): return json.loads(text)
    state = {'run_id': 'r1', 'course_id': 'c', 'modules': [], 'course_metadata': {'title': 'T'},
             'alignment_results': {d: AlignmentResult('a', d, .9, 'pass') for d in DIMENSIONS}}
    prefetch(Agent(), state); prefetch(Agent(), state)   # second call must not resubmit
    for d in DIMENSIONS: out = augment(Agent(), state, d)
    assert len(calls) == len(DIMENSIONS) and all(n.startswith('live-review') for n in calls)
    assert out['total_tokens'] == 5


def test_confirmations_are_not_gaps_and_fixable_findings_get_draftable_gap_types():
    import json
    from agents.live_review import DIMENSIONS, augment
    finding = lambda title, fixable: {'title': title, 'description': 'Described in detail here', 'severity': 'warning', 'rationale': 'Because',
        'correction': 'Add one', 'evidence_ids': ['real'], 'evidence_strength': 'moderate', 'fixable_by': fixable}
    class Agent:
        def _retrieve(self, *a, **k): return [RetrievedChunk('real', 'Real source excerpt', .8, 'a', 'slides', 'c', 1, None, None, None)]
        def _invoke(self, *a, **k):
            return json.dumps({'findings': [finding('No objective covers graphs', 'objective'), finding('Exam items unmapped', 'assessment'),
                finding('Schedule unclear', 'none')], 'confirmed': ['Binary search objective is supported by the slides'],
                'limitations': 'x'}), 7
        def _parse_json(self, text): return json.loads(text)
    state = {'course_id': 'c', 'modules': [], 'course_metadata': {'title': 'T'},
             'alignment_results': {d: AlignmentResult('a', d, .9, 'pass') for d in DIMENSIONS}}
    augment(Agent(), state, 'metadata_content')
    result = state['alignment_results']['metadata_content']
    assert [g.gap_type for g in result.gaps] == ['live_missing_objective', 'live_missing_assessment', 'live_alignment_review']
    assert result.findings['live_review']['confirmed'] == ['Binary search objective is supported by the slides']
    assert not any('supported' in g.description for g in result.gaps)
