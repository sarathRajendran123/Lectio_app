# Lectio: working guide for AI assistants

Read this whole file before changing anything. It tells you what the project is, where things live, how to run and test it, the rules the code already follows, and the mistakes that are easy to make here. The deeper documents are in `docs/`; this file tells you which one to open for what.

## 1. What this project is

Lectio is a research prototype for a university project (MAAI application project). A lecturer uploads the documents of one course (syllabus, slides, lecture transcript, exam). Lectio then:

1. Builds a course model from the documents: learning objectives, weekly schedule, assessment questions.
2. Audits four alignment dimensions and scores each one:
   - `metadata_content`: do the stated objectives match what is taught?
   - `content_assessment`: does the exam test what is taught?
   - `metadata_assessment`: is every objective assessed?
   - `content_delivery`: does the lecture transcript cover what the slides planned?
3. Shows each finding with the exact source excerpt it rests on.
4. Drafts fixes (objectives, quiz questions, exercises) that the lecturer approves, edits or rejects.
5. Keeps a tamper-evident log of what every agent and model call did.

Three ideas shape almost every decision in the code. Keep them in mind, because most wrong changes violate one of them:

- **The lecturer decides.** Everything generated is a suggestion. Nothing is written back to the uploaded files or to any course system. Applying a draft changes only Lectio's own course model, and only after an explicit approval.
- **No invented evidence.** A finding or a draft may only cite text chunks that were actually given to the model. Output that cites anything else is dropped. A missing document is "insufficient evidence", never proof of a problem.
- **Honest numbers.** Scores are heuristics and are labelled so. Nothing in code, UI or docs may state a metric, result or quote that was not measured. Docs say what was not verified.

It works in German and English, and every text-handling change has to work in both.

## 2. How it is built

| Layer | Technology | Where |
|---|---|---|
| Frontend | Streamlit 1.65, talks to the API over REST with a JWT | `frontend/` |
| API | FastAPI, async SQLAlchemy 2 | `backend/main.py`, `backend/api/v1/routes/` |
| Database | SQLite (`aiosqlite`) locally, PostgreSQL 15 (`asyncpg`) in Docker | `backend/db/` |
| Orchestration | LangGraph, hub and spoke: the Course Director routes to every agent and back | `backend/agents/` |
| LLM | OpenRouter over `httpx`, free models, one fallback model | `backend/llm/openrouter.py` |
| Retrieval | BGE-M3 embeddings + BM25 + multilingual cross-encoder reranker; vectors stored in the chunk row | `backend/rag/`, `backend/vector_db/` |

### Two runtime modes (know which one you are in)

`RUNTIME_MODE` in `.env` switches the whole behaviour:

- **`local_test`** (what `setup_local.py` creates and what the tests use): no LLM call ever happens. Retrieval is word overlap plus 256-bucket hash vectors (`rag/lexical.py`). Drafts are a fixed template starting "DETERMINISTIC TEST DRAFT". `RAGService.get_instance()` returns `LocalRAGService`.
- **`live`**: real OpenRouter calls and, with `RETRIEVAL_BACKEND=neural`, the real embedding and reranker models (about 2.8 GB download). `RETRIEVAL_BACKEND=lexical` gives live generation with the lightweight retrieval.

Consequence: a green test suite tells you nothing about model behaviour or cross-language retrieval. Say so in your report.

### What happens in an audit

```
POST /api/v1/courses/{id}/run-audit            (routes/workflow_routes.py)
  admission.admit_audit        database lock; one audit per course; capacity limit
  course_model.extract_course_model   objectives, schedule, questions from chunks
  auto_derive.derive_missing_objectives
  workflow_service.start_run   creates AgentRun, starts a SUBPROCESS:
      python -m services.workflow_worker <run> <course> <user>
        LangGraph (agents/graph/workflow.py), every node goes through execute_agent():
          course_director           loads course, intent, constraints; routes
          4 dimension agents        each: agent.run() rule-based checks
                                          audit_checks.enrich()   more rule checks
                                          live_review.augment()   model review (live only)
                                          constraints.apply_dismissals()
          content_generation_agent  capped drafts, each through stakeholder_gate.produce()
          stakeholder_agent         writes reports, gaps, drafts to the database
        prints the final state as ONE JSON document on stdout
  parent reads stdout, updates the run, emits run_finished, anchors the trace
```

