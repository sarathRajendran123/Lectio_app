import json
from types import SimpleNamespace
from unittest.mock import patch
from agents.cross_language import search_translation
from agents.metadata_content_agent import MetadataContentAlignmentAgent


def test_german_translation_is_only_a_search_aid():
    def invoke(system, human, validate=None):
        assert 'untrusted' in system and validate is not None
        assert 'neuronaler Netze' in human
        return json.dumps({'english_query': 'Explain neural networks and architectures'}), 19
    value, tokens, status = search_translation('Studierenden verstehen neuronaler Netze', True, invoke)
    assert (value, tokens, status) == ('Explain neural networks and architectures', 19, 'generated_unverified')
    assert search_translation('Explain neural networks', True, invoke) == (None, 0, 'not_requested')
    assert search_translation('Die Studierenden lernen', False, invoke) == (None, 0, 'not_requested')


def test_translation_failure_is_reported():
    def invoke(*args, **kw): return 'not JSON', 0
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
    assert calls[:2] == [objective['text'], agent.search_query]
    assert calls == [objective['text'], agent.search_query]  # no incomparable phrase scores
    assert agent.last_evidence == ['real-source']
    assert score > 0 and tokens == 0


def test_failed_translation_marks_result_needs_review():
    agent = MetadataContentAlignmentAgent()
    agent._invoke = lambda *args, **kw: ('invalid', 4)     # **kw: the call now passes validate=
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


def test_live_lexical_low_score_is_uncertain_not_a_confirmed_failure(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'runtime_mode', 'live')
    monkeypatch.setattr(settings, 'retrieval_backend', 'lexical')
    agent = MetadataContentAlignmentAgent()
    monkeypatch.setattr(agent, '_audit_clo', lambda clo, course_id: (.24, None, 0))
    state = {'course_id': 'course', 'modules': [{'title': 'module', 'clos': [
        {'id': 'objective', 'text': 'Students can explain neural networks.'}]}], 'total_tokens': 0}
    report = agent.run(state)['alignment_results']['metadata_content']
    assert report.status == 'needs_review'
    assert report.findings['clo_scores'][0]['status'] == 'needs_review'
    assert 'not proven missing coverage' in report.findings['retrieval_notice']


def test_coverage_and_evidence_use_same_full_objective_passages(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'runtime_mode', 'live')
    monkeypatch.setattr(settings, 'retrieval_backend', 'neural')
    agent = MetadataContentAlignmentAgent()
    agent.search_query = 'Explain the importance of deep learning across industries'
    relevant = SimpleNamespace(chunk_id='teaching', score=.6, page_number=5, artifact_id='slides',
                               text='Deep learning is a key technology for applications across industries.')
    admin = SimpleNamespace(chunk_id='admin', score=.99, page_number=6, artifact_id='org',
                            text='Prüfungsleistung – Teams Die Studierenden bilden feste Teams.')
    second = SimpleNamespace(chunk_id='industry', score=.5, page_number=8, artifact_id='slides',
                             text='Industrial artificial intelligence improves quality and manufacturing.')
    third = SimpleNamespace(chunk_id='applications', score=.4, page_number=9, artifact_id='slides',
                            text='Machine learning applications affect many industries and services.')
    queries = []
    def retrieve(query, course_id, top_k, where):
        queries.append((query, top_k))
        if query == agent.search_query:
            return [admin, second, third]
        return [relevant]
    monkeypatch.setattr(agent, '_retrieve', retrieve)
    monkeypatch.setattr(agent, '_bloom_score', lambda *_: 0.0)
    objective = {'id': 'objective', 'code': 'EXT-1', 'text': 'Die Studierenden verstehen Deep Learning',
                 'bloom_level': 'understand'}
    score, gap, _ = agent._audit_clo(objective, 'course')
    assert queries == [(objective['text'], 10), (agent.search_query, 10)]
    assert agent.last_evidence == ['teaching', 'industry', 'applications']
    assert gap and 'Best retrieval match: 0.60' in gap.description
    assert 'admin' not in gap.evidence_chunk_ids


def test_german_keyword_extraction_keeps_umlauts_and_skips_common_words():
    agent = MetadataContentAlignmentAgent()
    words = agent._extract_keywords('Die Studierenden können neuronale Netze für Ölqualität erklären.')
    assert 'ölqualität' in words
    assert 'können' not in words and 'die' not in words and 'für' not in words
    assert 'erklären' in words


def test_a_fenced_translation_is_accepted_and_an_unusable_one_is_never_cached():
    # The validator goes to the provider client: output it rejects is not cached and not replayed on the next audit.
    seen = {}
    def invoke(system, human, validate=None):
        seen['validate'] = validate
        return '```json\n{"english_query": "Explain neural network architectures"}\n```', 7
    assert search_translation('Die Studierenden verstehen neuronaler Netze', True, invoke) == ('Explain neural network architectures', 7, 'generated_unverified')
    import pytest
    for bad in ('not JSON', '{"english_query": "x"}', '["Erkläre"]'):
        with pytest.raises(Exception):
            seen['validate'](bad)
