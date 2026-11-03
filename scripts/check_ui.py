"""Smoke test every Streamlit page against a locally running API."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
sys.path.insert(0,str(ROOT/'frontend'))
from api_client.lectio_client import LectioClient
from streamlit.testing.v1 import AppTest
client=LectioClient()
tokens=client.login(os.environ['ADMIN_EMAIL'],os.environ['ADMIN_PASSWORD'])
client=LectioClient(tokens['access_token'])
user=client.get_me()
# Explicit smoke-test fixture, only in this opt-in verification script.
courses=client.list_courses()['courses']
course=next((c for c in courses if c['code']=='UI-SMOKE'),None)
if not course:
    course=client.create_course({'code':'UI-SMOKE','title':'Algorithms · UI test fixture','level':'undergraduate'})
    client.upload_artifact(course['id'],b'Students will be able to explain binary search complexity.','objectives.txt','syllabus')
    client.upload_artifact(course['id'],b'Binary search halves a sorted list on each step and has logarithmic time complexity.','lecture.txt','slides')
    client.upload_artifact(course['id'],b'Explain binary search complexity for a sorted list with 64 elements.','exam.txt','assignment')
    import time
    for _ in range(60):
        docs=client.list_artifacts(course['id'])['artifacts']
        if all(d['processing_status'] in ('done','error') for d in docs):break
        time.sleep(.1)
    result=client.run_audit(course['id'])
    for _ in range(100):
        if client.get_run_status(result['run_id'])['status']!='running':break
        time.sleep(.1)
    client.workbench('courses/'+course['id']+'/generate','POST',{'purpose':'Practice binary search complexity','content_type':'exercise','alternatives':2})

app=AppTest.from_file(str(ROOT/'frontend/app.py'),default_timeout=30)
app.session_state['access_token']=tokens['access_token']
app.session_state['refresh_token']=tokens['refresh_token']
app.session_state['user']=user
app.run()
assert not app.exception,[e.message for e in app.exception]
for page in list(app.sidebar.radio[0].options):
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception,(page,[e.message for e in app.exception])
    print('PASS',page)
