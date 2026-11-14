"""Bug hunt with deliberately defective input, on a throwaway server (test mode by default).

    python scripts/run_defect_suite.py --out study/defects

Part 1, broken files: uploads about twenty files that are empty, mislabelled, wrongly encoded, corrupt or oddly named.
Each has a list of acceptable outcomes (a clear refusal, or clean processing). Anything else is reported: a server
error, a hang, a file accepted as "done" with nothing extracted, or a refusal without a reason.

Part 2, planted misalignments: audits the courses in datasets/defects/ and reports which planted defects the audit
found, which it missed, and what it raised on the aligned control course.

Writes results.json and report.md. The courses are synthetic; the result is a list of places to look, not an
evaluation of usefulness.
"""
import argparse
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_experiment   # noqa: E402

TEXT = "Binary search halves the search space of a sorted array in every step and runs in logarithmic time."
REFUSED, PROCESSED = "refused with a reason", "processed"


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def _blank_pdf():
    import fitz
    document = fitz.open()
    document.new_page()
    return document.tobytes()


def _docx(paragraphs):
    import docx
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def broken_files():
    """(id, description, filename, bytes, mime, artifact_type, acceptable outcomes)"""
    vtt_ok = "WEBVTT\n\n00:00:01.000 --> 00:00:20.000\n" + TEXT + "\n"
    return [
        ("F01", "empty file", "empty.txt", b"", "text/plain", "slides", [REFUSED]),
        ("F02", "only spaces and line breaks", "blank.txt", b"   \n\n \t\n", "text/plain", "slides", [REFUSED]),
        ("F03", "random bytes named .pdf", "random.pdf", bytes(range(256)) * 20, "application/pdf", "slides", [REFUSED]),
        ("F04", "PDF header followed by garbage", "truncated.pdf", b"%PDF-1.7\n" + b"\x00\xff garbage " * 200, "application/pdf", "slides", [REFUSED]),
        ("F05", "valid PDF with one blank page (like a scan)", "scan.pdf", _blank_pdf(), "application/pdf", "slides", [REFUSED]),
        ("F06", "zip archive named .docx", "notes.docx", _zip([("hello.txt", "not a document")]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "slides", [REFUSED]),
        ("F07", "Word document with no text", "empty.docx", _docx([]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "slides", [REFUSED]),
        ("F08", "valid Word document with German text", "Übung.docx", _docx(["Die binäre Suche halbiert in jedem Schritt den Suchraum eines sortierten Arrays."]),
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "slides", [PROCESSED]),
        ("F09", "text saved as Latin-1 with umlauts", "latin1.txt", "Die binäre Suche halbiert den Suchraum für sortierte Felder.".encode("latin-1"), "text/plain", "slides", [REFUSED]),
        ("F10", "text saved as UTF-16", "utf16.txt", TEXT.encode("utf-16"), "text/plain", "slides", [REFUSED, PROCESSED]),
        ("F11", "text with a byte-order mark (as Notepad saves it)", "bom.txt", b"\xef\xbb\xbf" + TEXT.encode(), "text/plain", "slides", [PROCESSED]),
        ("F12", "text containing zero bytes", "nul.txt", b"Binary\x00search\x00halves the search space.", "text/plain", "slides", [REFUSED]),
        ("F13", "program file", "tool.exe", b"MZ\x90\x00" + b"\x00" * 200, "application/octet-stream", "slides", [REFUSED]),
        ("F14", "double extension", "lecture.pdf.exe", b"MZ\x90\x00" + b"\x00" * 200, "application/octet-stream", "slides", [REFUSED]),
        ("F15", "no extension", "lecture", TEXT.encode(), "text/plain", "slides", [REFUSED]),
        ("F16", "file name that tries to leave the upload folder", "../../outside.txt", (TEXT + " Traversal case.").encode(), "text/plain", "slides", [PROCESSED, REFUSED]),
        ("F17", "file name with umlauts, spaces and a dash", "Vorlesung Übung – 01.txt", (TEXT + " Umlaut case.").encode(), "text/plain", "slides", [PROCESSED]),
        ("F18", "file name of 300 characters", "a" * 296 + ".txt", (TEXT + " Long name case.").encode(), "text/plain", "slides", [PROCESSED, REFUSED]),
        ("F19", "one 2 MB line without any space", "oneline.txt", b"x" * 2_000_000, "text/plain", "slides", [PROCESSED, REFUSED]),
        ("F20", "transcript without timestamps", "plain.vtt", ("WEBVTT\n\n" + TEXT + "\n").encode(), "text/vtt", "transcript", [PROCESSED, REFUSED]),
        ("F21", "transcript with a broken timestamp line", "broken.vtt", ("WEBVTT\n\n00:00:xx --> later\n" + TEXT + " Broken stamp.\n").encode(), "text/vtt", "transcript", [PROCESSED, REFUSED]),
        ("F22", "valid transcript", "good.vtt", vtt_ok.encode(), "text/vtt", "transcript", [PROCESSED]),
        ("F23", "Markdown with headings only", "headings.md", b"# Week 1\n\n## Sorting\n\n## Searching\n", "text/markdown", "syllabus", [PROCESSED, REFUSED]),
        ("F24", "only digits and symbols", "symbols.txt", b"1234567890 +-*/ ()[]{} 3.14159 ;;;; ---- ==== 42 42 42 42", "text/plain", "slides", [PROCESSED, REFUSED]),
        ("F25", "text file declared as PDF by the browser", "declared.txt", (TEXT + " Wrong type case.").encode(), "application/pdf", "slides", [REFUSED]),
        ("F26", "unknown document type chosen", "kind.txt", (TEXT + " Unknown kind case.").encode(), "text/plain", "banana", [REFUSED]),
        ("F27", "script tags and SQL in the text", "inject.txt", b"<script>alert(1)</script> Robert'); DROP TABLE courses;-- Binary search halves the search space of a sorted array.", "text/plain", "slides", [PROCESSED]),
        ("F28", "the same file a second time", "bom.txt", b"\xef\xbb\xbf" + TEXT.encode(), "text/plain", "slides", [REFUSED]),
    ]


def upload_case(server, base, case, timeout=120):
    case_id, what, name, data, mime, kind, acceptable = case
    started = time.time()
    result = {"id": case_id, "what": what, "file": name if len(name) < 60 else name[:20] + "…" + name[-8:], "bytes": len(data), "acceptable": acceptable}
    try:
        response = server.client.post(base + "/artifacts", data={"artifact_type": kind}, files={"file": (name, data, mime)}, timeout=timeout)
    except Exception as exc:
        return {**result, "outcome": "no answer", "detail": type(exc).__name__, "seconds": round(time.time() - started, 1), "problem": "the server did not answer"}
    result["http"] = response.status_code
    detail = ""
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else ""
        detail = detail if isinstance(detail, str) else json.dumps(detail)[:200]
    except ValueError:
        body = {}
    if response.status_code >= 500:
        return {**result, "outcome": "server error", "detail": detail[:200], "seconds": round(time.time() - started, 1), "problem": "server error instead of a clear refusal"}
    if response.status_code >= 400:
        outcome, problem = REFUSED, None
        if not detail or detail == "Internal server error.":
            outcome, problem = "refused without a reason", "refusal carries no usable message"
        elif REFUSED not in acceptable:
            problem = "a file that should be usable was refused"
        return {**result, "outcome": outcome, "detail": detail[:200], "seconds": round(time.time() - started, 1), "problem": problem}
    artifact = body["id"]
    state = {}
    while time.time() - started < timeout:
        state = server.get(base + f"/artifacts/{artifact}/status")
        if state["processing_status"] in ("done", "error"):
            break
        time.sleep(.3)
    result["seconds"] = round(time.time() - started, 1)
    result["stored_as"] = body.get("filename")
    if state.get("processing_status") == "error":
        reason = state.get("processing_error") or ""
        problem = None if reason else "processing failed without a reason"
        if reason and REFUSED not in acceptable:
            problem = "a file that should be usable failed in processing"
        return {**result, "outcome": REFUSED if reason else "failed without a reason", "detail": reason[:200], "problem": problem}
    if state.get("processing_status") != "done":
        return {**result, "outcome": "still processing", "detail": state.get("processing_status", ""), "problem": f"not finished after {timeout} s"}
    chunks = len(server.get(base + "/evidence", artifact_id=artifact))
    result["chunks"] = chunks
    problem = None
    if chunks == 0:
        problem = "accepted as done although nothing was extracted"
    elif PROCESSED not in acceptable:
        problem = "accepted although it should have been refused"
    return {**result, "outcome": PROCESSED, "detail": f"{chunks} passage(s)", "problem": problem}


def run_files(server):
    course = server.post("/courses", json={"code": "DEFECT-FILES", "title": "Broken file cases"})["id"]
    base = f"/courses/{course}"
    results = [upload_case(server, base, case) for case in broken_files()]
    stored = [r.get("stored_as") or "" for r in results]
    escaped = [name for name in stored if ".." in name or "/" in name or "\\" in name]
    health = server.client.get(f"http://127.0.0.1:{server.port}/health").status_code
    return {"cases": results, "stored_names_leaving_the_folder": escaped, "server_healthy_afterwards": health == 200}


def audit_course(server, folder: Path, defects: list) -> dict:
    course = server.post("/courses", json={"code": ("DEFECT-" + folder.name.upper())[:20], "title": folder.name})["id"]
    base = f"/courses/{course}"
    for file in sorted(folder.iterdir()):
        artifact = server.post(base + "/artifacts", data={"artifact_type": run_experiment.kind(file.name)},
                               files={"file": (file.name, file.read_bytes(), run_experiment.MIME.get(file.suffix.lower(), "text/plain"))})["id"]
        while server.get(base + f"/artifacts/{artifact}/status")["processing_status"] not in ("done", "error"):
            time.sleep(.3)
    run = server.post(base + "/run-audit")["run_id"]
    while server.get(f"/runs/{run}")["status"] == "running":
        time.sleep(.5)
    state = server.get(f"/runs/{run}")
    structure = server.get(base + "/structure")
    objectives = [o for m in structure["modules"] for o in m["objectives"]]
    findings, dimensions = [], {}
    for report in server.get(base + "/reports"):
        assessed = report["status"] not in ("needs_review", "failed")
        dimensions[report["report_type"]] = {"status": report["status"], "score": report["overall_score"] if assessed else None, "reason": report.get("reason")}
        for gap in server.get(f"/reports/{report['id']}")["gaps"]:
            findings.append({"dimension": report["report_type"], "gap_type": gap["gap_type"], "severity": gap["severity"], "description": gap["description"]})

    def mentions(finding, keywords):
        text = finding["description"].lower()
        if any(k in text for k in keywords):
            return True
        named = [o for o in objectives if o.get("code") and o["code"].lower() in text]      # "Objective EXT-3 ..." names it by code
        return any(k in o["text"].lower() for o in named for k in keywords)

    planted, used = [], set()
    for defect in defects:
        hits = [n for n, f in enumerate(findings) if f["dimension"] == defect["dimension"] and mentions(f, defect["keywords"])]
        elsewhere = [f["dimension"] for f in findings if f["dimension"] != defect["dimension"] and mentions(f, defect["keywords"])]
        used.update(hits)
        planted.append({**defect, "found": bool(hits), "by": sorted({findings[n]["gap_type"] for n in hits}),
                        "mentioned_in_other_dimensions": sorted(set(elsewhere))})
    other = [f for n, f in enumerate(findings) if n not in used]
    return {"course": folder.name, "run_status": state["status"], "run_error": state.get("error_message"), "dimensions": dimensions,
            "objectives": [{"code": o.get("code"), "bloom_level": o.get("bloom_level"), "text": o["text"]} for o in objectives],
            "findings": len(findings), "planted": planted, "found": sum(p["found"] for p in planted),
            "findings_not_matching_a_planted_defect": other, "trace_valid": server.get(f"/runs/{run}/trace/verify")["valid"]}


def render(report: dict) -> str:
    files = report["files"]
    problems = [c for c in files["cases"] if c["problem"]]
    lines = ["# Defect suite report", "",
             f"Run {report['started_at']}, mode {report['mode']}. Synthetic input made to provoke errors; a result here is a place to look.", "",
             "## Part 1: broken files", "",
             f"{len(files['cases'])} files, {len(problems)} with an unexpected outcome. Server healthy afterwards: {'yes' if files['server_healthy_afterwards'] else 'NO'}. "
             f"Stored names that leave the upload folder: {len(files['stored_names_leaving_the_folder'])}.", "",
             "| Case | File | Outcome | Detail | Problem |", "|---|---|---|---|---|"]
    for c in files["cases"]:
        detail = (c.get("detail") or "").replace("|", "/").replace("\n", " ")[:110]
        lines.append(f"| {c['id']} {c['what']} | `{c['file']}` | {c['outcome']} ({c.get('http', '-')}, {c.get('seconds', '-')} s) | {detail} | {c['problem'] or ''} |")
    lines += ["", "## Part 2: planted misalignments", ""]
    for course in report["courses"]:
        total = len(course["planted"])
        lines += [f"### {course['course']}", "",
                  f"Run: {course['run_status']}" + (f" ({course['run_error']})" if course["run_error"] else "") + f". Findings: {course['findings']}. "
                  + (f"Planted defects found: {course['found']} of {total}." if total else "No defect planted: every finding is a possible false alarm.") + "", "",
                  "Scores: " + ", ".join(f"{d.replace('_', ' ')} {'not assessable' if v['score'] is None else format(v['score'], '.0%')}" for d, v in sorted(course["dimensions"].items())) + ".", ""]
        if total:
            lines += ["| Planted defect | Dimension | Found | By finding type | Seen in other dimensions |", "|---|---|---|---|---|"]
            lines += [f"| {p['id']} {p['what']} | {p['dimension'].replace('_', ' ')} | {'yes' if p['found'] else 'NO'} | {', '.join(p['by'])} | {', '.join(d.replace('_', ' ') for d in p['mentioned_in_other_dimensions'])} |"
                      for p in course["planted"]]
            lines.append("")
        extra = course["findings_not_matching_a_planted_defect"]
        if extra:
            lines += [f"Findings that match no planted defect ({len(extra)}):", ""]
            lines += [f"- {f['dimension'].replace('_', ' ')} / {f['gap_type']} ({f['severity']}): {f['description'][:230]}" for f in extra]
            lines.append("")
        lines += ["Objectives the system extracted: " + "; ".join(f"{o['code']} [{o['bloom_level'] or 'no level'}] {o['text'][:70]}" for o in course["objectives"]) + ".", ""]
    return "\n".join(lines)


def run(out: Path, live: bool = False, echo=print) -> dict:
    manifest = json.loads((ROOT / "datasets" / "defects" / "manifest.json").read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with run_experiment.Server({}, live) as server:
        echo("broken files ...")
        files = run_files(server)
        courses = []
        for name, entry in manifest["courses"].items():
            echo(f"course {name} ...")
            courses.append(audit_course(server, ROOT / "datasets" / "defects" / name, entry["defects"]))
    report = {"started_at": started, "mode": "live" if live else "local_test", "files": files, "courses": courses}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(render(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="audit with the configured model (uses provider quota)")
    args = parser.parse_args(argv)
    print(render(run(args.out, args.live)))


if __name__ == "__main__":
    main()
