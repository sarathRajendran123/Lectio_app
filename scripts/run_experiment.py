"""Run the same course files through several configurations and compare what the system does.

    python scripts/run_experiment.py experiments/ablation_test_mode.json --out study/experiment
    python scripts/run_experiment.py my_spec.json --out study/live --live      # calls the model: uses provider quota

Each run gets its own server process, its own empty SQLite database and its own storage folder, so conditions cannot
influence each other and nothing touches your working database. Writes results.json (every measurement) and report.md.

Spec: {"dataset": "datasets/en_algorithms", "repeats": 2, "conditions": [
         {"name": "baseline", "description": "..."},
         {"name": "no_retries", "env": {"QUALITY_MAX_RETRIES": "0"}},
         {"name": "with_intent", "intent": {"goals": "...", "cognitive_levels": ["analyse"]}},
         {"name": "with_rules", "constraints": ["Keep exercises short."]},
         {"name": "no_transcript", "exclude": [".vtt"]}]}
The first condition is the baseline. Only the settings listed in knowledge/experiment.py may be changed.

Test mode (the default) calls no model. With --live every run sends real requests and repeats are not served from the
cache of an earlier run, so a spec with C conditions and R repeats costs C x R audits.
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from knowledge import experiment   # noqa: E402  (no database or settings import)

MIME = {".vtt": "text/vtt", ".md": "text/markdown", ".pdf": "application/pdf"}
PASSED_THROUGH = ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODEL", "EMBEDDING_MODEL",
                  "RERANK_MODEL", "EMBEDDING_DEVICE", "HF_HOME", "TRANSFORMERS_CACHE")
SYSTEM = ("SYSTEMROOT", "PATH", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "PATHEXT", "COMSPEC", "LANG")


def kind(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("syllabus", "handbuch", "manual")):
        return "syllabus"
    if any(k in n for k in ("exam", "klausur")):
        return "exam"
    if "transcript" in n or n.endswith(".vtt"):
        return "transcript"
    return "slides"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """One isolated backend: own database, own storage, own credentials, loopback only."""

    def __init__(self, overrides: dict, live: bool, startup_seconds: int = 120):
        self.folder = Path(tempfile.mkdtemp(prefix="lectio-experiment-"))
        self.port = _free_port()
        self.password = secrets.token_urlsafe(24) + "aA1!"
        env = {k: os.environ[k] for k in SYSTEM if k in os.environ}
        if live:
            from dotenv import dotenv_values
            stored = {**dotenv_values(ROOT / ".env"), **os.environ}
            env.update({k: stored[k] for k in PASSED_THROUGH if stored.get(k)})
            if not env.get("OPENROUTER_API_KEY"):
                raise SystemExit("--live needs OPENROUTER_API_KEY in the environment or in .env")
        env.update({k.upper(): v for k, v in overrides.items()})
        env.update(DATABASE_URL=f"sqlite+aiosqlite:///{(self.folder / 'experiment.db').as_posix()}", SECRET_KEY=secrets.token_urlsafe(48),
                   RUNTIME_MODE="live" if live else "local_test", ADMIN_EMAIL="experiment@example.org", ADMIN_PASSWORD=self.password,
                   ARTIFACT_STORAGE_PATH=str(self.folder / "uploads"), LOG_LEVEL="WARNING")
        self.log = open(self.folder / "server.log", "w", encoding="utf-8")
        self.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(ROOT / "backend"), "--host", "127.0.0.1",
                                         "--port", str(self.port)], cwd=self.folder, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.port}/api/v1", timeout=300)
        deadline = time.time() + startup_seconds
        while True:
            if self.process.poll() is not None:
                self.close()
                raise RuntimeError(f"The server stopped while starting. Log: {self.folder / 'server.log'}")
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.time() > deadline:
                self.close()
                raise RuntimeError(f"The server did not start in {startup_seconds} s. Log: {self.folder / 'server.log'}")
            time.sleep(.3)
        self.login()

    def login(self):
        login = self.client.post("/auth/login", json={"email": "experiment@example.org", "password": self.password})
        login.raise_for_status()
        self.client.headers["Authorization"] = "Bearer " + login.json()["access_token"]

    def _send(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code == 401:            # access tokens last ACCESS_TOKEN_EXPIRE_MINUTES; long runs log in again
            self.login()
            response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def get(self, path, **params):
        return self._send("GET", path, params=params or None)

    def post(self, path, **kwargs):
        return self._send("POST", path, **kwargs)

    def close(self):
        self.client.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run_condition(condition: dict, files: list[Path], live: bool, timeout: int) -> dict:
    started = time.time()
    with Server(condition.get("env", {}), live) as server:
        system = server.get("/system/status")
        course = server.post("/courses", json={"code": "EXPERIMENT", "title": "Experiment course"})["id"]
        base = f"/courses/{course}"
        if condition.get("intent"):
            server.client.put(base + "/intent", json=condition["intent"]).raise_for_status()
        for text in condition.get("constraints", []):
            server.post(base + "/constraints", json={"text": text})
        documents = {}
        for file in files:
            if any(part.lower() in file.name.lower() for part in condition.get("exclude", [])):
                documents[file.name] = "left out"
                continue
            artifact = server.post(base + "/artifacts", data={"artifact_type": kind(file.name)},
                                   files={"file": (file.name, file.read_bytes(), MIME.get(file.suffix.lower(), "text/plain"))})["id"]
            state = {}
            for _ in range(300):
                state = server.get(base + f"/artifacts/{artifact}/status")
                if state["processing_status"] in ("done", "error"):
                    break
                time.sleep(1)
            documents[file.name] = state.get("processing_status", "unknown")
        run = server.post(base + "/run-audit")["run_id"]
        deadline = time.time() + timeout
        while server.get(f"/runs/{run}")["status"] == "running":
            if time.time() > deadline:
                server.client.post(f"/runs/{run}/cancel")
                break
            time.sleep(.5)
        measured = experiment.collect(server.get, course, run)
        return {**measured, "seconds": round(time.time() - started, 1), "documents": documents,
                "mode": system.get("mode"), "model": system.get("model"), "retrieval": system.get("retrieval")}


def run(spec: dict, out: Path, live: bool = False, timeout: int = 900, echo=print) -> dict:
    spec = experiment.validate_spec(spec)
    folder = (ROOT / spec["dataset"]) if not Path(spec["dataset"]).is_absolute() else Path(spec["dataset"])
    files = sorted(f for f in folder.iterdir() if f.is_file()) if folder.is_dir() else []
    if not files:
        raise SystemExit(f"No course files in {folder}")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = {}
    for condition in spec["conditions"]:
        results[condition["name"]] = []
        for repeat in range(spec["repeats"]):
            echo(f"{condition['name']} run {repeat + 1} of {spec['repeats']} ...")
            try:
                measured = run_condition(condition, files, live, timeout)
            except Exception as exc:   # one broken condition must not lose the others; it is reported as not finished
                measured = {"status": "runner_error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            results[condition["name"]].append(measured)
            echo(f"  {measured['status']}" + (f", {len(measured['findings'])} findings, {measured['seconds']} s" if measured.get("dimensions") else f": {measured.get('error')}"))
    report = {"spec": spec, "mode": "live" if live else "local_test", "started_at": started, "files": [f.name for f in files],
              "comparison": experiment.compare(results), "runs": results}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(experiment.render_markdown(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="call the configured model (uses provider quota)")
    parser.add_argument("--timeout", type=int, default=900, help="seconds allowed per audit")
    args = parser.parse_args(argv)
    report = run(json.loads(args.spec.read_text(encoding="utf-8")), args.out, args.live, args.timeout)
    print(experiment.render_markdown(report))


if __name__ == "__main__":
    main()
