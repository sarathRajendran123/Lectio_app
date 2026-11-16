"""Phase 2, item 9: approval transitions, concurrency, role matrix, upload and model-output fuzzing.

No test here calls a real model or a real network. The OpenRouter client is exercised by
monkeypatching httpx.post; everything else runs against the local_test SQLite database used by
the rest of the suite.
"""
import io
import threading
import zipfile
from types import SimpleNamespace

import httpx
import pytest

from rag.chunking.chunk_models import RetrievedChunk
from rag.generation.draft_schema import parse_draft

# ── helpers ──────────────────────────────────────────────────────────────────

def _chunks():
    return [
        RetrievedChunk('c1', 'Merge sort splits the list and merges sorted halves.', .9,
                        'a1', 'slides', 'course', 1, None, None, None),
        RetrievedChunk('c2', 'Quicksort partitions around a pivot element.', .8,
                        'a1', 'slides', 'course', 2, None, None, None),
    ]

VALID_DRAFT = '''{"title":"Sorting outcomes","sections":[{"heading":"Merge sort","text":"Explain merge sort.",
"supports":[{"source":1,"quote":"Merge sort splits the list and merges sorted halves."}],
"interpretation":"source_summary"}],"limitations":[],"bloom_level":"understand"}'''


# ── A. model-output fuzzing (draft_schema.parse_draft) ──────────────────────

def test_parse_draft_accepts_fenced_json():
    rendered, citations, draft = parse_draft("```json\n" + VALID_DRAFT + "\n```", _chunks())
    assert citations[0]['quote'] == _chunks()[0].text and '[SOURCE_1]' in rendered
    assert draft.title == 'Sorting outcomes'

@pytest.mark.parametrize("broken", [
    '{not json at all',
    '{"title":"x"}',  # missing required fields
    VALID_DRAFT.replace('"source_summary"', '"source_summary","extra":"nope"'),  # extra='forbid'
    VALID_DRAFT.replace('Merge sort splits the list and merges sorted halves.', 'Something never said'),  # non-verbatim quote
    VALID_DRAFT.replace('"source":1', '"source":99'),  # out-of-range source
    VALID_DRAFT.replace('"heading":"Merge sort"', '"heading":"' + 'x' * 5000 + '"'),  # over max_length
])
def test_parse_draft_rejects_malformed_or_fabricated_output(broken):
    with pytest.raises(Exception):
        parse_draft(broken, _chunks())

def test_parse_draft_stores_html_as_literal_text_not_markup():
    injected = VALID_DRAFT.replace('Explain merge sort.', 'Explain merge sort. <script>alert(1)</script>')
    rendered, _, draft = parse_draft(injected, _chunks())
    assert '<script>alert(1)</script>' in rendered
    assert draft.sections[0].text.count('<script>') == 1  # passed through unexecuted, not stripped or duplicated


# ── B. LLM client resilience (openrouter.py), no network ────────────────────

class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('error', request=None, response=self)

def _llm(monkeypatch, fallback='backup/model', cache=False):
    from config import settings
    from llm import openrouter
    monkeypatch.setattr(settings, 'openrouter_api_key', 'test-key-not-real', raising=False)
    monkeypatch.setattr(settings, 'openrouter_fallback_model', fallback, raising=False)
    monkeypatch.setattr(settings, 'llm_retry_wait_seconds', 0, raising=False)
    monkeypatch.setattr(settings, 'llm_cache_enabled', cache, raising=False)
    return openrouter.OpenRouterChat(model='primary/model', prompt_version='test')

def _messages():
    from langchain_core.messages import HumanMessage
    return [HumanMessage(content='hello')]

def test_llm_falls_back_to_second_model_after_transient_error(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, 'artifact_storage_path', str(tmp_path), raising=False)
    llm = _llm(monkeypatch)
    calls = []
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json['model'])
        if json['model'] == 'primary/model':
            return FakeResponse(503, text='service unavailable')
        return FakeResponse(200, {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}], 'usage': {'total_tokens': 5}})
    monkeypatch.setattr(httpx, 'post', fake_post)
    result = llm.invoke(_messages())
    assert result.content == 'ok'
    assert calls == ['primary/model', 'backup/model']

def test_llm_fatal_quota_error_does_not_try_fallback(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, 'artifact_storage_path', str(tmp_path), raising=False)
    llm = _llm(monkeypatch)
    calls = []
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json['model'])
        return FakeResponse(429, text='free-models-per-day limit reached')
    monkeypatch.setattr(httpx, 'post', fake_post)
    from llm.openrouter import LLMError
    with pytest.raises(LLMError):
        llm.invoke(_messages())
    assert calls == ['primary/model']  # fatal: no fallback attempted

def test_llm_non_fallback_http_status_raises_without_retry(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, 'artifact_storage_path', str(tmp_path), raising=False)
    llm = _llm(monkeypatch)
    calls = []
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json['model'])
        return FakeResponse(401, text='unauthorized')
    monkeypatch.setattr(httpx, 'post', fake_post)
    from llm.openrouter import LLMError
    with pytest.raises(LLMError):
        llm.invoke(_messages())
    assert calls == ['primary/model']