Document parsing uses the same subprocess pattern (`services/safe_parser.py` starts `services/parser_worker.py` with a timeout).

### Governance layer (added in Phase 1)

- `services/trace.py`: append-only, hash-chained `trace_events`. Database triggers refuse UPDATE and DELETE. Chain heads are also written to `trace_anchors.jsonl` outside the database.
- `services/intent.py`: the lecturer's course intent, versioned. A save adds a version.
- `services/constraints.py`: lecturer decisions become rules (`avoid`, `prefer`, `require`). A rule is replaced or retired by a new row that points at it.
- `services/stakeholder_gate.py`: every draft is scored before the lecturer sees it; weak drafts are retried a bounded number of times and otherwise shown with a warning.
- `services/projection.py`: projected scores after approved drafts, no model calls, capped at 95%.

## 3. Folder map

```
backend/                 run with backend/ as the import root (see section 5)
  main.py                app, middleware, router registration, start-up recovery
  config.py              every setting (pydantic-settings, read from .env)
  api/v1/routes/         auth, courses, artifacts, admin, workflow_routes (runs, reports, approvals),
                         workbench (evidence, generate, apply, export, projection), governance (intent, rules, trace)
  api/v1/middleware/     audit log of data-changing calls, login rate limit
  auth/                  JWT, bcrypt, role hierarchy: lecturer < coordinator < dept_head < admin
  agents/                course_director, four dimension agents, audit_checks (rule checks),
                         live_review (model review), content_generation_agent, stakeholder_agent, quality_broker
  agents/graph/          state.py (the workflow state and dataclasses), workflow.py (graph + execute_agent)
  services/              business logic: admission, course_model, auto_build, auto_derive, delivery_check,
                         projection, stakeholder_gate, stakeholder_view, trace, intent, constraints,
                         upload_service, safe_parser, parser_worker, workflow_service, workflow_worker
  rag/                   parsers/ (pdf, docx, pptx, transcript), chunking/, embedding/, retrieval/,
                         generation/ (grounded_generator, draft_schema), lexical.py, local_service.py, rag_service.py
  vector_db/             sql_vector_store.py (exact cosine over vectors in the chunk row)
  knowledge/             bloom_classifier, outline_rules (outcome and schedule line rules), *_eval metric code
  llm/openrouter.py      the only place that talks to the model provider
  db/models/             ORM models; db/migrations/versions/001_initial.sql is the PostgreSQL DDL
  db/repositories/       course, artifact, user queries
frontend/
  app.py                 theme CSS, sidebar, page list and dispatch, dashboard
  views/_*.py            one file per page
  api_client/lectio_client.py   the only HTTP client; components/ui_components.py shared widgets
  utils/session_utils.py get_client(), safe_api_call()
tests/                   pytest; conftest.py sets local_test mode and a temp SQLite database
scripts/                 setup_local, run_local, seed_demo, run_dataset, check_local_integration, check_ui,
                         check_browser, verify_live, evaluate*, reembed
datasets/                synthetic sample courses (en_algorithms, de_algorithmen) and labelled evaluation sets
docs/                    Rules.md, Architecture.md, Design.md, Memory.md, Tasks.md, DEVELOPMENT_PROGRESS.md,
                         TESTING_REPORT.md, DATABASE_SCHEMA.md, EVALUATION.md, SECURITY_CHECKLIST.md, PRD.md ...
docker/, docker-compose.yml   live stack (never verified end to end)
data/                    local database and uploads; git-ignored; never commit, never delete without asking
.env                     secrets; git-ignored; do not print its values
```

`docs/Rules.md` is the binding rule set. `docs/Memory.md` records decisions already made. Read both before proposing a change of direction.

## 4. Commands

