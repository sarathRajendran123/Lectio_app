"""Launch ephemeral localhost API, seed an explicit fixture, check all screens, stop."""
import os
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
import httpx
log=open(ROOT/'data/ui-api.log','w')
api=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--app-dir','backend','--host','127.0.0.1','--port','8000'],cwd=ROOT,stdout=log,stderr=log)
try:
    with httpx.Client(trust_env=False,timeout=2) as c:
        for _ in range(80):
            try:
                if c.get('http://127.0.0.1:8000/health').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_ui.py')],cwd=ROOT)
    raise SystemExit(result.returncode)
finally:
    api.terminate();api.wait(timeout=10);log.close()
