import json
import uuid
import httpx
import pytest
from rag.chunking.chunk_models import RetrievedChunk
from rag.generation.draft_schema import parse_draft
from agents.quality_broker import broker
from agents.graph.state import AlignmentGap,AlignmentResult
from scripts.paperclip_process import PaperclipGovernance

def source():return RetrievedChunk('real','Binary search halves a sorted array. It has logarithmic complexity.',.8,'doc','slides','course',1,None,None,None)
def payload(quote='Binary search halves a sorted array.'):
    return json.dumps({'title':'Binary search practice','sections':[{'heading':'Task','text':'Explain why binary search needs a sorted array.','supports':[{'source':1,'quote':quote}],'interpretation':'proposed_content'}],'limitations':['Instructor must review difficulty.'],'bloom_level':'understand'})
def test_strict_generation_schema_and_quotes():
    text,citations,draft=parse_draft(payload(),[source()])
    assert 'lecturer review required' in text and citations[0]['quote'] in source().text
    with pytest.raises(ValueError,match='verbatim'):parse_draft(payload('This quote is fabricated.'),[source()])
    with pytest.raises(ValueError):parse_draft('{"title":"Missing sections"}',[source()])

def test_broker_duplicates_conflicts_and_evidence():
    gaps=[AlignmentGap(str(uuid.uuid4()),'coverage','warning','Missing topic','clo','x',.2,'Add lecture material',['real']),
        AlignmentGap(str(uuid.uuid4()),'coverage','critical','Missing topic','clo','x',.2,'Add lecture material',['real']),
        AlignmentGap(str(uuid.uuid4()),'scope','info','Scope excess','clo','x',.1,'Remove excess material',[])]
    result=broker({'metadata_content':AlignmentResult('a','metadata_content',.2,'warning',gaps)})
    assert result['duplicate_count']==1
    assert result['ranked_findings'][0]['priority']>result['ranked_findings'][1]['priority']
    assert result['possible_conflicts'] and all(f['review_required'] for f in result['ranked_findings'])

def test_paperclip_checkout_and_human_handoff_contract():
    calls=[]
    def handle(request):
        calls.append(request)
        assert request.headers['x-paperclip-run-id']=='run-1'
        if request.url.path=='/api/agents/me':return httpx.Response(200,json={'id':'agent-1'})
        if request.url.path.endswith('/checkout'):
            assert json.loads(request.content)['agentId']=='agent-1'
            return httpx.Response(200,json={'status':'in_progress'})
        body=json.loads(request.content);assert body['status']=='in_review';assert 'human_approval_required' in body['comment']
        return httpx.Response(200,json=body)
    governance=PaperclipGovernance('https://paperclip.example','test','run-1','issue-1',httpx.MockTransport(handle))
    governance.checkout();governance.handoff({'run_id':'lectio-1','status':'waiting_for_human'});governance.close()
    assert len(calls)==3

def test_paperclip_never_retries_checkout_conflict():
    attempts=[]
    def handle(request):
        if request.method=='GET':return httpx.Response(200,json={'id':'agent-1'})
        attempts.append(request);return httpx.Response(409,json={'error':'owned by another run'})
    governance=PaperclipGovernance('https://paperclip.example','test','run-1','issue-1',httpx.MockTransport(handle))
    with pytest.raises(RuntimeError,match='retry is forbidden'):governance.checkout()
    governance.close();assert len(attempts)==1

def test_finding_decisions_and_provenance(client,headers):
    import time
    course=client.post('/api/v1/courses',headers=headers,json={'code':'FINDING-REVIEWS','title':'Search algorithms'}).json()['id']
    base=f'/api/v1/courses/{course}'
    docs=[('outcomes.txt','syllabus',b'Students will be able to explain graph traversal.'),('lecture.txt','slides',b'Binary search halves a sorted array and has logarithmic complexity.'),('exam.txt','assignment',b'Question 1: Explain binary search.\nQuestion 2: Compare it to linear search.')]
    artifacts=[]
    for name,kind,text in docs:
        r=client.post(base+'/artifacts',headers=headers,files={'file':(name,text,'text/plain')},data={'artifact_type':kind});assert r.status_code==201,r.text;artifacts.append(r.json()['id'])
    client.post(base+'/extract-model',headers=headers)
    structure=client.get(base+'/structure',headers=headers).json()
    assert structure['assessments'][0]['source']['artifact_id']==artifacts[-1]
    run=client.post(base+'/run-audit',headers=headers);assert run.status_code==202,run.text
    run_id=run.json()['run_id']
    for _ in range(150):
        if client.get('/api/v1/runs/'+run_id,headers=headers).json()['status']!='running':break
        time.sleep(.1)
    reports=client.get(base+'/reports',headers=headers).json()
    report=next(r for r in reports if r['gap_count'])
    full=client.get('/api/v1/reports/'+report['id'],headers=headers).json()
    assert full['findings']['findings']['broker_review']['ranked_findings']
    gap=full['gaps'][0]
    r=client.post('/api/v1/reports/'+report['id']+'/findings/'+gap['id']+'/review',headers=headers,
        json={'decision':'rejected','rationale':'Independent study intentionally covers this topic.'})
    assert r.status_code==200,r.text
    assert r.json()['content_approved'] is False
    assert client.get('/api/v1/reports/'+report['id']+'/finding-decisions',headers=headers).json()[0]['rationale']
    assert client.delete(base+'/artifacts/'+artifacts[-1],headers=headers).status_code==204
    assert client.get(base+'/structure',headers=headers).json()['assessments']==[]
    assert client.get(base+'/matrix',headers=headers).json()['stale'] is True

