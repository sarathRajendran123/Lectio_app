# Tasks

Status: Done, In progress, Open. Update this file with every change (see `Rules.md`).

## Done
| Area | Task |
|---|---|
| Ingestion | Parsers for PDF, DOCX, PPTX, MD, TXT, VTT with safety limits; headings kept with their text |
| Retrieval | BGE-M3 embeddings, BM25, multilingual reranker; embedding cache; stale-vector guard; `scripts/reembed.py` |
| LLM | OpenRouter client, validated-result cache, one fallback, daily-quota handling, reasoning hint |
| Course model | Outcome and schedule extraction in English and German; derived outcomes when none are stated |
| Audit | Four dimensions; concurrent model reviews; confirmations separated from problems; unverifiable findings dropped |
| Scores | "Not assessable" with a reason instead of "Unknown"; excluded from averages |
| Drafts | Automatic drafts for the worst gaps (capped); model findings that need an objective or an assessment get draftable types; no duplicate drafts |
| Projection | Projected scores from approved drafts, shown on Alignment Reports |
| Frontend | Page speed fix (`localhost`, connection reuse, short read cache); larger type |
| Study tooling | Issue sheet, blind export of findings and drafts, precision / recall / F1 per dimension, rater agreement, draft ratings (`scripts/study.py`); no study run yet |
| Experiments | Runner with one isolated server per condition, ablation spec, comparison report (`scripts/run_experiment.py`); run in test mode only |
| Live feedback | Provisional check of text being edited (level, objectives, evidence, uncertainty) in the Approval Center and the workbench; rules only |
| Load test | `scripts/load_test.py`; 20 simulated users on one process and SQLite without errors |
| Quality | 292 tests passing (2026-11-13, 294 passed); live provider and German retrieval checks recorded |
| Safety tests | Every endpoint checked for login and course isolation; approval transitions; parallel audit starts and applies; upload and model-output fuzzing; injected instructions in a document; cancel; restart recovery (`tests/test_phase2_resilience.py`, `tests/test_phase2_access.py`) |
| Docs | PRD, Architecture, Design, Rules, Memory, Tasks, roadmap, progress, security checklist, testing report, schema, release checklist |

## Open
| Priority | Task | Notes |
|---|---|---|
| High | Verify `docker compose up --build` end to end | daemon was unavailable during development |
| High | PostgreSQL rehearsal | set `LECTIO_TEST_POSTGRES_DSN` for the schema test, `LECTIO_TEST_DATABASE_URL` for the whole suite; neither tried |
| High | First run of `.github/workflows/ci.yml` | written without access to GitHub Actions |
| High | Evaluation with real MAAI course materials | labels and metrics: `docs/EVALUATION.md` |
| Medium | External Paperclip integration (governance, budgets, audit log) | process adapter exists; decision paper for the supervisor in `docs/PAPERCLIP.md`, not yet decided |
| Medium | Durable job queue for multi-instance deployment | scheduler is single-worker; restart recovery assumes one backend process |
| Medium | Injection test against a live model | only run in test mode and with a stand-in model so far |
| Medium | Real migration system (Alembic) | needs approval for a new dependency; schema file now complete and checked by a test |
| Medium | Draft generation for model findings that are not about objectives or assessments | none have a handler yet |
| Medium | Accessibility audit with a screen reader | colour contrast measured and fixed (2026-11-13); screen reader and keyboard not tested |
| Medium | Live ablation run (`run_experiment.py --live`) | spends provider quota; needed to see the effect of lecturer rules and gate retries |
| Low | Analysis tooling for interaction logs (emergent behaviour) | semester 2 goal; the experiment runner records event counts per run only |
| Low | Optional dark mode in the simple style | a heavier redesign was rejected |

## Ideas not committed to
Side-by-side comparison of two model variants on the same findings; export to PDF; per-course budgets.
