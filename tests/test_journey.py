import time

def test_full_journey(client,headers):
    before=client.get('/api/v1/dashboard',headers=headers).json()['documents_processed']
    r=client.post('/api/v1/courses',headers=headers,json={'code':'TEST101','title':'Algorithms','level':'undergraduate'})
    assert r.status_code==201,r.text
    course=r.json()['id'];base=f'/api/v1/courses/{course}'
    documents=[('outcomes.md','syllabus',b'# Outcomes\nStudents will be able to explain binary search and its complexity.\nStudents will be able to evaluate quantum error correction.'),
        ('lecture.txt','slides',b'Binary search repeatedly halves a sorted array. Binary search has logarithmic time complexity. Describe and compare binary search with linear search.'),
        ('exam.txt','assignment',b'Explain binary search and calculate the number of comparisons in a sorted array of 64 entries.')]
    for name,kind,data in documents:
        r=client.post(base+'/artifacts',headers=headers,files={'file':(name,data,'text/markdown' if name.endswith('md') else 'text/plain')},data={'artifact_type':kind})
        assert r.status_code==201,r.text
        aid=r.json()['id']
        status=client.get(base+f'/artifacts/{aid}/status',headers=headers).json()
        assert status['processing_status']=='done',status
    evidence=client.get(base+'/evidence',headers=headers).json()
    assert len(evidence)>=3
    r=client.post(base+'/extract-model',headers=headers)
    assert r.status_code==200,r.text
    assert r.json()['objectives_added']==2
    assert client.post(base+'/extract-model',headers=headers).json()['objectives_added']==0
    r=client.post(base+'/run-audit',headers=headers)
    assert r.status_code==202,r.text
    run=r.json()['run_id']
    for _ in range(150):
        status=client.get('/api/v1/runs/'+run,headers=headers).json()
        if status['status']!='running':break
        time.sleep(.1)
    assert status['status'] in ('completed','waiting_for_human','needs_review'),status
    reports=client.get(base+'/reports',headers=headers).json()
    assert len(reports)==4,reports
    assert client.get('/api/v1/runs/'+run+'/steps',headers=headers).json()
    assert client.get(base+'/matrix',headers=headers).json()['rows']
    r=client.post(base+'/generate',headers=headers,json={'content_type':'exercise','purpose':'Practice binary search complexity','alternatives':2})
    assert r.status_code==201,r.text
    items=r.json();assert len(items)==2
    item=items[0];assert 'DETERMINISTIC TEST' in item['content']
    assert item['citations'][0]['quote'] in [e['text'] for e in evidence]
    cid=item['id']
    r=client.post(f'/api/v1/approvals/{cid}/revise',headers=headers,json={'revision':'Revised exercise by lecturer.','comment':'Simplify'})
    assert r.status_code==200,r.text
    history=client.get(f'/api/v1/approvals/{cid}/history',headers=headers).json()
    assert history['original']==item['content']
    assert history['status']=='revised'
    assert client.post(f'/api/v1/approvals/{cid}/approve',headers=headers,json='Reviewed').status_code==200
    export=client.get(base+'/export',headers=headers)
    assert export.status_code==200,export.text
    accepted=next(i for i in export.json()['suggestions'] if i['id']==cid)
    assert accepted['accepted_content']=='Revised exercise by lecturer.'
    assert len(accepted['history'])==2
    stats=client.get('/api/v1/dashboard',headers=headers).json()
    assert stats['documents_processed']==before+3 and stats['approved']>=1

def test_reviewed_extraction_and_clusters(client,headers):
    course=client.post('/api/v1/courses',headers=headers,json={'code':'MODEL','title':'Model review'}).json()['id']
    base=f'/api/v1/courses/{course}'
    r=client.post(base+'/artifacts',headers=headers,files={'file':('outcomes.md',b'Students will be able to explain sorting algorithms.','text/markdown')},data={'artifact_type':'syllabus'})
    assert r.status_code==201
    assert client.post(base+'/extract-model',headers=headers).json()['objectives_added']==1
    module=client.get(base+'/modules',headers=headers).json()[0]
    objective=client.get(base+'/modules/'+module['id']+'/clos',headers=headers).json()[0]
    r=client.patch(base+'/objectives/'+objective['id'],headers=headers,json={'text':'Compare sorting algorithms and justify their complexity.','bloom_level':'analyse'})
    assert r.status_code==200,r.text
    assert client.post(base+'/extract-model',headers=headers).json()['objectives_added']==0
    clusters=client.post(base+'/cluster-topics',headers=headers)
    assert clusters.status_code==200,clusters.text
    assert clusters.json()['groups'][0]['method']=='local-test lexical hash cosine'
    assert clusters.json()['groups'][0]['chunk_ids']
