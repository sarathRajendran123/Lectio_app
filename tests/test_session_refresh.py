import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit


def test_refresh_retries_the_bound_client_with_the_new_token(monkeypatch):
    frontend = Path(__file__).resolve().parents[1] / 'frontend'
    monkeypatch.syspath_prepend(str(frontend))
    spec = importlib.util.spec_from_file_location('lectio_session_test', frontend / 'utils' / 'session_utils.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = {'access_token': 'old', 'refresh_token': 'refresh'}
    monkeypatch.setattr(module, '_st', lambda: SimpleNamespace(session_state=state))
    def refresh():
        state['access_token'] = 'new'
        return True
    monkeypatch.setattr(module, 'try_refresh', refresh)
    def request(client):
        if client._token == 'old':
            raise module.APIError(401, 'expired')
        return client._token
    monkeypatch.setattr(module.LectioClient, 'test_request', request, raising=False)
    client = module.LectioClient(access_token='old')
    result, error = module.safe_api_call(client.test_request)
    assert result == 'new' and error is None


def test_expired_session_rotates_real_refresh_token_and_retries_api(client, monkeypatch):
    frontend = Path(__file__).resolve().parents[1] / 'frontend'
    monkeypatch.syspath_prepend(str(frontend))
    spec = importlib.util.spec_from_file_location('lectio_session_integration_test', frontend / 'utils' / 'session_utils.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from api_client import lectio_client
    from config import settings
    # The test fixture supplies isolated test-only credentials, not a real account.
    login = client.post('/api/v1/auth/login', json={'email': settings.admin_email, 'password': settings.admin_password}).json()
    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__
    state = State(access_token='expired-invalid-token', refresh_token=login['refresh_token'])
    monkeypatch.setattr(module, '_st', lambda: SimpleNamespace(session_state=state))
    class TestPool:
        def get(self, url, timeout=None, **kwargs):
            return client.get(urlsplit(url).path, **kwargs)
        def post(self, url, timeout=None, **kwargs):
            return client.post(urlsplit(url).path, **kwargs)
    monkeypatch.setattr(lectio_client, '_pool', TestPool())
    lectio_client._cache.clear()
    api = module.LectioClient(access_token=state['access_token'])
    courses, error = module.safe_api_call(api.list_courses)
    assert error is None and 'courses' in courses
    assert state['access_token'] != 'expired-invalid-token' and api._token == state['access_token']
    assert state['refresh_token'] != login['refresh_token']
