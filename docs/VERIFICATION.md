# Revision 2 verification and remaining limits

Verified 2026-10-13, Linux/Python 3.12. Primary inputs: the supplied Lectio source archive and four-page exposé.

## Executed checks

- Python compilation: passed for backend, frontend and scripts.
- FastAPI and Streamlit startup: passed using explicit local-test configuration.
- Regression suite: **24 passed**, 16 warnings in the recorded final implementation run. Warnings concern deprecations; no test failure is hidden.
- All **11 Streamlit pages** passed AppTest against the localhost API using the explicit UI-SMOKE fixture.
- Real Chromium browser: login, dashboard, draft generation, approval and a fresh 390×844 mobile session passed. Desktop workbench and mobile dashboard captures were inspected; the mobile sidebar issue was corrected. Captures remain disposable and are not part of the archive.
- Actual dense SQL-vector operations: stored vectors, cosine retrieval, course isolation, artefact-type filtering and source deletion verified. These use explicit test vectors and do not pretend to be BGE inference.
- Paperclip protocol: identity, checkout, run-header use, human-review handoff and no-retry conflict handling verified against MockTransport contracts. No external Paperclip company is claimed.
- Dependency compatibility: `pip check` passed. Installed-runtime `pip-audit` reports **zero known vulnerabilities**; full result in DEPENDENCY_AUDIT.json.
- Full neural requirements: dependency resolution dry-run passed. Installation and model inference are separate, unexecuted checks.

Regression coverage includes the full upload/extraction/audit/generation/revision/approval/export journey, source formats and page/slide metadata, corrupt/encrypted/empty document failure, cross-course authorization, nested resources, duplicate cleanup, lockout/logout, quotation/schema rejection, Director routing, topic grouping, source-linked assessment/model editing, lecturer finding decisions, broker ranking/duplicates/conflicts, approved-draft application, stale audit detection, SQL vector isolation/deletion, Paperclip conflicts and human-review handoff, and evaluation calculations against explicit ground-truth labels.

## Live inference limits

The Groq models connectivity request using the key from the supplied archive returned HTTP 403 in this execution environment. No successful provider inference occurred, and this result does not establish whether the credential is valid outside this environment. Default local-test generation remains explicitly labelled as deterministic templates. Live code uses real Groq inference, strict educational schemas and exact quotation checks; `scripts/verify_live.py` refuses testing mode and is provided for an actual external inference check.

BGE model download/inference and cross-encoder reranking were not executed. Adaptive semantic-boundary logic was tested using a deliberately injected encoder; it is not a neural quality evaluation. Live mode can use clearly identified lexical retrieval while testing Groq independently, or neural BGE retrieval after installing its dependencies.

## Security scope

The first audit found 56 matches across 13 packages. Upgrades and the JWT-library replacement addressed the installed runtime. Installing ChromaDB for a real storage check exposed four unpatched advisories. ChromaDB was therefore removed from the supported runtime and Docker topology. Dense vectors now share the existing database's source transaction and access-control boundary. The final audit covers installed packages; it is not a security certification for uninstalled BGE dependencies, operating systems or all application code.

## Not completed or certified

- External Paperclip installation/provisioning and actual governed runs.
- PostgreSQL/Docker startup, existing-database migration rehearsal, backup/restore and public deployment.
- Actual Groq generation and neural retrieval quality.
- Load/stress testing, comprehensive keyboard/screen-reader accessibility, full browser cross-platform coverage, or formal security penetration testing.
- Real MAAI-course evaluation, lecturer ratings, ground-truth collection, calibrated confidence and the comparative research report. Tooling/protocol exists; no study results were invented.

Audit admission is database-locked, but job ownership/cancellation/restart recovery remain local to one API worker. Multi-instance deployment needs a durable job dispatcher. A reverse proxy should enforce TLS and bounded multipart/chunked request sizes and shared rate limits. Linux parsers have CPU/address-space/time limits; Windows requires OS/container memory controls for equivalent isolation. Exact dense retrieval is capped at 10,000 chunks per course.

Finding acceptance, generated-draft approval and applying an approved draft to the course model are separate explicit lecturer actions. Original uploads are preserved. Source and model changes invalidate previous audit views. Citation validation proves a real source and exact quotation; educational inference still requires human review.

This is a substantially completed and locally/browser-verified research implementation. Mandatory external verification and the real academic evaluation remain open, so full master-prompt completion or production certification is not claimed.

## Revision 3 (OpenRouter + multilingual retrieval), 2026-11-03

Verified here:
- Full suite: 40 passed, 1 skipped (`python -m pytest -q`); `compileall` clean; `docker compose config` valid.
- Real models, CPU: `BAAI/bge-m3` German->German and German->English retrieval and the multilingual cross-encoder ranked the expected passage first (`tests/test_german_retrieval.py`, 3 passed).
- OpenRouter client with mocked HTTP: cache reuse, no caching of invalid output, single bounded fallback, no fallback on 4xx, no request without a key.
- Stored vectors from a different embedding model are ignored in neural mode.
- Live OpenRouter inference: `scripts/verify_live.py` passed with `nvidia/nemotron-3-ultra-550b-a55b:free` (lexical retrieval; schema-valid draft, 1 citation validated, 1690 tokens). Both Gemma 4 free models returned upstream 429 at that time.