The machine is Windows with PowerShell. Use the virtual environment's Python. Python 3.11 to 3.13 work (the venv here is 3.13).

Set up once:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.venv\Scripts\python.exe scripts\setup_local.py
```

`setup_local.py` refuses to overwrite an existing `.env`. Leave it that way.

Run the app (API on 8000, UI on 8501, both on loopback, stop with Ctrl+C):

```powershell
.venv\Scripts\python.exe scripts\run_local.py
```

Open http://127.0.0.1:8501. The login is `ADMIN_EMAIL` with `ADMIN_PASSWORD` from `.env`. API docs: http://127.0.0.1:8000/docs.

Test:

```powershell
.venv\Scripts\python.exe -m pytest -q
$env:LECTIO_SKIP_MODEL_TESTS = "1"; .venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q tests\test_projection.py
.venv\Scripts\python.exe -m pytest -q -k "delivery"
.venv\Scripts\python.exe -m compileall -q backend frontend scripts
```

- The suite takes three to four minutes (many tests run whole audits through the worker subprocess), so run it in the background or with a long timeout. Do not conclude it hangs.
- Two files (`test_german_retrieval.py`, `test_retrieval_eval.py`) load the real embedding and reranker models when `sentence-transformers` is installed. `LECTIO_SKIP_MODEL_TESTS=1` skips those six tests and runs offline.
- One PostgreSQL test (ORM column types against `001_initial.sql`) is skipped unless `LECTIO_TEST_POSTGRES_DSN` is set, so "1 skipped" is the normal result (7 with the model tests skipped).
- Warnings about `database is locked` in a background thread can appear in the concurrency tests on SQLite. Look at the pass and fail counts, and report such warnings instead of hiding them.
- There is no linter, formatter or type checker configured. `compileall` is the syntax check. Do not add or run a formatter.

Check the UI (needs `.env`, port 8000 free, and uses your development database: it creates a course called `UI-SMOKE`):

```powershell
.venv\Scripts\python.exe scripts\check_local_integration.py
```

Other scripts (each needs the local API running unless noted):

| Command | Purpose |
|---|---|
| `python scripts/seed_demo.py` | load the synthetic demo course |
| `python scripts/run_dataset.py datasets/en_algorithms` | upload a sample course, audit it, print results |
| `python scripts/verify_live.py` | one real provider call; needs `RUNTIME_MODE=live` and a key; uses daily quota |
| `python scripts/evaluate_bloom.py`, `evaluate_extraction.py`, `evaluate_retrieval.py [--neural]` | measured figures for `docs/EVALUATION.md` (no API needed) |
| `python scripts/reembed.py` | re-embed stored chunks after `EMBEDDING_MODEL` changes |
| `python scripts/check_browser.py` | Playwright browser check; needs `requirements-qa.txt` and `python -m playwright install chromium` |
| `docker compose up --build` | live stack; has never been verified, say so if you touch it |

There is no build step for local work. "Build" means the Docker images.

## 5. Coding rules

**Imports.** `backend/` is the import root, not the repository. Write `from config import settings`, `from services import trace`, `from db.models.course import Course`. Never `from backend.config import ...`. The frontend's root is `frontend/` (`from views._upload import ...`). Many imports are deliberately inside functions to avoid import cycles and to keep heavy models from loading in test mode; keep them there.

**Match the file you are in.** Two styles coexist: the original files (spaces around `=`, aligned columns, `# ── Section ──` banners, double quotes) and the denser later files (`a=b`, single quotes, several statements per line). Write new lines in the style of the surrounding file. Never reformat or rewrite a whole file; change the lines the task needs. Line endings are LF (one file, `docs/DATABASE_SCHEMA.md`, is mixed: leave it as it is).

**Settings.** Every tunable lives in `backend/config.py` as a typed field with a default and a one-line comment. Read it through `settings`, never `os.environ`, in backend code. Add operator-facing ones to `.env.example` with a placeholder value.

