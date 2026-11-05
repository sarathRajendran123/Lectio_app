"""Upload a dataset folder to a running local API, run an audit and print the results.

    python scripts/run_dataset.py datasets/en_algorithms

File type is guessed from the name: syllabus/handbuch/manual -> syllabus, exam/klausur -> exam,
transcript/.vtt -> transcript, anything else -> slides. Uses ADMIN_EMAIL/ADMIN_PASSWORD from .env.
"""
import os
import sys
import time
from pathlib import Path
import httpx
from dotenv import load_dotenv
root = Path(__file__).resolve().parents[1]; load_dotenv(root / '.env')


MIME = {'.vtt': 'text/vtt', '.md': 'text/markdown'}


def kind(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ('syllabus', 'handbuch', 'manual')): return 'syllabus'
    if any(k in n for k in ('exam', 'klausur')): return 'exam'
    if 'transcript' in n or n.endswith('.vtt'): return 'transcript'
    return 'slides'


def main(folder: str, base: str = 'http://127.0.0.1:8000'):
    c = httpx.Client(base_url=base + '/api/v1', timeout=180)
    r = c.post('/auth/login', json={'email': os.environ['ADMIN_EMAIL'], 'password': os.environ['ADMIN_PASSWORD']}); r.raise_for_status()
    H = {'Authorization': 'Bearer ' + r.json()['access_token']}
    folder_path = Path(folder)
    course = c.post('/courses', headers=H, json={'code': f'{folder_path.name[:12].upper()}-{int(time.time()) % 10000}',
                    'title': folder_path.name}).json()['id']
    path = f'/courses/{course}'
    for f in sorted(folder_path.iterdir()):
        a = c.post(path + '/artifacts', headers=H, files={'file': (f.name, f.read_bytes(), MIME.get(f.suffix, 'text/plain'))}, data={'artifact_type': kind(f.name)}).json()['id']
        for _ in range(180):
            s = c.get(path + f'/artifacts/{a}/status', headers=H).json()
            if s['processing_status'] in ('done', 'error'): break
            time.sleep(2)
        print(f'{f.name:28} {kind(f.name):10} {s["processing_status"]} {s.get("processing_error") or ""}')
    run = c.post(path + '/run-audit', headers=H).json()['run_id']
    for _ in range(300):
        st = c.get('/runs/' + run, headers=H).json()
        if st['status'] != 'running': break
        time.sleep(3)
    print('run:', st['status'], '| tokens', st.get('total_tokens'))
    for m in c.get(path + '/modules', headers=H).json():
        for o in c.get(path + f"/modules/{m['id']}/clos", headers=H).json():
            print(f"  {o.get('code'):7} [{o.get('bloom_level')}] {o['text'][:110]}")
    for x in sorted(c.get(path + '/reports', headers=H).json(), key=lambda x: x['report_type']):
        shown = 'NOT ASSESSABLE' if x['status'] in ('needs_review', 'failed') else f"{x['overall_score']:.0%}"
        print(f"report {x['report_type']:20} {x['status']:13} {shown:15} gaps={x['gap_count']} {x.get('reason') or ''}")
    return course


if __name__ == '__main__':
    main(*sys.argv[1:3])
