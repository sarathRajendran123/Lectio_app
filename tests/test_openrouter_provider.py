from types import SimpleNamespace
from unittest.mock import patch
import sys

from services.llm_provider import build_chat, OPENROUTER_ENDPOINT


def test_openrouter_request_and_token_accounting():
    calls = []
    class HTTPError(Exception): pass
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices': [{'message': {'content': 'Model response'}}],
                    'usage': {'total_tokens': 17}}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    fake_httpx = SimpleNamespace(post=post, HTTPError=HTTPError)
    settings = SimpleNamespace(active_model='example/model', active_api_key='test-key',
        llm_provider='openrouter', llm_timeout_seconds=5)
    with patch.dict(sys.modules, {'httpx': fake_httpx}):
        response = build_chat(settings).invoke([SimpleNamespace(type='human', content='hello')])
    assert calls[0][0] == OPENROUTER_ENDPOINT
    assert calls[0][1]['json']['model'] == 'example/model'
    assert calls[0][1]['json']['messages'] == [{'role': 'user', 'content': 'hello'}]
    assert calls[0][1]['headers']['Authorization'] == 'Bearer test-key'
    assert response.content == 'Model response'
    assert response.response_metadata['token_usage']['total_tokens'] == 17


def test_openrouter_requires_model_and_key():
    settings = SimpleNamespace(active_model='', active_api_key='test-key',
        llm_provider='openrouter', llm_timeout_seconds=5)
    try:
        build_chat(settings)
    except ValueError as exc:
        assert 'model and API key' in str(exc)
    else:
        raise AssertionError('A missing model must not silently fall back')
