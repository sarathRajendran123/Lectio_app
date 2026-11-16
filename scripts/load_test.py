"""Load test of the API on a throwaway server (test mode, empty SQLite database, loopback).

    python scripts/load_test.py --users 20 --seconds 30 --out study/load

Prepares one course with documents, an audit and drafts, then lets N simulated lecturers send a mix of the calls the
pages make (dashboard, course list, reports, evidence, matrix, approvals, draft feedback) for the given time.
Writes load.json and prints latency per endpoint. Nothing touches the working database and no model is called.

This measures the API process and SQLite on this machine. It says nothing about model latency, the embedding models,
PostgreSQL or several server processes.
"""
import argparse
import json
import math
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_experiment   # noqa: E402

MIX = [("dashboard", 3), ("courses", 3), ("reports", 3), ("evidence", 2), ("matrix", 2), ("approvals", 2), ("structure", 1), ("draft_feedback", 2)]


def percentile(values: list, share: float):
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered), max(1, math.ceil(share * len(ordered)))) - 1]


def summarise(samples: list, seconds: float) -> dict:
    """samples: (endpoint, status code or None for a transport error, milliseconds)."""
    result = {}
    for name in sorted({s[0] for s in samples}) + ["all"]:
        rows = [s for s in samples if name == "all" or s[0] == name]
        times = [s[2] for s in rows if s[1] is not None and s[1] < 400]
        result[name] = {"requests": len(rows), "ok": len(times), "client_errors": sum(s[1] is not None and 400 <= s[1] < 500 for s in rows),
                        "server_errors": sum(s[1] is not None and s[1] >= 500 for s in rows), "transport_errors": sum(s[1] is None for s in rows),
                        "p50_ms": percentile(times, .5), "p95_ms": percentile(times, .95), "max_ms": max(times) if times else None}
    result["all"]["requests_per_second"] = round(len(samples) / seconds, 1) if seconds else None
    return result


def prepare(server) -> str:
    course = server.post("/courses", json={"code": "LOAD", "title": "Load test course"})["id"]
    base = f"/courses/{course}"
    folder = ROOT / "datasets" / "en_algorithms"
    for file in sorted(folder.iterdir()):
        artifact = server.post(base + "/artifacts", data={"artifact_type": run_experiment.kind(file.name)},
                               files={"file": (file.name, file.read_bytes(), run_experiment.MIME.get(file.suffix.lower(), "text/plain"))})["id"]
        for _ in range(300):
            if server.get(base + f"/artifacts/{artifact}/status")["processing_status"] in ("done", "error"):
                break
            time.sleep(.2)
    run = server.post(base + "/run-audit")["run_id"]
    while server.get(f"/runs/{run}")["status"] == "running":
        time.sleep(.5)
    return course


def user(base_url, token, course, stop_at, samples, number):
    calls = {"dashboard": ("GET", "/dashboard", None), "courses": ("GET", "/courses", None), "reports": ("GET", f"/courses/{course}/reports", None),
             "evidence": ("GET", f"/courses/{course}/evidence", None), "matrix": ("GET", f"/courses/{course}/matrix", None),
             "approvals": ("GET", f"/approvals?course_id={course}", None), "structure": ("GET", f"/courses/{course}/structure", None),
             "draft_feedback": ("POST", f"/courses/{course}/draft-feedback",
                                {"content_type": "exercise", "text": "Explain how binary search halves the search space of a sorted array."})}
    order = [name for name, weight in MIX for _ in range(weight)]
    step = number                                                    # users start at different points of the mix
    with httpx.Client(base_url=base_url, headers={"Authorization": "Bearer " + token}, timeout=60) as client:
        while time.time() < stop_at:
            name = order[step % len(order)]
            step += 1
            method, path, body = calls[name]
            started = time.perf_counter()
            try:
                status = client.request(method, path, json=body).status_code
            except httpx.HTTPError:
                status = None
            samples.append((name, status, round((time.perf_counter() - started) * 1000, 1)))   # list.append is atomic


def run(users: int, seconds: int) -> dict:
    with run_experiment.Server({}, live=False) as server:
        course = prepare(server)
        token = server.client.headers["Authorization"].split(" ", 1)[1]
        samples = []
        started = time.time()
        threads = [threading.Thread(target=user, args=(str(server.client.base_url), token, course, started + seconds, samples, n)) for n in range(users)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.time() - started
        healthy = httpx.get(f"http://127.0.0.1:{server.port}/health", timeout=10).status_code == 200
    return {"started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(timespec="seconds"), "users": users, "seconds": round(elapsed, 1),
            "mode": "local_test", "database": "sqlite", "server_processes": 1, "healthy_afterwards": healthy, "endpoints": summarise(samples, elapsed)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = run(args.users, args.seconds)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "load.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['users']} users, {report['seconds']} s, healthy afterwards: {report['healthy_afterwards']}")
    print(f"{'endpoint':16}{'requests':>9}{'ok':>7}{'4xx':>5}{'5xx':>5}{'failed':>7}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}")
    for name, row in report["endpoints"].items():
        print(f"{name:16}{row['requests']:>9}{row['ok']:>7}{row['client_errors']:>5}{row['server_errors']:>5}{row['transport_errors']:>7}"
              f"{str(row['p50_ms']):>9}{str(row['p95_ms']):>9}{str(row['max_ms']):>9}")
    print("requests per second:", report["endpoints"]["all"]["requests_per_second"])


if __name__ == "__main__":
    main()