def test_llm_cut_off_output_raises_even_after_both_models(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, 'artifact_storage_path', str(tmp_path), raising=False)
    llm = _llm(monkeypatch)
    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(200, {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}], 'usage': {}})
    monkeypatch.setattr(httpx, 'post', fake_post)
    from llm.openrouter import LLMError
    with pytest.raises(LLMError, match='cut off'):
        llm.invoke(_messages())

def test_llm_validation_failure_is_not_cached_and_is_retried_on_rerun(monkeypatch, tmp_path):
    """Re-run stability: a rejected draft must not poison the cache for the next attempt."""
    from config import settings
    monkeypatch.setattr(settings, 'artifact_storage_path', str(tmp_path), raising=False)
    llm = _llm(monkeypatch, cache=True)
    calls = {'n': 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls['n'] += 1
        return FakeResponse(200, {'choices': [{'message': {'content': 'bad output'}, 'finish_reason': 'stop'}], 'usage': {'total_tokens': 3}})
    monkeypatch.setattr(httpx, 'post', fake_post)
    def rejecting_validate(_content):
        raise ValueError('schema violation')
    with pytest.raises(ValueError):
        llm.invoke(_messages(), validate=rejecting_validate)
    with pytest.raises(ValueError):
        llm.invoke(_messages(), validate=rejecting_validate)
    assert calls['n'] == 2  # second call was not served from cache

def test_llm_identical_validated_request_is_served_from_cache(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, 'artifact_storage_path', str(tmp_path), raising=False)
    llm = _llm(monkeypatch, cache=True)
    calls = {'n': 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls['n'] += 1
        return FakeResponse(200, {'choices': [{'message': {'content': 'good output'}, 'finish_reason': 'stop'}], 'usage': {'total_tokens': 3}})
    monkeypatch.setattr(httpx, 'post', fake_post)
    first = llm.invoke(_messages(), validate=lambda c: None)
    second = llm.invoke(_messages(), validate=lambda c: None)
    assert first.content == second.content == 'good output'
    assert calls['n'] == 1  # second call reused the cached, validated result


# ── C. Upload fuzzing (zip bombs, unsafe archives) ───────────────────────────

def _zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()

def _office_shell(extra_entries=()):
    entries = [('[Content_Types].xml', '<Types/>'), ('word/document.xml', '<document/>')]
    entries += list(extra_entries)
    return entries

def test_upload_rejects_many_entries():
    from services.upload_service import UploadService, UploadError
    entries = _office_shell([(f'word/media/img{i}.png', 'x') for i in range(5000)])
    data = _zip_bytes(entries)
    with pytest.raises(UploadError):
        UploadService()._validate_office(data, 'docx')

def test_upload_rejects_path_traversal_entry():
    from services.upload_service import UploadService, UploadError
    entries = _office_shell([('../../evil.txt', 'x')])
    data = _zip_bytes(entries)
    with pytest.raises(UploadError):
        UploadService()._validate_office(data, 'docx')

def test_upload_rejects_vba_and_embeddings():
    from services.upload_service import UploadService, UploadError
    for bad in [('word/vbaProject.bin', 'x'), ('word/embeddings/oleObject1.bin', 'x')]:
        with pytest.raises(UploadError):
            UploadService()._validate_office(_zip_bytes(_office_shell([bad])), 'docx')

def test_upload_rejects_high_compression_ratio_zip_bomb():
    from services.upload_service import UploadService, UploadError
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<document/>')
        z.writestr('word/media/bomb.bin', b'0' * (5 * 1024 * 1024))
    with pytest.raises(UploadError):
        UploadService()._validate_office(buf.getvalue(), 'docx')

def test_upload_rejects_corrupt_zip():
    from services.upload_service import UploadService, UploadError
    good = _zip_bytes(_office_shell())
    corrupted = good[:-20] + b'\x00' * 20
    with pytest.raises(UploadError):
        UploadService()._validate_office(corrupted, 'docx')


# ── D. Role matrix (unit-level, no DB) ───────────────────────────────────────

def test_role_hierarchy_ordering():
    from auth.rbac import CurrentUser
    from types import SimpleNamespace as NS
    def has_min_role(roles, min_role):
        return CurrentUser.has_min_role(NS(roles=roles), min_role)
    assert has_min_role(['lecturer'], 'lecturer') is True
    assert has_min_role(['lecturer'], 'admin') is False
    assert has_min_role(['admin'], 'lecturer') is True
    assert has_min_role(['dept_head'], 'coordinator') is True
    assert has_min_role([], 'lecturer') is False
    assert has_min_role(['unknown_role'], 'lecturer') is False

def test_admin_endpoints_forbidden_to_lecturer(client, headers):
    lecturer = _new_lecturer(client, headers, 'role-matrix-lecturer')
    for method, path in [('GET', '/api/v1/admin/users'), ('GET', '/api/v1/admin/system-stats'),
                          ('GET', '/api/v1/admin/audit-logs')]:
        r = client.request(method, path, headers=lecturer)
        assert r.status_code == 403, (path, r.text)

def test_admin_cannot_deactivate_own_account(client, headers):
    me = client.get('/api/v1/auth/me', headers=headers)
    if me.status_code != 200:
        pytest.skip('no /auth/me endpoint to resolve the admin id')
    r = client.delete('/api/v1/admin/users/' + me.json()['id'], headers=headers)
    assert r.status_code == 400


def _new_lecturer(client, headers, name):
    response = client.post('/api/v1/admin/users', headers=headers,
        json={'email': name + '@example.org', 'password': 'StrongPassword!123', 'full_name': name,
              'role': 'lecturer', 'role_name': 'lecturer'})
    assert response.status_code == 201, response.text
    response = client.post('/api/v1/auth/login', json={'email': name + '@example.org', 'password': 'StrongPassword!123'})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


# ── E. Approval state transitions ────────────────────────────────────────────

def _course_with_draft(client, headers, code):
    course = client.post('/api/v1/courses', headers=headers, json={'code': code, 'title': 'Transitions'}).json()['id']
    base = f'/api/v1/courses/{course}'
    client.post(base + '/artifacts', headers=headers,
        files={'file': ('lecture.txt', b'Sorting algorithms arrange items. Merge sort splits recursively.', 'text/plain')},
        data={'artifact_type': 'slides'})
    item = client.post(base + '/generate', headers=headers,
        json={'purpose': 'Practice sorting algorithms thoroughly', 'content_type': 'exercise', 'alternatives': 1}).json()[0]
    return course, item['id']

def test_reject_then_approve_overwrites_status(client, headers):
    _, content_id = _course_with_draft(client, headers, 'TRANS1')
    r1 = client.post(f'/api/v1/approvals/{content_id}/reject', headers=headers)
    assert r1.status_code == 200 and r1.json()['decision'] == 'rejected'
    r2 = client.post(f'/api/v1/approvals/{content_id}/approve', headers=headers)
    assert r2.status_code == 200 and r2.json()['decision'] == 'approved'
    history = client.get(f'/api/v1/approvals/{content_id}/history', headers=headers).json()
    assert [d['decision'] for d in history['decisions']] == ['rejected', 'approved']
    assert history['status'] == 'approved'

def test_revise_without_text_is_rejected(client, headers):
    _, content_id = _course_with_draft(client, headers, 'TRANS2')
    r = client.post(f'/api/v1/approvals/{content_id}/revise', headers=headers, json={'comment': 'needs work'})
    assert r.status_code == 422

def test_apply_requires_approved_status(client, headers):
    _, content_id = _course_with_draft(client, headers, 'TRANS3')
    client.post(f'/api/v1/approvals/{content_id}/reject', headers=headers)
    r = client.post(f'/api/v1/approvals/{content_id}/apply', headers=headers, json={})
    assert r.status_code == 409

def test_apply_cannot_be_repeated(client, headers):
    course, content_id = _course_with_draft(client, headers, 'TRANS4')
    client.post(f'/api/v1/approvals/{content_id}/approve', headers=headers)
    r1 = client.post(f'/api/v1/approvals/{content_id}/apply', headers=headers, json={})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f'/api/v1/approvals/{content_id}/apply', headers=headers, json={})
    assert r2.status_code == 409

def test_submit_approval_rejects_unknown_decision():
    import asyncio
    from services.workflow_service import workflow_service
    with pytest.raises(ValueError):
        asyncio.run(workflow_service.submit_approval('x', 'y', 'maybe', None, None, None))


# ── F. Concurrency ────────────────────────────────────────────────────────────

def test_concurrent_audits_on_same_course_are_serialised(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': 'CONC1', 'title': 'Concurrency'}).json()['id']
    client.post(f'/api/v1/courses/{course}/artifacts', headers=headers,
        files={'file': ('notes.txt', b'Sorting algorithms arrange items in a sequence for study.', 'text/plain')},
        data={'artifact_type': 'slides'})
    results = []
    def start():
        results.append(client.post(f'/api/v1/courses/{course}/run-audit', headers=headers).status_code)
    threads = [threading.Thread(target=start) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count(202) == 1, results
    assert all(code in (202, 409) for code in results), results

def test_concurrent_apply_on_same_draft_applies_once(client, headers):
    course, content_id = _course_with_draft(client, headers, 'CONC2')
    client.post(f'/api/v1/approvals/{content_id}/approve', headers=headers)
    results = []
    def apply():
        results.append(client.post(f'/api/v1/approvals/{content_id}/apply', headers=headers, json={}).status_code)
    threads = [threading.Thread(target=apply) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count(200) == 1, results
    assert all(code in (200, 409) for code in results), results
