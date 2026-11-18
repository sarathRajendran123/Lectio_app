"""Preserve preliminary analysis when optional live review fails validation."""


def try_live_review(agent, output, dimension, augment):
    try:
        return augment(agent, output, dimension), None
    except Exception as exc:
        # The model output remains rejected. Do not present a partial live review.
        reason = str(exc)[:500]
        result = output['alignment_results'][dimension]
        result.status = 'needs_review'
        result.findings['live_review_failure'] = (
            'Live specialist review failed or was rejected. Preliminary heuristic results '
            'are retained for lecturer review; live analysis is incomplete. ' + reason
        )
        return agent._log_error(output, reason), reason
