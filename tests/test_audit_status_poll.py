import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('status,expected', [
    ('needs_review', 'finished with issues requiring review'),
    ('cancelled', 'was cancelled'),
    ('completed', 'Audit complete'),
])
def test_terminal_audit_status_stops_polling_and_shows_message(status, expected):
    source = Path('frontend/views/_upload.py').read_text(encoding='utf-8')
    module = ast.parse(source)
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == '_poll_run')
    messages = []
    calls = []
    class Placeholder:
        def container(self): return self
        def __enter__(self): return self
        def __exit__(self, *_): pass
    st = SimpleNamespace(empty=lambda: Placeholder(),
                         info=lambda m: messages.append(m),
                         warning=lambda m: messages.append(m),
                         success=lambda m: messages.append(m),
                         error=lambda m: messages.append(m))
    def fetch(*_):
        calls.append(1)
        return {'status': status, 'total_tokens': 0}, None
    ns = {'st': st, 'time': SimpleNamespace(sleep=lambda _: None),
          'safe_api_call': fetch, 'status_badge': lambda s: s}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<test>', 'exec'), ns)
    ns['_poll_run'](SimpleNamespace(get_run_status=lambda *_: None), 'run')
    assert len(calls) == 1
    assert any(expected in message for message in messages)
