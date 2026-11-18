from agents.graph.state import AlignmentGap, AlignmentResult
from agents.live_review_fallback import try_live_review


def test_rejected_review_keeps_heuristics_and_reports_failure():
    class Agent:
        def _log_error(self, state, message):
            return {**state, 'error_log': [{'message': message}]}
    gap = AlignmentGap('gap', 'test', 'warning', 'Existing finding', 'course', None, .3, 'Review')
    result = AlignmentResult('agent', 'metadata_content', .3, 'warning', [gap],
                             {'clo_scores': [{'search_translation': 'Neural networks'}]})
    state = {'alignment_results': {'metadata_content': result}}
    def reject(*args): raise ValueError('Live specialist cited an unknown source. Output rejected.')
    updated, error = try_live_review(Agent(), state, 'metadata_content', reject)
    assert 'unknown source' in error
    assert result.status == 'needs_review' and result.gaps == [gap]
    assert result.findings['clo_scores'][0]['search_translation'] == 'Neural networks'
    assert 'incomplete' in result.findings['live_review_failure']
    assert updated['error_log']
