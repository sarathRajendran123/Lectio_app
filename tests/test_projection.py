"""Projected scores from approved drafts: honest re-check, never assumed."""
import time
from types import SimpleNamespace as NS

from services import projection as p
from test_multilingual_model import _upload


def gap(kind, description, severity='warning'):
    return NS(gap_type=kind, description=description, severity=severity)


def draft(text, kind='quiz'):
    return {'id': 'd1', 'title': 't', 'type': kind, 'text': text}


def test_topic_gap_is_addressed_only_by_a_draft_that_really_covers_it():
    g = gap('topic_not_assessed', "Topic 'Hash tables and collision handling' has lecture content but no assessment questions.")
    hit, why = p.check_gap(g, [draft('Question: explain hash tables and collision handling with chaining and open addressing.')])
    assert hit and 'similarity' in why
    miss, why = p.check_gap(g, [draft('Question: describe photosynthesis in plants and the role of chlorophyll.')])
    assert miss is None and 'no approved' in why


def test_a_draft_cannot_close_a_delivery_or_coverage_gap_and_wrong_draft_types_are_ignored():
    assert p.check_gap(gap('topic_not_delivered', 'x'), [draft('anything')])[0] is None
    g = gap('topic_not_assessed', "Topic 'Graph traversal' has lecture content but no assessment questions.")
    assert p.check_gap(g, [draft('graph traversal with BFS and DFS', kind='description')])[0] is None


def test_bloom_gap_needs_a_draft_aligned_with_taught_level():
    g = gap('bloom_level_mismatch', "Assessment 'E' targets 'create' level but content only reaches 'understand'. The verb heuristic")
    assert p.check_gap(g, [draft('Students will be able to explain binary search.', 'clo')])[0]
    assert p.check_gap(g, [draft('Students will be able to design a new algorithm.', 'clo')])[0] is None


def test_status_thresholds_match_the_audit_agents():
    assert p.status_for('content_assessment', .76) == 'pass' and p.status_for('metadata_assessment', .76) == 'warning'


def test_projection_moves_only_after_approval_and_stays_below_verified_100(client, headers):
    course = client.post('/api/v1/courses', headers=headers, json={'code': 'PROJ-EN', 'title': 'Algorithms'}).json()['id']
    base = f'/api/v1/courses/{course}'
    for name, kind, mime in [('syllabus.md', 'syllabus', 'text/markdown'), ('lecture_slides.txt', 'slides', 'text/plain'),
                             ('lecture_transcript.vtt', 'transcript', 'text/vtt'), ('exam.txt', 'exam', 'text/plain')]:
        _upload(client, headers, base, 'en_algorithms', name, kind, mime)
    run = client.post(base + '/run-audit', headers=headers).json()['run_id']
    for _ in range(300):
        if client.get('/api/v1/runs/' + run, headers=headers).json()['status'] != 'running':
            break
        time.sleep(.1)
    before = client.get(base + '/projection', headers=headers).json()
    assert before['approved_drafts'] == 0
    assert all(d['delta'] == 0 for d in before['dimensions'])          # nothing approved: no movement
    pending = [i for i in client.get('/api/v1/approvals?status=pending', headers=headers).json() if i['course_id'] == course]
    assert pending, 'audit should have drafted fixes for the gaps'
    rejected, accepted = pending[0], pending[1:]
    assert client.post(f"/api/v1/approvals/{rejected['id']}/reject", headers=headers, json='Not suitable').status_code == 200
    for item in accepted:
        assert client.post(f"/api/v1/approvals/{item['id']}/approve", headers=headers, json='ok').status_code == 200
    after = client.get(base + '/projection', headers=headers).json()
    assert after['approved_drafts'] == len(accepted)
    for d in after['dimensions']:
        if d['projected_score'] is None:
            continue
        assert d['projected_score'] >= d['verified_score'] and d['delta'] >= 0
        assert d['projected_score'] < 1.0 or not d['open']              # 100% only if nothing is left open
        assert len(d['addressed']) + len(d['open']) == d['gaps_total']
    assert any(d['addressed'] for d in after['dimensions']) and any(d['delta'] > 0 for d in after['dimensions'])
    verified_now = {r['report_type']: r['overall_score'] for r in client.get(base + '/reports', headers=headers).json()}
    assert all(abs(d['verified_score'] - verified_now[d['report_type']]) < 1e-6 for d in after['dimensions'])  # verified untouched


def test_one_draft_closes_at_most_one_level_gap():
    g = gap('bloom_level_mismatch', "Assessment 'E' targets 'create' level but content only reaches 'understand'. x")
    d = draft('Students will be able to explain binary search.', 'clo')
    first, _ = p.check_gap(g, [d], set())
    assert first and p.check_gap(g, [d], {d['id']})[0] is None


def test_model_findings_about_missing_objectives_or_assessments_can_be_closed_by_matching_drafts():
    g = gap('live_missing_objective', 'No objective for graph traversal: BFS and DFS are taught in week 4 Rationale: none covers it')
    obj = draft('Students will be able to apply BFS and DFS graph traversal.', 'clo')
    assert p.target_of(g).endswith('week 4')
    assert p.check_gap(g, [obj])[0]
    assert p.check_gap(g, [draft('Quiz on graph traversal with BFS and DFS', 'quiz')])[0] is None     # wrong draft type
    assert p.check_gap(g, [draft('Students will be able to bake bread and cakes.', 'clo')])[0] is None   # unrelated
    a = gap('live_missing_assessment', 'Exam items about hash tables collisions are missing. Rationale: x')
    assert p.check_gap(a, [draft('Question: explain hash tables collisions.', 'quiz')])[0]
    assert p.check_gap(gap('live_alignment_review', 'Schedule unclear'), [obj])[0] is None


def test_projection_is_capped_and_a_single_finding_cannot_explain_the_whole_shortfall():
    assert p.projected_score(.76, .5, .5) < .82            # one minor finding closed: modest gain, not 100%
    assert p.projected_score(.5, 10, 10) == p.MAX_PROJECTED   # everything closed: still capped
    assert p.projected_score(.97, 0, 5) == .97 and p.projected_score(.97, 5, 5) == .97   # never below verified
    assert p.projected_score(.67, 3.0, 3.5) == p.MAX_PROJECTED and abs(p.projected_score(.67, 1.0, 3.5) - (.67 + .33 / 3.5)) < 1e-9
