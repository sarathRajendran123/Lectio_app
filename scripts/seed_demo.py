"""Explicit demo fixture; never runs automatically in normal application startup."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1]
load_dotenv(root/'.env');sys.path.insert(0,str(root/'frontend'))
from api_client.lectio_client import LectioClient
client=LectioClient()
login=client.login(os.environ['ADMIN_EMAIL'],os.environ['ADMIN_PASSWORD'])
client=LectioClient(login['access_token'])
if any(c['code']=='DEMO-ALG' for c in client.list_courses()['courses']):raise SystemExit('Demo course already exists.')
course=client.create_course({'code':'DEMO-ALG','title':'Algorithms · Explicit demonstration dataset','level':'undergraduate','description':'Synthetic teaching fixture, not university evaluation data.'})
cid=course['id']
documents=[('syllabus.md','syllabus', '# Learning outcomes\nStudents will be able to explain binary search and its logarithmic complexity.\nStudents will be able to evaluate graph traversal algorithms.'),
    ('lecture-notes.md','slides','# Binary search\nBinary search halves a sorted array at each step. Its time complexity is logarithmic. Compare binary search with linear search.\n# Sorting\nInsertion sort builds a sorted prefix of the list, inserting one element at a time.'),
    ('assignment.txt','assignment','Explain binary search. Calculate the comparisons needed to search a sorted array of 64 entries. Compare its complexity with linear search.'),
    ('schedule.md','other','# Planned delivery\nWeek 1: Binary search, worked examples and independent practice.\nWeek 2: Graph traversal workshop.\nThis is a teaching plan, not evidence that sessions occurred.')]
for name,kind,text in documents:client.upload_artifact(cid,text.encode(),name,kind)
module=client.create_module(cid,{'title':'Planned teaching','sequence_number':1})
for number,title in [(1,'Binary search'),(2,'Graph traversal')]:
    week=client.create_week(cid,module['id'],{'week_number':number,'title':title})
    client.create_topic(cid,module['id'],week['id'],{'title':title,'sequence_order':1})
print('Created explicit demo course. Open Course workbench, inspect processing, then run an audit.')