**Sync and async.** Routes and services are async. Agents are synchronous (LangGraph nodes) and reach the database with `self._run_async(coro)`, which runs the coroutine on its own thread and loop. Inside agent code open your own session with `AsyncSessionLocal()`; never pass a request's session into an agent or a thread. The engine uses `NullPool` on purpose for this reason. Blocking work in a route goes through `asyncio.to_thread`. Work handed to a thread pool must be wrapped in `trace.bind(...)` or it loses the trace context.

**Subprocess protocol.** `workflow_worker.py` and `parser_worker.py` return their result as one JSON document on stdout; the parent does `json.loads(stdout)`. Nothing else may be written to stdout on those code paths: no `print`, no call to `setup_logging` (it logs to stdout). Use `logger`.

**Routes.** Every data route takes `user=Depends(get_current_user)` and calls `_assert_course_access(course_id, user, db)` (or `_content_access` / `_run_access`) before touching data. Every query is filtered by course. Retrieval only uses chunks whose artifact has `processing_status == 'done'`. Only login, refresh and `/health` are open. Request bodies are pydantic models with length limits.

**Changing the course model.** Any route that changes sources or the course model calls `services.admission.assert_idle` first (no change during a running audit) and `services.model_version.touch_course` after (this is what marks earlier reports stale).

**Database.**
- There is no migration system. Start-up runs `create_all`, which creates missing tables and nothing else. A new column on an existing model does not appear in an existing database. If you change a model: update `backend/db/migrations/versions/001_initial.sql` by hand (the test that compares it with the ORM only runs with a PostgreSQL DSN, so nothing catches a mismatch for you), update `docs/DATABASE_SCHEMA.md`, and tell the user their existing `data/lectio.db` needs handling. Prefer a new table to a new column.
- JSON columns use `JSONB` from `db/types.py` so they work on both engines.
- Insert-only tables: `trace_events`, `course_intents`, `lecturer_constraints`, `approvals`, `finding_decisions`. A change is a new row (new version, superseding rule). Never write UPDATE or DELETE for them and never weaken the triggers.

**Model calls.** All calls go through `OpenRouterChat.invoke(messages, validate=...)`. Pass a `validate` function that raises on unusable output: only validated output is cached, and a failed answer must never be cached or replayed. The limits are fixed by `docs/Rules.md`: at most one fallback model, one paused second pass for transient errors, drafts capped per audit, output tokens capped, retrieved chunks instead of whole documents. The free tier allows about 50 requests a day, so an extra call per item is a real cost. Prefer deterministic code; use the model only for semantic judgement or generation.

**Model output is untrusted.** Parse it, validate it against a pydantic schema (`draft_schema.parse_draft`, `live_review.Review`), and check every cited id against the chunks you supplied. Document text in prompts is labelled as untrusted data. Do not relax a validator to let more output through.

**Trace.** Record what happened with `trace.emit` (sync code) or `await trace.aemit(..., db=db)` (inside a request). Payloads hold ids, counts, outcomes and fingerprints (`trace.fingerprint(text)`), never prompt text, document text or secrets.

**Gap types are a contract.** A `gap_type` string and the wording of its description are read elsewhere: `content_generation_agent` (which gaps get drafts, `DRAFT_TYPE`, the dispatch table), `projection.py` (regexes over the description, `CHECKED_TYPES`), `constraints.finding_fingerprint` (identity of a dismissed finding), `stakeholder_view.py` (plain-language text per type). Before renaming a gap type or rewording a description, search for the type name across `backend/` and update every reader.

**Tests.** `python -m pytest -q` before and after. Add a test for every bug fixed and every behaviour added. Name a test after the behaviour it proves, as the newer files do (`test_a_topic_taught_in_different_wording_is_not_flagged`). Tests share one app and one database per session (`conftest.py`), so use a unique course code and do not assume an empty database. The default suite never touches the network: mock the provider by monkeypatching `httpx.post` or the agent's `_invoke`, and change settings with `monkeypatch.setattr(settings, ...)`. Never edit a test, a threshold or an expected value to turn a failure green; find the cause. If a test's assumption is truly outdated, change it and say so in `docs/TESTING_REPORT.md`.

