# Project memory: context and confirmed decisions

Facts a new contributor (or a new session) needs. Dates are when the decision was made.

## Project
- Lectio: multi-agent course-alignment auditing and content-suggestion prototype (MAAI application project, supervisor Prof. Dr. Carsten Lanquillon). Source documents: `Lectio_Project_Description.pdf` and the team's exposé.
- This code is a FastAPI + Streamlit + LangGraph implementation (revision 2 baseline, then the changes in `DEVELOPMENT_PROGRESS.md`).

## Confirmed decisions
| Date | Decision | Detail |
|---|---|---|
| 2026-11-03 | Generation through OpenRouter, free models | no budget; one fallback model; model names are configurable |
| 2026-11-03 | Embeddings `BAAI/bge-m3` | German and English retrieval; weights cached once in a Docker volume |
| 2026-11-03 | Keep token and API use minimal | caching of validated results, retrieval instead of whole documents, caps, no retry loops |
| 2026-11-04 | Automatic drafts after an audit, capped | worst gaps first, one per gap type, default 4 per audit |
| 2026-11-04 | Projected scores after approved drafts | labelled as projections, capped at 95% |
| 2026-11-05 | UI stays simple with larger text | a dark "Console" redesign with a light/dark switch was built and judged to look dated and over-designed; the simple UI was restored |
| 2026-11-05 | Code shared in the team repository under its own folder | `test umang/` in `sarathRajendran123/Lectio_app` |

## Model facts (checked 2026-11-03/04)
- Default: `nvidia/nemotron-3.5-super-vl:free` (about 10 to 70 s per audit review depending on load). Fallback: `nvidia/nemotron-3-ultra-550b-a55b:free`.
- Gemma 4 free models were rate-limited upstream during testing.
- An OpenRouter account without credits gets **50 free-model requests per day** (1000 after buying 10 credits). One audit uses about 5 requests plus up to 4 for drafts. Resets at 00:00 UTC.

## Known quirks
- First request after a restart can wait for the embedding model to load (warmed at start-up in neural mode).
- `.env` in some setups has `BACKEND_URL=http://backend:8000` (Docker name); local runs need `http://127.0.0.1:8000`. `localhost` is slow on Windows (IPv6 fallback), so the client rewrites it.
- Free models may reason for a long time; audit caps are 6000 tokens and cut-off replies fall back to the other model.
- About 2 of 10 model findings per run cite evidence that was not supplied and are dropped by design.

## Not verified
Docker image build and `docker compose up`; PostgreSQL deployment (one regression test is skipped without a DSN); external Paperclip; evaluation on real MAAI course materials.

## Where things are
- Run locally: `python scripts/run_local.py` (see `README.md`).
- Sample data: `datasets/en_algorithms`, `datasets/de_algorithmen`; run them with `python scripts/run_dataset.py <folder>`.
- Cost and models: `docs/COST_AND_MODELS.md`. Verification log: `docs/VERIFICATION.md`.
