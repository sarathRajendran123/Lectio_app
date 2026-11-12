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
python -m pytest -q                       # full suite (88 passed, 1 skipped on 2026-11-12)
LECTIO_SKIP_MODEL_TESTS=1 python -m pytest -q   # skip the real-model tests
python scripts/verify_live.py             # needs OPENROUTER_API_KEY
python scripts/run_dataset.py datasets/en_algorithms   # against a running local API
```

## Update 2026-11-12 (Phase 1)

`python -m pytest -q`: **77 passed, 1 skipped** (about 85 s). New file `tests/test_phase1_governance.py` (17 tests): intent versioning and validation; intent on every audit event and hand-over; a changed intent reaching later runs while earlier runs keep theirs; intent and constraints in the model prompt; decisions becoming constraints, supersede, retire, general vs course scope; a rejected draft not passing again; gate scoring; gate retry with adjusted instructions, intent kept and model switched; retry limit and no false pass; failed generations recorded; per-model-call logging without prompt text or secrets; trace order, linkage and hash-chain verification; ORM, SQL and tamper detection; briefing in plain language; per-finding and per-draft trace.
Failures found while writing them and fixed: gate relevance compared singular and plural words as different (now 5-letter stems); a test assumed one start event per director task.

## Update 2026-11-12 (Phase 1 completion, second session)

Baseline before any change: `python -m pytest -q` gave 77 passed, 1 skipped. After the changes: **88 passed, 1 skipped** (about 105 s, Windows, Python 3.13, SQLite, `RUNTIME_MODE=local_test`).

New file `tests/test_phase1_completion.py` (11 tests):

| Area | Tests | What they show |
|---|---|---|
| Audit log | 4 | every stored finding is preceded by an `agent_decision` from the agent that produced it; one `dimension_assessed` decision per dimension; the run ends with `run_finished` and its head is anchored outside the database; a per-finding trace contains only that finding's events; a lecturer draft request is logged (fingerprint, not text) before its retrieval, check and queueing; with the database guards dropped, a removed tail and a last event rewritten with a matching hash are both reported by `verify_chain` |
| Course intent | 2 | intended levels compared with objective and question levels in a unit test; a full audit of the English sample course with intent "evaluate, create" reports the unreached levels, records the intent version in the report and words the finding plainly |
| Constraints | 2 | rejecting a finding creates an `avoid` rule, revising one a `prefer` rule, approving one none; the next audit marks the same finding as dismissed (information, no new warning) while other findings stay; retiring the rule brings it back on the third audit; finding identity ignores changing scores |
| Gate | 3 | a failing Division 1 step runs twice then is reported as failed, once with zero retries; a model review citing an unsupplied id is asked again with the allowed ids and only verified findings surface, and the loop stops at the limit; a weak automatic draft is retried on the second model with the intent kept in the instructions |

One existing test was adjusted: the exact-match assertion on `verify_chain` now includes the new `anchored_seq` field.
Failure found by the full run and fixed: the new intent findings have no source excerpt, and the briefing rule "no evidence is stated as low certainty" (existing test) failed; their certainty text now starts "Low to moderate" and says no excerpt is attached.

Not run in this session: any live-model call (the Division 1 retry, model-review retry and model reassignment were tested with mocked agents and models); PostgreSQL (trigger SQL including the new TRUNCATE trigger is untested there; one test still skipped); a browser check of the Approval Center and workbench changes (the two files compile and their API data is tested); Docker. Not run: live-model evaluation of the new gate, PostgreSQL run of the trace triggers (SQL for PostgreSQL written, untested), browser check of the new workbench sections.
