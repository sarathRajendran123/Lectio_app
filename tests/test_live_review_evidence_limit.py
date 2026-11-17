import pytest
from pydantic import ValidationError

from agents.live_review import Finding, Review, _kept


def finding(ids):
    return dict(title='Review finding', description='A finding requiring lecturer review.',
                severity='warning', rationale='Source evidence.', correction='Please review.',
                evidence_ids=ids, evidence_strength='moderate')


@pytest.mark.parametrize('count', [8, 9, 12])
def test_finding_accepts_up_to_available_twelve_sources(count):
    ids = [f'S{i}' for i in range(1, count + 1)]
    result = Finding.model_validate(finding(ids))
    assert result.evidence_ids == ids


def test_finding_rejects_more_than_twelve_source_references():
    with pytest.raises(ValidationError):
        Finding.model_validate(finding([f'S{i}' for i in range(1, 14)]))


def test_invented_reference_still_removes_finding():
    review = Review.model_validate({'findings': [finding(['S1', 'invented'])], 'limitations': 'Review.'})
    assert _kept(review, {'S1': object()}) == []


@pytest.mark.parametrize('alias', ['objective', 'learning objective', 'learning_objective', 'Course-Learning-Objective', 'learning outcome', 'CLO'])
def test_learning_objective_entity_alias_is_normalised(alias):
    data = finding(['S1'])
    data['affected_entity_type'] = alias
    assert Finding.model_validate(data).affected_entity_type == 'clo'


def test_unknown_entity_type_is_still_rejected():
    data = finding(['S1'])
    data['affected_entity_type'] = 'lecturer'
    with pytest.raises(ValidationError):
        Finding.model_validate(data)


def test_review_retries_once_for_schema_errors_without_echoing_model_output(monkeypatch):
    import json
    from config import settings
    from agents.live_review import _compute
    from rag.chunking.chunk_models import RetrievedChunk

    monkeypatch.setattr(settings, 'quality_max_retries', 1)
    chunk = RetrievedChunk('source-id', 'A valid source passage.', .7, 'artifact', 'slides', 'course', 1, None, None, None)
    calls = []

    class Agent:
        def _retrieve(self, *args):
            return [chunk]

        def _parse_json(self, raw):
            return json.loads(raw)

        def _invoke(self, system, human, validate):
            calls.append(human)
            data = finding(['S1'])
            data['affected_entity_type'] = 'secret-invalid-value' if len(calls) == 1 else 'objective'
            raw = json.dumps({'findings': [data], 'limitations': 'Review needed.'})
            validate(raw)
            return raw, 10

    state = {'modules': [], 'course_id': 'course', 'course_metadata': {'title': 'Course'}}
    review, _, tokens = _compute(Agent(), state, 'metadata_content')
    assert review.findings[0].affected_entity_type == 'clo'
    assert len(calls) == 2 and tokens == 10
    assert 'affected_entity_type' in calls[1]
    assert 'secret-invalid-value' not in calls[1]
