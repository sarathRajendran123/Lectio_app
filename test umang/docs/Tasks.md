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
| Quality | 60 tests passing; live provider and German retrieval checks recorded |
| Docs | PRD, Architecture, Design, Rules, Memory, Tasks, roadmap, progress, security checklist, testing report, schema, release checklist |

## Open
| Priority | Task | Notes |
|---|---|---|
| High | Verify `docker compose up --build` end to end | daemon was unavailable during development |
| High | PostgreSQL rehearsal | set `LECTIO_TEST_POSTGRES_DSN` to run the skipped regression test |
| High | Evaluation with real MAAI course materials | labels and metrics: `docs/EVALUATION.md` |
| Medium | External Paperclip integration (governance, budgets, audit log) | process adapter exists |
| Medium | Durable job queue for multi-instance deployment | scheduler is single-worker |
| Medium | Real migration system (Alembic) | tables are created at start-up |
| Medium | Draft generation for model findings that are not about objectives or assessments | none have a handler yet |
| Medium | Accessibility audit with a screen reader | not done |
| Low | Analysis tooling for interaction logs (emergent behaviour) | semester 2 goal |
| Low | Optional dark mode in the simple style | a heavier redesign was rejected |

## Ideas not committed to
Side-by-side comparison of two model variants on the same findings; export to PDF; per-course budgets.
