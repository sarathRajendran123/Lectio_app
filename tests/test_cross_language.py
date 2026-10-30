import json
from types import SimpleNamespace
from unittest.mock import patch
from agents.cross_language import search_translation
from agents.metadata_content_agent import MetadataContentAlignmentAgent


def test_german_translation_is_only_a_search_aid():
    def invoke(system, human):
        assert 'untrusted' in system
        assert 'neuronaler Netze' in human
        return json.dumps({'english_query': 'Explain neural networks and architectures'}), 19
    value, tokens, status = search_translation('Studierenden verstehen neuronaler Netze', True, invoke)
    assert (value, tokens, status) == ('Explain neural networks and architectures', 19, 'generated_unverified')
    assert search_translation('Explain neural networks', True, invoke) == (None, 0, 'not_requested')
    assert search_translation('Die Studierenden lernen', False, invoke) == (None, 0, 'not_requested')


def test_translation_failure_is_reported():
    def invoke(*args): return 'not JSON', 0
    assert search_translation('Die Studierenden lernen', True, invoke) == (None, 0, 'failed')


def test_original_and_english_searches_return_actual_source_ids():
    agent = MetadataContentAlignmentAgent()
    agent.search_query = 'Explain neural networks and architectures'
    calls = []
    def retrieve(query, course_id, top_k, where):
        calls.append(query)
        if query.startswith('Explain'):
            return [SimpleNamespace(chunk_id='real-source', score=.8, text='Explain neural networks and architectures.')]
        return []
    agent._retrieve = retrieve
    objective = {'id': 'objective', 'code': 'CLO1', 'text': 'Die Studierenden verstehen neuronaler Netze', 'bloom_level': 'understand'}
    score, gap, tokens = agent._audit_clo(objective, 'course')
    assert calls == [objective['text'], agent.search_query]
    assert agent.last_evidence == ['real-source']
    assert score > 0 and tokens == 0


def test_failed_translation_marks_result_needs_review():
    agent = MetadataContentAlignmentAgent()
    agent._invoke = lambda *args: ('invalid', 4)
    agent._retrieve = lambda *args, **kwargs: []
    config = SimpleNamespace(settings=SimpleNamespace(runtime_mode='live', active_api_key='test', active_model='example/model'))
    state = {'course_id': 'course', 'modules': [{'title': 'module', 'clos': [
        {'id': 'objective', 'text': 'Die Studierenden verstehen neuronaler Netze'}]}], 'total_tokens': 0}
    with patch.dict('sys.modules', {'config': config}):
        result = agent.run(state)
    report = result['alignment_results']['metadata_content']
    assert report.status == 'needs_review'
    assert report.findings['clo_scores'][0]['status'] == 'needs_review'
    assert result['total_tokens'] == 4
