# Lectio — course alignment workbench

An improved implementation of the supplied FastAPI / Streamlit / LangGraph project (implementation revision 2). It audits four educational alignment dimensions, links findings to uploaded sources, generates reviewable drafts, and preserves lecturer decisions. The supplied Lectio exposé informed this implementation; see `docs/REQUIREMENTS_TRACEABILITY.md`.

**Status:** local end-to-end workflow tested. This is a research prototype with substantial hardening, not a certified production release. Live Groq inference returned HTTP 403 here; BGE inference, PostgreSQL/Docker and an external Paperclip deployment remain unverified. Local API, SQL vector retrieval, browser interactions and the installed dependency set were verified. See `docs/VERIFICATION.md` for exact results and remaining limits.

## Quick start — no API key or Docker required

Use Python 3.11 or 3.12. From this directory:

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Then:

```bash
python -m pip install -r requirements-local.txt
python scripts/setup_local.py
python scripts/run_local.py
```

Open **http://127.0.0.1:8501**. Sign in as `admin@example.org` with the generated `ADMIN_PASSWORD` stored in your private `.env`. API documentation: http://127.0.0.1:8000/docs. Stop both services with Ctrl+C.

This mode stores data in `data/lectio.db` and uploads in `data/uploads`. It uses deterministic source extraction, lexical hash-vector retrieval and visibly labelled draft templates. **No LLM inference takes place in local_test mode.** It is intended for demonstrations, regression tests and development; do not use its scores to claim AI research results.

`setup_local.py` never overwrites an existing `.env`. To switch configurations, back up your current configuration and data first. No original credentials, Git history, generated test database or uploaded source files are included in this deliverable.

## Lecturer workflow

1. Create a course in **Documents & upload** and upload documents with their correct artefact category.
2. Wait until each document reports `done`, or inspect its error and retry.
3. Open **Course workbench → Sources & model** to inspect exact extracted chunks. Extract learning-objective candidates and assessment text. Review objective wording and Bloom levels.
4. Enter planned weeks and topics in **Course Structure**. Automatic schedule inference is intentionally not claimed.
5. Run an audit in the workbench; refresh progress or cancel. Inspect all four dimensions, the outcome coverage matrix, source excerpts and limitations.
6. Use **Create drafts** for objectives, exercises, quizzes, module descriptions and targeted improvements. Select outcomes, specify constraints and compare up to three alternatives.
7. In **Approval Center**, edit, approve or reject. An edited draft remains `revised` until explicitly approved. Original drafts and decision history are retained.
8. Optionally apply an explicitly approved draft to the course model from **Review & export**, then rerun alignment. Original source documents remain preserved.
9. Export the course's reports, evidence and accepted/rejected proposals from **Review & export**.

Supported formats: PDF, DOCX, PPTX, Markdown, UTF-8 TXT, VTT. Corrupt/encrypted PDFs and invalid or active Office archives fail safely. OCR needs the optional Python `pytesseract` package and a Tesseract executable; empty scans without successful OCR remain errors.

## Explicit demo dataset

With the local API running, in another activated terminal:

```bash
python scripts/seed_demo.py
```

The sample is clearly named and contains an intentional missing graph-traversal teaching section. It is synthetic and must not be described as a real university evaluation corpus. Nothing is seeded automatically.

## Live deployment configuration

Copy `.env.example` to a private `.env` and set fresh database and JWT secrets, an optional bootstrap admin password (at least 12 characters), and `GROQ_API_KEY`. Set `RUNTIME_MODE=live`. `GROQ_MODEL` is configurable; verify its availability in your Groq account. Set `ARTIFACT_STORAGE_PATH=/app/uploads` for the supplied Docker volume.

```bash
docker compose up --build
```

