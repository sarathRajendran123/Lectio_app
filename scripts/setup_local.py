"""Create a local development configuration; never overwrite an existing .env."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
target=root/'.env'
if target.exists(): raise SystemExit('.env already exists; left unchanged.')
password=secrets.token_urlsafe(18)
(root/'data').mkdir(exist_ok=True)
target.write_text('\n'.join([
    'APP_ENV=development','RUNTIME_MODE=local_test','DEBUG=false',
    f'DATABASE_URL=sqlite+aiosqlite:///{(root/"data/lectio.db").as_posix()}',
    f'SECRET_KEY={secrets.token_urlsafe(48)}',
    'ADMIN_EMAIL=admin@example.org',f'ADMIN_PASSWORD={password}',
    f'ARTIFACT_STORAGE_PATH={(root/"data/uploads").as_posix()}',
    'GROQ_API_KEY=','BACKEND_URL=http://127.0.0.1:8000','']))
target.chmod(0o600)
print('Created local-test configuration. Login: admin@example.org')
print('Your generated password is in .env under ADMIN_PASSWORD. Keep that file private.')
