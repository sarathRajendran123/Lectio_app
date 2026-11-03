import io
import uuid
import zipfile
from pathlib import Path
import pytest
from services.upload_service import UploadService,UploadError
from rag.generation.grounded_generator import CitationBuilder,GroundedGenerator
from rag.chunking.chunk_models import RetrievedChunk
from rag.chunking.semantic_chunker import SemanticChunker
from rag.parsers.base_parser import ParsedDocument,ParsedBlock

def test_untrusted_office_and_paths():
    service=UploadService()
    with pytest.raises(UploadError):service._validate_magic_bytes(b'not pdf','pdf')
    for ext in ('docx','pptx'):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:archive.writestr('random.txt','not a document')
        with pytest.raises(UploadError):service._validate_office(data.getvalue(),ext)
    with pytest.raises(ValueError):service._destination('../../escape','file.txt')
    with pytest.raises(UploadError):service.delete('/tmp/not-a-lectio-file')

def test_chunk_locations_and_hard_limits():
    doc=ParsedDocument('x','pdf','slides',[ParsedBlock('a'*5000,'paragraph',page_number=1),ParsedBlock('A short objective.','paragraph',page_number=2)])
    chunks=SemanticChunker().chunk(doc,str(uuid.uuid4()),str(uuid.uuid4()))
    assert all(len(c.text)<=1800 for c in chunks)
    assert chunks[-1].page_number==2
    assert all(c.text in doc.blocks[c.page_number-1].text for c in chunks)

def test_citation_rejection():
    chunk=RetrievedChunk('id','actual text',.8,'artifact','slides','course',2,None,None,None)
    with pytest.raises(ValueError):CitationBuilder.resolve('Invented [SOURCE_8]',[chunk])
    with pytest.raises(ValueError):CitationBuilder.resolve('No source',[chunk])
    with pytest.raises(ValueError):GroundedGenerator().generate('invent something',[])
    _,refs=CitationBuilder.resolve('Actual [SOURCE_1]',[chunk])
    assert refs[0]['quote']=='actual text' and refs[0]['page_number']==2

def new_lecturer(client,headers,name):
    response=client.post('/api/v1/admin/users',headers=headers,json={'email':name+'@example.org','password':'StrongPassword!123','full_name':name,'role':'lecturer','role_name':'lecturer'})
    assert response.status_code==201,response.text
    response=client.post('/api/v1/auth/login',json={'email':name+'@example.org','password':'StrongPassword!123'})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['access_token']}

def test_course_and_child_isolation(client,headers):
    a=new_lecturer(client,headers,'lecturer-a');b=new_lecturer(client,headers,'lecturer-b')
    ca=client.post('/api/v1/courses',headers=a,json={'code':'PRIVATEA','title':'Private A'})
    cb=client.post('/api/v1/courses',headers=b,json={'code':'PRIVATEB','title':'Private B'})
    assert ca.status_code==201,ca.text
    assert cb.status_code==201,cb.text
    aid=ca.json()['id'];bid=cb.json()['id']
    mod=client.post(f'/api/v1/courses/{aid}/modules',headers=a,json={'title':'Private module','sequence_number':1}).json()['id']
    for path in [f'courses/{aid}/reports',f'courses/{aid}/evidence',f'courses/{aid}/matrix',f'courses/{aid}/export']:
        assert client.get('/api/v1/'+path,headers=b).status_code==403,path
    assert client.get(f'/api/v1/courses/{bid}/modules/{mod}/clos',headers=b).status_code==404
    r=client.post(f'/api/v1/courses/{bid}/modules/{mod}/weeks',headers=b,json={'week_number':1})
    assert r.status_code==404,r.text
    assert all(c['id']!=aid for c in client.get('/api/v1/courses',headers=b).json()['courses'])

def test_upload_errors_and_duplicate_cleanup(client,headers):
    course=client.post('/api/v1/courses',headers=headers,json={'code':'FILES','title':'File validation'}).json()['id']
    path=f'/api/v1/courses/{course}/artifacts'
    r=client.post(path,headers=headers,files={'file':('bad.pdf',b'bad','application/pdf')},data={'artifact_type':'slides'})
    assert r.status_code==422
    data=b'Useful lecture notes about algorithms and data structures.'
    r=client.post(path,headers=headers,files={'file':('notes.txt',data,'text/plain')},data={'artifact_type':'slides'})
    assert r.status_code==201
    folder=UploadService().storage_root/course
    count=len(list(folder.iterdir()))
    r=client.post(path,headers=headers,files={'file':('notes.txt',data,'text/plain')},data={'artifact_type':'slides'})
    assert r.status_code==409
    assert len(list(folder.iterdir()))==count

def test_failed_login_counter_and_logout(client,headers):
    auth=new_lecturer(client,headers,'lockout-user')
    for _ in range(5):
        assert client.post('/api/v1/auth/login',json={'email':'lockout-user@example.org','password':'bad'}).status_code==401
    assert client.post('/api/v1/auth/login',json={'email':'lockout-user@example.org','password':'StrongPassword!123'}).status_code==401
    login=client.post('/api/v1/auth/login',json={'email':'admin@example.org','password':'LectioTestPassword!42'}).json()
    r=client.post('/api/v1/auth/logout',headers={'Authorization':'Bearer '+login['access_token']},json={'refresh_token':login['refresh_token']})
    assert r.status_code==204,r.text
    assert client.post('/api/v1/auth/refresh',json={'refresh_token':login['refresh_token']}).status_code==401

def test_workflow_object_isolation_and_deleted_sources(client,headers):
    import time
    a=new_lecturer(client,headers,'audit-owner');b=new_lecturer(client,headers,'audit-outsider')
    course=client.post('/api/v1/courses',headers=a,json={'code':'AUDIT-PRIVATE','title':'Sorting algorithms'}).json()['id']
    base=f'/api/v1/courses/{course}'
    artifact=client.post(base+'/artifacts',headers=a,files={'file':('lecture.txt',b'Sorting algorithms arrange items in a sequence. Compare merge sort with insertion sort.','text/plain')},data={'artifact_type':'slides'}).json()['id']
    item=client.post(base+'/generate',headers=a,json={'purpose':'Practice sorting algorithms','content_type':'exercise','alternatives':1}).json()[0]
    for suffix in ('','/history'):
        assert client.get('/api/v1/approvals/'+item['id']+suffix,headers=b).status_code==403
    for action in ('approve','reject'):
        assert client.post('/api/v1/approvals/'+item['id']+'/'+action,headers=b,json='no').status_code==403
    assert client.get('/api/v1/approvals',headers=b).json()==[]
    run=client.post(base+'/run-audit',headers=a).json()['run_id']
    assert client.get('/api/v1/runs/'+run,headers=b).status_code==403
    assert client.get('/api/v1/runs/'+run+'/steps',headers=b).status_code==403
    for _ in range(100):
        if client.get('/api/v1/runs/'+run,headers=a).json()['status']!='running':break
        time.sleep(.1)
    report=client.get(base+'/reports',headers=a).json()[0]
    assert client.get('/api/v1/reports/'+report['id'],headers=b).status_code==403
    assert client.delete(base+'/artifacts/'+artifact,headers=a).status_code==204
    assert client.get(base+'/evidence',headers=a).json()==[]
    assert client.post(base+'/generate',headers=a,json={'purpose':'Practice sorting algorithms','content_type':'exercise'}).status_code==422
