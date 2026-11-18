"""A check that cannot be scored names its real reason, and the report page reads the findings where they are stored."""
import ast
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

DATA = Path(__file__).resolve().parents[1] / 'datasets'
FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'


def _frontend_functions(relative, *names):
    """Selected top-level functions and constants of a page, without importing Streamlit or the page's own imports."""
    tree = ast.parse((FRONTEND / relative).read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in names for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), ns)
    return ns


def test_a_course_without_an_exam_gets_the_agents_reason_not_the_generic_text(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': f'DE-NOEX-{uuid.uuid4().hex[:6]}', 'title': 'Algorithmen'}).json()['id']
    base = f'/api/v1/courses/{course}'
    for name, kind, mime in (('modulhandbuch.md', 'syllabus', 'text/markdown'), ('vorlesung.txt', 'slides', 'text/plain')):
        r = client.post(base + '/artifacts', headers=headers, data={'artifact_type': kind}, files={'file': (name, (DATA / 'de_algorithmen' / name).read_bytes(), mime)})
        assert r.status_code == 201, r.text
    run = client.post(base + '/run-audit', headers=headers).json()['run_id']
    for _ in range(300):
        if client.get('/api/v1/runs/' + run, headers=headers).json()['status'] != 'running':
            break
        time.sleep(.1)
    reports = {r['report_type']: r for r in client.get(base + '/reports', headers=headers).json()}
    unscored = [r for r in reports.values() if r['status'] in ('needs_review', 'failed')]
    assert reports['content_assessment'] in unscored
    assert 'exam' in reports['content_assessment']['reason']                    # the agent's own sentence: what to upload
    assert all('recorded no reason' not in r['reason'] and 'Not enough source data' not in r['reason'] for r in unscored)


def test_the_reason_is_read_from_the_stored_result_including_review_and_translation_notices():
    from api.v1.routes.workflow_routes import _reason
    def report(findings, status='needs_review'):
        return SimpleNamespace(status=status, findings={'agent_name': 'a', 'findings': findings})
    assert _reason(report({'reason': 'Keine Klausur hochgeladen.'})) == 'Keine Klausur hochgeladen.'
    assert _reason(report({'live_review_failure': 'Live specialist review failed.'})).startswith('Live specialist review')
    assert _reason(report({'translation_notice': 'Search translation failed.'})) == 'Search translation failed.'
    assert _reason(SimpleNamespace(status='needs_review', findings={'reason': 'top level, older rows'})) == 'top level, older rows'
    assert 'recorded no reason' in _reason(report({}))                          # honest fallback, never "not enough data"
    assert _reason(report({'reason': 'x'}, status='pass')) is None


def test_the_report_page_reads_assessment_scores_from_the_nested_findings():
    report_findings = _frontend_functions('views/_alignment_reports.py', 'report_findings')['report_findings']
    stored = {'findings': {'agent_name': 'content_assessment_agent', 'findings': {'assessment_scores': [{'title': 'Klausur', 'score': .4}], 'uncovered_topics': ['Graphen']}}}
    assert report_findings(stored)['uncovered_topics'] == ['Graphen']
    assert report_findings({'findings': {'clo_scores': []}}) == {'clo_scores': []}   # flat findings still work
    assert report_findings({}) == {}


def test_file_names_suggest_the_document_type_in_german_and_english():
    guess = _frontend_functions('views/_upload.py', '_NAME_HINTS', 'guess_artifact_type')['guess_artifact_type']
    assert guess('MWI_DL__Beschreibung_Modulhandbuch.pdf', 'slides') == 'module_manual'
    assert guess('Klausur_WS2025.pdf', 'slides') == 'exam'
    assert guess('Übungsblatt 3.pdf', 'slides') == 'assignment'
    assert guess('lecture_transcript.vtt', 'slides') == 'transcript'
    assert guess('syllabus.md', 'slides') == 'syllabus'
    assert guess('MWI_DL_05_Transformer.pdf', 'slides') == 'slides'               # no hint: the chosen default


def test_a_check_marked_for_review_keeps_its_statistics_unless_there_was_nothing_to_score():
    from api.v1.routes.workflow_routes import _has_statistics
    def report(findings, status='needs_review', score=.42):
        return SimpleNamespace(status=status, overall_score=score, findings={'agent_name': 'a', 'findings': findings})
    assert _has_statistics(report({'clo_scores': [{'code': 'LO1', 'score': .42}], 'live_review_failure': 'rejected'}))   # model review rejected
    assert _has_statistics(report({'clo_scores': [], 'translation_notice': 'Suchübersetzung fehlgeschlagen.'}))
    assert not _has_statistics(report({'reason': 'Keine Klausur hochgeladen.'}, score=0.0))                   # nothing to score
    assert not _has_statistics(report({'error': 'old wording'}, score=0.0))
    assert not _has_statistics(report({'assessment_scores': []}, status='failed'))
    assert _has_statistics(report({'assessment_scores': [{'title': 'Klausur', 'score': .5}]}, status='warning'))


def test_the_reports_list_says_which_checks_have_statistics(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': f'DE-STAT-{uuid.uuid4().hex[:6]}', 'title': 'Algorithmen'}).json()['id']
    base = f'/api/v1/courses/{course}'
    for name, kind, mime in (('modulhandbuch.md', 'syllabus', 'text/markdown'), ('vorlesung.txt', 'slides', 'text/plain')):
        client.post(base + '/artifacts', headers=headers, data={'artifact_type': kind}, files={'file': (name, (DATA / 'de_algorithmen' / name).read_bytes(), mime)})
    run = client.post(base + '/run-audit', headers=headers).json()['run_id']
    for _ in range(300):
        if client.get('/api/v1/runs/' + run, headers=headers).json()['status'] != 'running':
            break
        time.sleep(.1)
    listed = {r['report_type']: r for r in client.get(base + '/reports', headers=headers).json()}
    assert listed['content_assessment']['has_statistics'] is False                # no exam uploaded
    assert listed['metadata_content']['has_statistics'] is True
    one = client.get(f"/api/v1/reports/{listed['content_assessment']['id']}", headers=headers).json()
    assert one['has_statistics'] is False and 'exam' in one['reason']