def test_semantic_chunking_preserves_source_slices():
    from rag.chunking.semantic_chunker import SemanticChunker
    from rag.parsers.base_parser import ParsedBlock,ParsedDocument
    text='Binary search halves sorted arrays repeatedly. It needs logarithmic comparisons for large arrays. Quantum computing uses qubits and unitary gates to represent states.'
    class Encoder:
        def embed_texts(self,texts):return [[1.,0.],[1.,0.],[0.,1.]][:len(texts)]
    chunker=SemanticChunker(use_semantic_split=True);chunker._encoder=Encoder()
    chunks=chunker.chunk(ParsedDocument('x','txt','slides',[ParsedBlock(text,'paragraph',page_number=4)]),'a','c')
    assert len(chunks)==2 and all(c.text in text and c.page_number==4 for c in chunks)


def test_actual_sql_vectors_isolation_and_filters(client,headers):
    import asyncio
    from db.session import AsyncSessionLocal
    from db.models.artifact import Chunk,CourseArtifact
    from vector_db.sql_vector_store import SQLVectorStore
    courses=[];artifacts=[]
    for code,text in [('VECTOR-A',b'Binary search source.'),('VECTOR-B',b'Other private source.')]:
        course=client.post('/api/v1/courses',headers=headers,json={'code':code,'title':code}).json()['id'];courses.append(course)
        r=client.post(f'/api/v1/courses/{course}/artifacts',headers=headers,files={'file':('source.txt',text,'text/plain')},data={'artifact_type':'slides'})
        artifacts.append(r.json()['id'])
    async def assign():
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            chunks=list((await db.scalars(select(Chunk).where(Chunk.course_id.in_([uuid.UUID(c) for c in courses])))).all())
            for chunk in chunks:chunk.metadata_=dict(chunk.metadata_ or {},vector=[1.,0.,0.])
            await db.commit()
    asyncio.run(assign());store=SQLVectorStore()
    result=store.query(courses[0],[1.,0.,0.],10)
    assert len(result)==1 and result[0].text=='Binary search source.'
    assert store.query(courses[0],[1.,0.,0.],10,{'artifact_type':'assignment'})==[]
    assert client.delete(f'/api/v1/courses/{courses[0]}/artifacts/{artifacts[0]}',headers=headers).status_code==204
    assert store.query(courses[0],[1.,0.,0.])==[]
    assert len(store.query(courses[1],[1.,0.,0.]))==1

def test_apply_requires_human_approval_and_preserves_sources(client,headers):
    course=client.post('/api/v1/courses',headers=headers,json={'code':'APPLY-DRAFT','title':'Approved changes'}).json()['id'];base=f'/api/v1/courses/{course}'
    text=b'Binary search repeatedly halves a sorted array.'
    client.post(base+'/artifacts',headers=headers,files={'file':('source.txt',text,'text/plain')},data={'artifact_type':'slides'})
    module=client.post(base+'/modules',headers=headers,json={'title':'Search','sequence_number':1}).json()['id']
    item=client.post(base+'/generate',headers=headers,json={'content_type':'clo','purpose':'Explain binary search','alternatives':1}).json()[0]
    path='/api/v1/approvals/'+item['id']+'/apply'
    body={'module_id':module,'outcome_text':text.decode()}
    assert client.post(path,headers=headers,json=body).status_code==409
    assert client.post('/api/v1/approvals/'+item['id']+'/approve',headers=headers,json='Reviewed').status_code==200
    r=client.post(path,headers=headers,json=body);assert r.status_code==200,r.text
    assert r.json()['source_documents_modified'] is False
    assert client.get(base+'/modules/'+module+'/clos',headers=headers).json()[0]['text']==text.decode()
    assert client.post(path,headers=headers,json=body).status_code==409
    assert client.get(base+'/evidence',headers=headers).json()[0]['text']==text.decode()