Not verified here:
- Docker image build / `docker compose up` (Docker daemon not running); PostgreSQL deployment; external Paperclip.
- Retrieval quality beyond the five-passage German/English fixture; no research metrics are claimed.
- End-to-end on the running app (SQLite, live mode, BGE-M3 neural retrieval, Nemotron Ultra): German syllabus/slides/exam upload -> embedding -> 4-dimension audit (9.5k tokens, all agents completed, real findings incl. "graph algorithms promised, hash tables delivered") -> German draft generation with a validated citation. The first run exposed truncated JSON (token cap), invented entity IDs and 429s; fixed (4000-token audit cap, truncation detection, unknown entity IDs dropped, one paused second pass, a failed model review no longer erases deterministic findings).
- Observed: a syllabus heading can land in a separate chunk, which makes the model report "header only, no objectives" as a low-severity finding. Not fixed.

### Revision 3b (speed, German/English extraction, derivation, analytics)
- UI lag: root cause was `http://localhost:8000` (about 2 s per request on Windows, IPv6 fallback) with 3 to 21 requests per page: Course workbench 40.9 s -> 0.8 s, other pages 2-20 s -> under 0.6 s (Streamlit AppTest, local API). Fix: `localhost` -> `127.0.0.1`, shared keep-alive pool, 3 s read cache for repeated GETs (cleared by any write, never for run/status polling). Inside Docker the `backend` hostname is unaffected.
- "Unknown" scores: a German syllabus produced no objectives (English-only patterns), so every agent had nothing to audit. Now German and English outcome/schedule phrasing is extracted and, if nothing is stated, outcomes are derived from the materials. Checks that still lack data say why ("upload an exam...", "add a schedule...") and are excluded from averages instead of counted as 0%.
- English dataset (`datasets/en_algorithms`, no stated outcomes): live run produced 6 outcomes and all four dimensions scored (84% / 64% / 57% / 33%). German dataset (`datasets/de_algorithmen`, stated outcomes): 3 outcomes extracted, all four scored, 74 s.
- Live re-check on 2026-11-04 (after the quota reset), `datasets/en_algorithms`: first run took 8 min and only 1 of 4 model reviews succeeded (invented evidence IDs rejected a whole review; hidden reasoning exhausted the token cap; an empty reply caused pointless retries). Fixed: findings citing unsupplied evidence are dropped individually (counted as `discarded_unverifiable`), audit cap 6000 tokens with a "max 5 short findings" instruction, cut-off replies fall back to the other model without a pause pass. Second run: 3 min 49 s, **4 of 4 live reviews succeeded** (26k tokens; 2 unverifiable findings dropped), scores 71% / 64% / 67% / 57%, 3 outcomes derived.
- Test suite: 49 passed, 1 skipped.
- Automatic drafts (2026-11-04, English course): audit 1 produced 4 drafts (quiz questions, revised CLO, assessment question; 2-3 citations each) from the worst gaps; an identical re-audit took 97 s, used 0 tokens and added no duplicates.

### Projected scores after approved drafts (2026-11-04)
- `GET /courses/{id}/projection`, `services/projection.py`; shown on Alignment Reports and, compactly, after approving in the Approval Center. Verified scores are never changed; only a full audit sets them.
- Method: each open gap a draft can address is re-checked against approved (or edited-and-approved) drafts with the audit's similarity measure (BGE-M3 cosine, bar 0.55; hash-vector bar 0.30 in test mode). Cognitive-level gaps need a draft within one level of the taught content, and one draft closes at most one such gap. Delivery gaps, coverage gaps and model-review findings are never closed by a draft. Score = verified + (100% - verified) x severity-weighted share of gaps addressed (critical 2, warning 1, info 0.5), so 100% needs every gap closed.
- Live, English course, 4 approved drafts: Content<->Assessment 64% -> 75% (4 of 13 addressed), Metadata<->Assessment 67% -> 73% (1 of 5), the other two unchanged. First version let one quiz close three level gaps; found on this run and fixed.
- Cost: no LLM calls. First projection after new approvals embeds the draft and gap texts once (about 14 s for 20 texts on this CPU), then served from memory (0.09 s). The embedding model is warmed in the background at server start.
- Tests: 56 passed, 1 skipped.

### Review findings, headings, projection cap (2026-11-04)
- Model review now returns problems as findings and good news in a separate `confirmed` list (stored under `live_review.confirmed`, never counted as gaps). Findings carry `fixable_by` (objective / assessment / none); fixable ones get gap types `live_missing_objective` / `live_missing_assessment`, which the draft generator handles and the projection re-checks against matching approved drafts.
- Chunker keeps a heading with the text under it (a heading-only chunk gave the model false "empty section" findings).
- Live, fresh English course: confirmations separated (3-4 per dimension), Content<->Delivery gaps 3 -> 0, Metadata<->Content gaps 3 -> 1, syllabus chunks 4 -> 2 (heading merged), a CLO draft generated for the dynamic-programming finding. With 3 drafts approved the uncapped projection reached 95% and 100% (single minor finding closed), which over-promised; projections are now capped at 95% and share the shortfall over at least three warning-weights.
- Tests: 60 passed, 1 skipped.
