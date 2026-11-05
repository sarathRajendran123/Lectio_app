import os
import sys
from pathlib import Path
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'backend'))
TEST_ROOT=Path(tempfile.mkdtemp(prefix='lectio-tests-'))
os.environ.update(DATABASE_URL=f'sqlite+aiosqlite:///{TEST_ROOT}/test.db',
    SECRET_KEY='test-only-secret-more-than-thirty-two-characters',RUNTIME_MODE='local_test',
    ADMIN_EMAIL='admin@example.org',ADMIN_PASSWORD='LectioTestPassword!42',ARTIFACT_STORAGE_PATH=str(TEST_ROOT/'uploads'))
import pytest
from fastapi.testclient import TestClient
from main import app

@pytest.fixture(scope='session')
def client():
    with TestClient(app) as c: yield c

@pytest.fixture(scope='session')
def headers(client):
    r=client.post('/api/v1/auth/login',json={'email':'admin@example.org','password':'LectioTestPassword!42'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}
