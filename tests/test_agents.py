from agents.graph.state import AlignmentResult,AlignmentGap,Node
from agents.course_director import CourseDirectorAgent
from agents.live_review import augment
from rag.chunking.chunk_models import RetrievedChunk
from scripts.evaluate import evaluate
import pytest

def test_director_merges_before_generation_route():
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
        def _invoke(self,*a):return json.dumps({'findings':[{'title':'Finding','description':'An unsupported conclusion','severity':'warning','rationale':'Rationale here','correction':'Review this issue','evidence_ids':['invented'],'evidence_strength':'strong'}],'limitations':'Unverified'}),10
        def _parse_json(self,text):return json.loads(text)
    with pytest.raises(ValueError,match='unknown source'):
        augment(Agent(),{'course_id':'c','modules':[],'course_metadata':{'title':'Topic'},'alignment_results':{'metadata_content':AlignmentResult('a','metadata_content',.5,'warning')}},'metadata_content')

def test_live_review_rejects_entire_response_when_later_citation_invalid():
    import json
    class Agent:
        def _retrieve(self,*a,**k):return [RetrievedChunk('real','Real source excerpt',.8,'a','slides','c',1,None,None,None)]
        def _invoke(self,*a):
            finding={'title':'Finding','description':'A proposed conclusion','severity':'warning','rationale':'Rationale here','correction':'Review this issue','evidence_ids':['S1'],'evidence_strength':'strong'}
            return json.dumps({'findings':[finding,{**finding,'evidence_ids':['invented']}],'limitations':'Unverified'}),10
        def _parse_json(self,text):return json.loads(text)
    report=AlignmentResult('a','metadata_content',.5,'warning')
    state={'course_id':'c','modules':[],'course_metadata':{'title':'Topic'},'alignment_results':{'metadata_content':report}}
    with pytest.raises(ValueError,match='unknown source'):augment(Agent(),state,'metadata_content')
    assert report.gaps == []

def test_live_review_resolves_aliases_to_real_chunk_ids():
    import json
    class Agent:
        def _retrieve(self,*a,**k):return [RetrievedChunk('real','Real source excerpt',.8,'a','slides','c',1,None,None,None)]
        def _invoke(self,system,human):
            assert 'ID=S1' in human
            return json.dumps({'findings':[{'title':'Finding','description':'A grounded conclusion','severity':'warning','rationale':'Rationale here','correction':'Review this issue','evidence_ids':['S1'],'evidence_strength':'strong'}],'limitations':'Unverified'}),10
        def _parse_json(self,text):return json.loads(text)
    report=AlignmentResult('a','metadata_content',.5,'warning')
    state={'course_id':'c','modules':[],'course_metadata':{'title':'Topic'},'alignment_results':{'metadata_content':report}}
    output=augment(Agent(),state,'metadata_content')
    assert report.gaps[0].evidence_chunk_ids == ['real']
    assert output['total_tokens'] == 10

def test_evaluation_is_ground_truth_based():
    result=evaluate([{'predicted':'1','actual':'1','accepted':'1','quality':'4'}, {'predicted':'1','actual':'0','accepted':'0'}, {'predicted':'0','actual':'1'}])
    assert result['precision']==.5 and result['recall']==.5 and result['acceptance_rate']==.5

def test_generation_marks_empty_action_list_attempted():
    from agents.content_generation_agent import ContentGenerationAgent
    state={'course_id':'x','all_gaps':[AlignmentGap('g','objective_not_measurable','warning','Vague verb','clo',None,.2,'Review verb')]}
    result=ContentGenerationAgent().run(state)
    assert result['generation_attempted'] is True
