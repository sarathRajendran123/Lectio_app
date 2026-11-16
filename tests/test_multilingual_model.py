"""German/English outcome extraction, derivation when none are stated, no bare 'unknown', frontend client speed-ups."""
import importlib
import sys
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'datasets'


def _upload(client, headers, base, folder, name, kind, mime='text/plain'):
    r = client.post(base + '/artifacts', headers=headers, data={'artifact_type': kind},
                    files={'file': (name, (DATA / folder / name).read_bytes(), mime)})
    assert r.status_code == 201, r.text
    assert client.get(base + f"/artifacts/{r.json()['id']}/status", headers=headers).json()['processing_status'] == 'done'


def _objectives(client, headers, base):
    return [o for m in client.get(base + '/modules', headers=headers).json()
            for o in client.get(base + f"/modules/{m['id']}/clos", headers=headers).json()]


def test_german_outcomes_and_schedule_are_extracted(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': 'DE-EXT', 'title': 'Algorithmen'}).json()['id']
    base = f'/api/v1/courses/{course}'
    _upload(client, headers, base, 'de_algorithmen', 'modulhandbuch.md', 'syllabus', 'text/markdown')
    objectives = _objectives(client, headers, base)
    assert len(objectives) == 3 and all(o['text'].startswith('Die Studierenden') for o in objectives)
    assert {o['bloom_level'] for o in objectives} >= {'understand', 'apply'}   # German verbs are classified
    weeks = [w for m in client.get(base + '/structure', headers=headers).json()['modules'] for w in m.get('planned_weeks', [])]
    assert len(weeks) == 4   # "Woche N:" lines


def test_outcomes_are_derived_when_none_are_stated_and_no_check_is_unknown(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': 'EN-DER', 'title': 'Algorithms'}).json()['id']
    base = f'/api/v1/courses/{course}'
    for name, kind, mime in [('syllabus.md', 'syllabus', 'text/markdown'), ('lecture_slides.txt', 'slides', 'text/plain'),
                             ('lecture_transcript.vtt', 'transcript', 'text/vtt'), ('exam.txt', 'exam', 'text/plain')]:
        _upload(client, headers, base, 'en_algorithms', name, kind, mime)
    assert _objectives(client, headers, base) == []   # nothing is stated in these files
    run = client.post(base + '/run-audit', headers=headers).json()['run_id']
    for _ in range(200):
        if client.get('/api/v1/runs/' + run, headers=headers).json()['status'] != 'running':
            break
        time.sleep(.1)
    derived = _objectives(client, headers, base)
    assert derived and all(o['is_generated'] and o['code'].startswith('DER-') for o in derived)
    assert not any('schedule' in o['text'].lower() for o in derived)   # administrative text is not an outcome
    reports = client.get(base + '/reports', headers=headers).json()
    assert len(reports) == 4
    for r in reports:   # either scored, or a concrete reason is given
        assert r['status'] not in ('needs_review', 'failed') or r['reason']
    assert any(r['status'] not in ('needs_review', 'failed') for r in reports)


def test_derived_outcomes_never_replace_stated_ones(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': 'DE-KEEP', 'title': 'Algorithmen'}).json()['id']
    base = f'/api/v1/courses/{course}'
    _upload(client, headers, base, 'de_algorithmen', 'modulhandbuch.md', 'syllabus', 'text/markdown')
    _upload(client, headers, base, 'de_algorithmen', 'vorlesung.txt', 'slides')
    client.post(base + '/run-audit', headers=headers)
    assert not any(o['code'].startswith('DER-') for o in _objectives(client, headers, base))


def test_german_detection_and_cluster_ranking():
    from services.auto_derive import is_german, rank_clusters
    assert is_german('Die binäre Suche halbiert den Suchraum und ist logarithmisch.')
    assert not is_german('Binary search halves the search space of a sorted array.')
    info = {'a': {'artifact': 1, 'type': 'slides', 'order': 0}, 'b': {'artifact': 1, 'type': 'slides', 'order': 1},
            'c': {'artifact': 2, 'type': 'transcript', 'order': 2}, 'd': {'artifact': 3, 'type': 'slides', 'order': 3}}
    ranked = rank_clusters([{'label': 'single', 'chunk_ids': ['d']}, {'label': 'spread', 'chunk_ids': ['a', 'b', 'c']}], info)
    assert [g['label'] for g in ranked] == ['spread', 'single']


def test_frontend_client_avoids_slow_localhost_and_caches_reads(monkeypatch):
    monkeypatch.setenv('BACKEND_URL', 'http://localhost:8000')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frontend'))
    import api_client.lectio_client as lc
    lc = importlib.reload(lc)
    assert lc.BACKEND_URL == 'http://127.0.0.1:8000'
    import httpx
    hits = []

    def fake_get(url, **kw):
        hits.append(url)
        return httpx.Response(200, json={}, request=httpx.Request('GET', url))
    monkeypatch.setattr(lc._pool, 'get', fake_get)
    monkeypatch.setattr(lc._pool, 'post', lambda url, **kw: httpx.Response(200, json={}, request=httpx.Request('POST', url)))
    with lc._session(5) as c:
        c.get('http://x/courses'); c.get('http://x/courses')
        c.get('http://x/runs/1'); c.get('http://x/runs/1')   # progress polling is never cached
        assert hits == ['http://x/courses', 'http://x/runs/1', 'http://x/runs/1']
        c.post('http://x/courses'); c.get('http://x/courses')   # a write invalidates the cache
    assert hits[-1] == 'http://x/courses' and len(hits) == 4


def test_headings_stay_with_the_text_they_introduce():
    from rag.chunking.semantic_chunker import SemanticChunker
    from rag.parsers.base_parser import ParsedBlock, ParsedDocument
    blocks = [ParsedBlock('# CS201 Module Manual', 'heading'), ParsedBlock('This module introduces algorithms.', 'paragraph'),
              ParsedBlock('## Weekly schedule', 'heading'), ParsedBlock('Week 1: Sorting\nWeek 2: Binary search', 'paragraph'),
              ParsedBlock('## Appendix', 'heading')]
    texts = [c.text for c in SemanticChunker().chunk(ParsedDocument('x', 'md', 'syllabus', blocks), 'a', 'c')]
    assert texts == ['# CS201 Module Manual\nThis module introduces algorithms.', '## Weekly schedule\nWeek 1: Sorting\nWeek 2: Binary search', '## Appendix']