The live stack is PostgreSQL, BGE embeddings, transactional SQL vector storage, BM25, cross-encoder reranking, LangGraph and Groq. ChromaDB was removed from the supported runtime because the audited release had four advisories without listed fixes. Source text and vectors now commit together in the existing database; retrieval enforces course ownership and source status. API keys are never shown by system status. Docker Compose binds services to loopback. Live model output is parsed and schema-checked; citations are restricted to retrieved sources. A valid citation proves source identity, not claim entailment: lecturers must still verify conclusions.

Use **one API worker** for this prototype's in-process scheduler and restart recovery. Audit admission uses database locks, but dispatch/cancellation/restart recovery remain local to an API worker. Multi-instance deployment still requires a durable external job queue before use. Use a reverse proxy with TLS, bounded request bodies (including chunked requests), authentication rate limits and network isolation before any public deployment. Refresh/revoke behaviour and deployment dependencies need a release security review.

Existing databases: the changes reuse existing ORM tables; portable JSON compiles to PostgreSQL JSONB. Startup creates missing tables but is not a schema-migration system. Back up existing data; run a PostgreSQL migration rehearsal before deployment. Current access policy is admin-global and course-owner for other roles; department-wide sharing must be explicitly modelled before enabling it.

## Paperclip and evaluation

See `docs/PAPERCLIP.md` for the process-adapter boundary and its verification limits. The inner LangGraph workflow remains in place. Full external Paperclip governance is still an integration task.

See `docs/EVALUATION.md` for labelling and metric collection. Run `python scripts/evaluate.py reviewed-data.csv` to calculate precision, recall, acceptance rate and instructor quality from real labels. No research measurements have been fabricated.

## Checks

```bash
python -m pytest -q
python -m compileall -q backend frontend scripts
python scripts/check_local_integration.py
```

For real browser QA, install `requirements-qa.txt`, run `python -m playwright install chromium`, then `python scripts/check_browser.py`. Screenshots remain in disposable `data/`, not in the delivered archive.

The last command requires `.env`, starts a localhost API, creates an explicit `UI-SMOKE` fixture, runs Streamlit AppTest over every page and stops its API process. It is a functional screen test. The separate browser script checks login, generation, approval and a fresh mobile session; it is not a full screen-reader/accessibility audit. Use it against a disposable development database only.

Documentation: baseline assessment, requirements matrix, verification results, known limitations and research evaluation protocol are in `docs/`.

## Live inference without a neural-model download

### Experimental OpenRouter provider

OpenRouter may be selected with `LLM_PROVIDER=openrouter`, a private
`OPENROUTER_API_KEY`, and an explicitly selected `OPENROUTER_MODEL` in `.env`.
Set `RUNTIME_MODE=live` and, to test without downloading neural models,
`RETRIEVAL_BACKEND=lexical`. The model must be available to the account and may
incur provider charges. `python scripts/verify_live.py` exercises an actual
synthetic inference request; the code has not been verified against a live
OpenRouter account. No inference occurs in `local_test` mode. Live requests send
selected course excerpts to the configured provider; check permission before
using private material. Provider support alone does not make lexical retrieval
multilingual. Do not commit or share `.env`.

To verify real Groq generation while using the lightweight local retrieval path, install `requirements-local.txt` and configure:

```dotenv
RUNTIME_MODE=live
RETRIEVAL_BACKEND=lexical
GROQ_API_KEY=<your private Groq key>
GROQ_MODEL=<an available model in your account>
```

Run `python scripts/verify_live.py`. It requires actual provider inference and strict source quotations; it refuses local_test mode. This lexical retrieval option is explicitly identified and does not claim neural semantics. Use `RETRIEVAL_BACKEND=neural` with `requirements.txt` for BGE and semantic boundary detection. On CPU-only machines install CPU PyTorch first to avoid CUDA downloads, as the backend Dockerfile does.

Configured Groq variants can be supplied as `GROQ_MODEL_VARIANTS=["model-a","model-b"]`; only allow-listed models may be selected in the UI. Model availability is checked separately; configuring a name does not verify it.
