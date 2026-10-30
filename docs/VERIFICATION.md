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
