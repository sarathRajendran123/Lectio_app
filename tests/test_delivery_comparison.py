"""Checks source separation and conservative delivery-comparison behaviour."""
from types import SimpleNamespace

from agents.delivery_comparison import compare_delivery


def chunk(identifier, score=.8, week=1):
    return SimpleNamespace(chunk_id=identifier, score=score, week_number=week)


def test_delivery_comparison_keeps_sources_separate_and_rejects_other_weeks():
    modules = [{'title': 'ML', 'weeks': [{'week_number': 1, 'topics': [
        {'id': 'topic-1', 'title': 'Decision trees'},
        {'id': 'topic-2', 'title': 'Random forests'},
    ]}]}]
    data = {
        ('Decision trees', 'slides'): [chunk('slide-1')],
        ('Decision trees', 'transcript'): [chunk('transcript-1')],
        ('Random forests', 'slides'): [chunk('slide-2')],
        ('Random forests', 'transcript'): [chunk('other-week', week=3), chunk('weak', score=.1)],
    }
    def retrieve(title, course_id, top_k, where):
        assert course_id == 'course-1'
        return data.get((title, where['artifact_type']), [])

    rows, truncated = compare_delivery(modules, 'course-1', retrieve)
    assert not truncated
    assert rows[0]['status'] == 'both_have_matching_evidence'
    assert rows[0]['prepared_chunk_ids'] == ['slide-1']
    assert rows[0]['transcript_chunk_ids'] == ['transcript-1']
    assert rows[1]['status'] == 'transcript_evidence_not_found'
    assert rows[1]['transcript_chunk_ids'] == []
    assert 'does not prove' in rows[1]['notice']


def test_empty_evidence_and_comparison_limit():
    topics = [{'title': f'Topic {i}'} for i in range(21)]
    modules = [{'weeks': [{'week_number': 1, 'topics': topics}]}]
    rows, truncated = compare_delivery(modules, 'course-1', lambda *args, **kwargs: [])
    assert truncated and len(rows) == 20
    assert all(row['status'] == 'no_matching_evidence' for row in rows)