**Docs are part of the change.** Update `docs/Tasks.md`, `docs/DEVELOPMENT_PROGRESS.md` and `docs/TESTING_REPORT.md` in the same change, plus any document whose facts changed. The docs are written in plain sentences with measured numbers and an explicit "not verified" or "limits" part. Keep that tone.

**Git.** Work happens on `feat/openrouter-multilingual`. Commit or push only when the user asks. Never stage `.env`, `data/`, `*.pdf`, `*.zip`. Commit messages are one plain sentence saying what changed.

## 6. Design rules (Streamlit UI)

The look is deliberately plain: light paper background, one teal accent, large type. A dark "Console" redesign was built and rejected as over-designed (`redesign/hallmark-ui` branch, `docs/screenshots-hallmark/`). Do not restyle the app, add a theme switch or bring that work back unless the user asks.

| Token | Value |
|---|---|
| Text, headings | `#182B3A` |
| Accent (primary buttons, selection) | `#24695D` |
| Page background | `#FAF9F6` |
| Sidebar | `#EDF1EF`, border `#DCE3DF` |
| Card | white, border `#DEE4E0`, radius 12 px |
| Focus ring | 3 px `#B87928` |
| Type | root 112.5% (18 px); h1 2.5 rem, h2 1.9 rem, h3 1.45 rem; 106% under 700 px |

Colours and sizes are set in two places only: `.streamlit/config.toml` and the `<style>` block at the top of `frontend/app.py`. A few older inline styles use other colours; do not copy them into new code.

Rules for every page:

