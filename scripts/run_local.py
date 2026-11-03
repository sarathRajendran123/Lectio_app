"""Start the existing FastAPI and Streamlit apps together, on loopback only."""
import os
from pathlib import Path
import subprocess
import sys
import time
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1]
if not (root/'.env').exists():raise SystemExit('Run python scripts/setup_local.py first.')
load_dotenv(root/'.env')
os.chdir(root)
processes=[]
try:
    processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--app-dir','backend','--host','127.0.0.1','--port','8000']))
    processes.append(subprocess.Popen([sys.executable,'-m','streamlit','run','frontend/app.py','--server.address','127.0.0.1','--server.port','8501']))
    print('Lectio: http://127.0.0.1:8501 | API: http://127.0.0.1:8000/docs')
    while all(p.poll() is None for p in processes):time.sleep(1)
finally:
    for process in processes:
        if process.poll() is None:process.terminate()
    for process in processes:
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill()
