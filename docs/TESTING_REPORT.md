# Testing report

Run on 2026-11-05 on Windows, Python 3.13, SQLite, `RUNTIME_MODE=local_test` for the automated suite.

```
python -m pytest -q
60 passed, 1 skipped in 86 s
```

## Results by file
| File | Tests | What it covers |
|---|---|---|
| `test_agents.py` | 6 | director routing, live-review evidence rules, concurrent reviews called once each, confirmations separated from gaps, evaluation maths |
| `test_completion.py` | 8 | schema and quotation validation, broker, Paperclip contract, finding decisions, SQL vector isolation, apply-requires-approval |
| `test_formats.py` | 3 | PDF, Office and empty files; missing evidence is not a pass; encrypted PDF rejected |
| `test_german_retrieval.py` | 3 | real `BAAI/bge-m3` and the multilingual reranker: German to German, German to English, rerank (needs the models; `LECTIO_SKIP_MODEL_TESTS=1` skips offline) |
| `test_journey.py` | 2 | full lecturer journey: upload, extract, audit, generate, revise, approve, export; reviewed extraction and clusters |
| `test_llm_cost.py` | 14 | cache reuse, invalid output never cached, single fallback, quota stop, reasoning hint, embedding cache, stale-vector guard, draft cap |
| `test_multilingual_model.py` | 6 | German extraction, outcome derivation, no unexplained "unknown", client speed-ups, heading chunks |
| `test_postgres_regressions.py` | 4 (1 skipped) | PostgreSQL column and audit-log regressions; the skipped test needs `LECTIO_TEST_POSTGRES_DSN` |
| `test_projection.py` | 8 | gap checks per draft, cognitive-level rule, cap and formula, end-to-end projection after approval |
| `test_security.py` | 7 | untrusted Office and paths, hard limits, citation rejection, course isolation, upload errors, failed-login counter and logout, object isolation |

## Live and real-model checks (not part of the default suite)
| Date | Check | Result |
|---|---|---|
| 2026-11-03 | `scripts/verify_live.py` against OpenRouter | passed (schema-valid draft, citation checked) |
| 2026-11-03 | German retrieval with real models | 3 passed |
| 2026-11-03 | English and German datasets end to end | scores for all four dimensions; first run exposed three defects (below) |
| 2026-11-04 | English dataset after fixes | 4 of 4 live reviews; 3 min 49 s; scores 71 / 64 / 67 / 57% |
| 2026-11-04 | Automatic drafts and projection | 4 drafts; identical re-audit: 0 tokens, no duplicates; 64% to 75% projected |
| 2026-11-05 | Every page renders (Streamlit app test) | no exceptions |

## Failures found by live runs and fixed (each has a regression test)
1. Truncated JSON from a token cap that was too low: cap raised, truncation detected and reported.
2. Invented entity IDs and evidence IDs discarded a whole review: now dropped individually.
3. Rate limits and free-quota exhaustion: one paused second pass; daily limit stops at once with a message.
4. A failed model review erased rule-based findings: now isolated.
5. A duplicate-submission bug in concurrent reviews, found by its own test.
6. A single minor finding projecting 100%: capped at 95% and shared over at least three warning weights.
7. First version let one draft close three level gaps: limited to one.
8. `localhost` costing about 2 s per request: rewritten to `127.0.0.1`.

## Not tested
Docker image build and `docker compose up`; PostgreSQL deployment (one test skipped); external Paperclip; screen-reader accessibility; load; evaluation on real MAAI course data.

## How to run
```bash
python -m pytest -q                       # full suite (60 passed, 1 skipped)
LECTIO_SKIP_MODEL_TESTS=1 python -m pytest -q   # skip the real-model tests
python scripts/verify_live.py             # needs OPENROUTER_API_KEY
python scripts/run_dataset.py datasets/en_algorithms   # against a running local API
```