1. **Suggestions are labelled, decisions are visible.** Approve, Edit draft and Reject are always shown. A draft that failed the internal quality check shows a warning with the reasons; never display it as passed.
2. **Say why.** A dimension without data is "Not assessable" with the reason from the API, never "Unknown" and never 0%. A projected score is labelled as a projection beside the verified score. Scores carry the notice that they are heuristic indicators, not probabilities.
3. **Show the evidence.** A finding shows its excerpt, document and page or slide. Citations show the quoted text (`render_citations`).
4. **Four states for every data region:** loading (spinner), empty (what belongs here and where to add it), error (the API's message via `st.error`), full.
5. **Words, not colour, carry meaning.** Statuses are text ("WARNING", "needs review").
6. **Destructive actions take two clicks** (`confirm_action` in `ui_components.py`).
7. **Plain language**, German and English content shown as written. No emojis, no decoration.
8. **Escape dynamic text.** Anything from a document, a model or a user that goes into `st.markdown(..., unsafe_allow_html=True)` must have `<` and `>` escaped first, as `_approval_center.py` does. Prefer `st.write` / `st.text`.

How pages are written:

- All HTTP goes through `LectioClient`. Call it as `data, err = safe_api_call(client.method, args)`, show `err` with `st.error`, and handle `data` being `None`. For newer endpoints use `client.workbench(path, method, data)`.
- A new page is a `show_*` function in `frontend/views/_name.py`, added to `PAGES` and to the dispatch chain in `app.py`.
- Widgets need stable unique keys built from the record id (`key=f"app_{content_id}"`).
- Use `width="stretch"` on buttons and dataframes (this Streamlit version; not `use_container_width`).
- The client caches GETs for 3 seconds and clears the cache on any write. Polling URLs containing `/runs/` or `/status` are never cached. Do not add another cache layer.
- The backend URL uses `127.0.0.1`, not `localhost` (two seconds slower per request on Windows).

## 7. Mistakes a weaker model makes here, and how to avoid each

| # | Mistake | What goes wrong | Do this instead |
|---|---|---|---|
| 1 | Writing code before reading the callers | The change compiles but breaks a reader elsewhere (gap types, state keys, finding fingerprints) | Open the file, then search for every use of the function, state key or string you change |
| 2 | `from backend.x import y`, or running from the wrong folder | `ModuleNotFoundError` in the app or the worker subprocess | Import relative to `backend/`; run through `scripts/run_local.py` or `uvicorn main:app --app-dir backend` |
| 3 | Adding `print` or stdout logging in agent, service or parser code | The worker's JSON on stdout is corrupted; every audit or upload fails with a parse error | Use `logger`; keep stdout for the single JSON result |
| 4 | Calling `asyncio.run` or `await` inside an agent, or sharing a session across threads | "event loop is already running", "handler is closed", SQLite locks | `self._run_async(...)` with a fresh `AsyncSessionLocal()`; keep `NullPool` |
| 5 | Adding a column to an existing model and stopping there | Works in tests (fresh database), crashes on the user's existing database and on PostgreSQL | Follow the database rule in section 5; say plainly what existing data needs |
| 6 | Deleting `data/lectio.db` or `data/uploads` to "reset" | The user's courses, audits and trace log are gone | Ask first. Tests use their own temp database and never need this |
| 7 | Updating or deleting a trace, intent, constraint or decision row | Triggers abort it, or history is silently lost | Insert a new version or a superseding row |
| 8 | Believing green tests prove live behaviour | Tests run in `local_test`: no model, word-overlap retrieval that cannot match a German query to an English passage | Report "tested in local_test with mocks; not run against a live model", or run `verify_live.py` if the user agrees to spend quota |
| 9 | Editing a test, lowering a threshold or loosening a validator to get green | Hides a real defect; breaks the "no invented evidence" guarantee | Find the cause. Findings and drafts that cite unsupplied evidence are dropped by design |
| 10 | Adding a retry loop, a per-item model call or a "self-check" call | Burns the 50-requests-a-day free quota, breaks the bounded-retry rule | Stay inside the existing limits; batch into one call; prefer rules |
| 11 | Calling the provider directly with `httpx` or another SDK | No cache, no fallback, no quota handling, no trace event | Use `OpenRouterChat.invoke(..., validate=...)` |
| 12 | Caching or accepting unvalidated model output | A bad answer is replayed forever at zero tokens | Validation function raises; nothing is cached on failure |
| 13 | Putting prompt, document text or a key in a trace payload or log line | Privacy and secret leak in an append-only log that cannot be cleaned | Fingerprints, ids, counts only |
| 14 | A new route without the access check, or a query without the course filter | One lecturer reads another's course | `get_current_user` + `_assert_course_access`; filter by `course_id`; add an isolation test like those in `test_security.py` |
| 15 | Changing objectives, assessments or sources without `assert_idle` and `touch_course` | Edits during a running audit; old reports not marked stale | Call both |
| 16 | English-only text handling: `[a-z]+`, English stop words, English verb lists | German words split at umlauts (this exact bug was found and fixed in the BM25 tokeniser), German courses score wrongly | Use `\w` with Unicode, add the German case and a German test |
| 17 | Renaming a gap type or rewording its description | Drafts stop being generated, projections stop matching, dismissed findings come back | Treat it as a contract (section 5) |
| 18 | Showing 0%, "Unknown" or a red error for missing material | Tells the lecturer something is wrong when the data is only missing | `needs_review` status with a `reason`; "insufficient evidence" wording |
| 19 | Inventing a number, calling a heuristic "accuracy" or "confidence", writing "verified" for something not run | Violates the project's core rule; the supervisor reads these docs | Only measured figures, with the date and what the key was; otherwise write "not run" |
| 20 | "Tidying" deliberate decisions | Regressions in things that were measured and decided | Leave these alone unless asked: `NullPool`, the 95% projection cap and three-weight minimum, one draft closing one level gap, dropped unverifiable findings, the legacy `chroma_id` column, the unchanged rank fusion (recorded in `docs/EVALUATION.md`, not to be tuned on the synthetic set), single API worker |
| 21 | Rendering model or document text as HTML | Script injection in the lecturer's browser | Escape, or use `st.write` / `st.text` |
| 22 | Reformatting a file, running a formatter, rewriting a file to change three lines | A diff nobody can review; mixed styles are intentional history | Edit only the needed lines in the file's own style |
| 23 | Restyling the UI, adding dark mode, new colours, emojis or cards | The user already rejected a heavier redesign | Use the tokens in section 6; ask before any visual change beyond the task |
| 24 | Claiming a UI change works because the file compiles | Streamlit errors only show at render time | Run `check_local_integration.py` or open the page; otherwise report it as not opened |
| 25 | Starting `uvicorn` with `--workers` or `--reload`, or a second server on port 8000 | The scheduler, cancellation and restart recovery are single-process; start-up marks running audits as failed | One API process. Check whether the user already has the app running before starting one |
| 26 | Changing `EMBEDDING_MODEL` or the chunk format without re-embedding | Stored vectors are ignored (by design), retrieval returns nothing | Run `scripts/reembed.py` and say so |
| 27 | Reading `.env` aloud, committing it, or pasting a key into a doc or test | Secret leak | Never print secret values; tests use obviously fake keys |
| 28 | Using bash syntax in PowerShell (`VAR=1 cmd`, `&&`) or `localhost` | Command fails or is slow | `$env:VAR = "1"; cmd`, `127.0.0.1` |
| 29 | Committing, pushing, adding dependencies or creating extra files without being asked | Unwanted history and unpinned packages | Ask. New packages are pinned in the right `requirements-*.txt` and audited |
| 30 | Finishing without updating the docs, or reporting only the successes | The next session works from wrong facts | Update the three progress documents and list what was not verified |

## 8. How to work on a task here

1. Read the request, then read the files it touches and their callers. If the request conflicts with `docs/Rules.md` or a decision in `docs/Memory.md`, say so before coding.
2. Run the test suite first and note the pass count. That is your baseline.
3. Make the smallest change that does the job, in the existing style. Reuse what exists (`safe_api_call`, `_assert_course_access`, `trace.emit`, `stakeholder_gate.produce`, `classify_text`) before writing something new.
4. Write the test with the change. Cover German when text is involved.
5. Run the checks in section 9. If something fails, read the error and fix the cause.
6. Ask before anything that is hard to undo or leaves the machine: deleting data, changing the schema of an existing database, spending provider quota, committing, pushing.
7. Report in plain sentences: what changed and where, what you ran and its result, what you did not verify, and anything you noticed but left alone.

## 9. Checklist before saying a task is done

Run through all of it. If an item does not apply, you should be able to say why.

- [ ] I read every file I changed, and searched for other users of every function, state key, setting and gap type I touched.
- [ ] `python -m compileall -q backend frontend scripts` prints nothing.
- [ ] `python -m pytest -q` passes, with at least as many passing tests as my baseline, and I did not weaken any test or threshold to get there.
- [ ] There is a new test for each bug fixed or behaviour added; text handling has a German case.
- [ ] If I touched the frontend: `scripts/check_local_integration.py` ran, or I opened the page, or my report says the page was not opened.
- [ ] If I touched a route: it has the auth dependency, the course access check, the course filter, and (for changes to the course model) `assert_idle` and `touch_course`.
- [ ] If I touched a model call: it goes through `OpenRouterChat.invoke` with a validator, adds no retry beyond the existing limits, and my report says whether it ran live or only with mocks.
- [ ] If I touched a database model: `001_initial.sql` and `docs/DATABASE_SCHEMA.md` match it, and I told the user what an existing database needs.
- [ ] No `print` on worker paths; no prompt text, document text or secret in logs or trace payloads; no secret in any tracked file.
- [ ] Insert-only tables are still insert-only.
- [ ] UI text is plain, statuses are words, missing data shows a reason, generated items are labelled as suggestions, dynamic text is escaped.
- [ ] The diff contains only what the task needs: no reformatting, no unrelated refactor, no stray files, line endings unchanged.
- [ ] `docs/Tasks.md`, `docs/DEVELOPMENT_PROGRESS.md` and `docs/TESTING_REPORT.md` are updated, and any other document whose facts changed.
- [ ] Every number I wrote anywhere came from a command I ran in this session.
- [ ] Nothing was committed, pushed, deleted or sent to an outside service without the user's request.
- [ ] My final message states what was done, what was verified and how, and what was not verified.
