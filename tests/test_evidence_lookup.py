import asyncio
import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import insert

from db.models.artifact import Chunk
from db.session import AsyncSessionLocal


def test_workbench_collects_only_valid_chunk_references():
    path = Path(__file__).resolve().parents[1] / 'frontend' / 'utils' / 'evidence_refs.py'
    spec = importlib.util.spec_from_file_location('evidence_refs_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first, second = str(uuid4()), str(uuid4())
    report = {'id': str(uuid4()), 'findings': {'gaps': [{'evidence_chunk_ids': [first, 'invalid']}],
              'findings': {'prepared_transcript_comparison': [{'prepared_chunk_ids': [second]}]}}}
    assert module.cited_chunk_ids(report) == {first, second}


def test_lookup_finds_cited_chunk_beyond_preview_and_enforces_course_scope(client, headers):
    def make_course(code):
        course = client.post('/api/v1/courses', headers=headers,
                             json={'code': code, 'title': 'Source lookup'}).json()['id']
        artifact = client.post(
            f'/api/v1/courses/{course}/artifacts', headers=headers,
            files={'file': ('notes.txt', b'Course content for the source lookup test.', 'text/plain')},
            data={'artifact_type': 'slides'},
        ).json()['id']
        return course, artifact

    course, artifact = make_course('LOOKUP-A')
    other_course, other_artifact = make_course('LOOKUP-B')
    late_id, other_id = uuid4(), uuid4()

    async def insert_chunks():
        async with AsyncSessionLocal() as db:
            chunks = [{'id': uuid4(), 'course_id': UUID(course), 'artifact_id': UUID(artifact),
                       'text': 'Preview chunk', 'chunk_index': i} for i in range(2001)]
            chunks.append({'id': late_id, 'course_id': UUID(course), 'artifact_id': UUID(artifact),
                           'text': 'Referenced late chunk', 'chunk_index': 3000})
            chunks.append({'id': other_id, 'course_id': UUID(other_course), 'artifact_id': UUID(other_artifact),
                           'text': 'Other course', 'chunk_index': 0})
            await db.execute(insert(Chunk), chunks)
            await db.commit()

    asyncio.run(insert_chunks())
    base = f'/api/v1/courses/{course}/evidence'
    preview = client.get(base, headers=headers).json()
    assert len(preview) == 2000
    assert str(late_id) not in {item['id'] for item in preview}
    response = client.post(base + '/lookup', headers=headers,
                           json={'chunk_ids': [str(late_id), str(other_id)]})
    assert response.status_code == 200
    assert [(item['id'], item['text']) for item in response.json()] == [(str(late_id), 'Referenced late chunk')]
    assert client.post(base + '/lookup', headers=headers,
                       json={'chunk_ids': [str(late_id)] * 201}).status_code == 422
    assert client.post(base + '/lookup', json={'chunk_ids': [str(late_id)]}).status_code == 401
