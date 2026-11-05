# Permanent development and security rules

These apply to every change. If a rule must be broken, record the reason in `Memory.md`.

## Product rules
1. **Nothing writes back to course systems or to uploaded sources.** Applying a draft changes only the Lectio course model, after explicit approval, and marks earlier results stale.
2. **Every generated item is a suggestion** and is labelled as such. The lecturer's decision (approve, edit, reject) is recorded with the original text.
3. **No fabricated evidence.** Citations must refer to chunks that were supplied to the model; findings citing anything else are dropped. Never present absence of evidence as proof of an error.
4. **Never invent metrics, results, quotes or sources** in code, docs or the UI. Scores are heuristics and are labelled so; projected scores are labelled as projections.
5. **Language parity.** New text handling must work for German and English.

## Security rules
1. **Secrets never enter Git.** `.env`, keys and passwords stay local; `.env.example` holds placeholders only. Scan tracked files for keys before any push.
2. **Authenticate everything.** Every data route requires a valid token (only login, refresh and health are open); roles are enforced server-side; users reach only courses they own (admins excepted).
3. **Treat documents as untrusted data.** Prompts say so; model output is parsed and schema-validated; document text is never executed or rendered as HTML (escape dynamic text).
4. **Uploads are bounded and checked**: size, extension, MIME and signature, archive expansion, parsing in a subprocess with a timeout.
5. **Course isolation**: every retrieval and query is scoped to the course and to processed sources.
6. **Rate limits and lockout** on login; refresh tokens rotate and are revocable.
7. **Dependencies**: pin versions, audit with `pip-audit` before a release, remove packages with unfixed advisories.
8. **Provider keys are never shown** by status endpoints or logs.

## LLM rules
1. Prefer deterministic code; call a model only for semantic analysis or generation.
2. Cache only validated output; never replay a failed answer.
3. At most one fallback model per call and one paused second pass for transient errors. No unbounded retry or agent loops.
4. Cap output tokens; retrieve only relevant chunks; do not send whole documents.
5. Daily-quota errors stop immediately with a clear message.
6. Do not regenerate when a valid result exists; do not create duplicate drafts.

## Engineering rules
1. **Tests before merge.** Run `python -m pytest -q`; add a test for every bug fixed. Do not edit a test to make it pass.
2. Keep changes small and in the existing style; avoid unrelated refactors.
3. Preserve line endings of existing files (no whole-file diffs).
4. Database changes must keep existing data; document the schema change in `DATABASE_SCHEMA.md` (the app creates missing tables but is not a migration system).
5. Real-provider and real-model checks are run, not only mocks, whenever credentials and network allow; record the result in `TESTING_REPORT.md`.
6. **Update the docs in the same change**: `Tasks.md`, `DEVELOPMENT_PROGRESS.md`, `TESTING_REPORT.md`, and any document whose facts changed.
7. Report what was not verified, not only what was.
