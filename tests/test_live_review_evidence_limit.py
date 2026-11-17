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
