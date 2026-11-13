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
python -m pytest -q                       # full suite (297 passed, 2 skipped on SQLite; 299 passed on PostgreSQL; 2026-11-13)
LECTIO_SKIP_MODEL_TESTS=1 python -m pytest -q   # skip the real-model tests
python scripts/verify_live.py             # needs OPENROUTER_API_KEY
python scripts/run_dataset.py datasets/en_algorithms   # against a running local API
```

## Update 2026-11-12 (Phase 1)

`python -m pytest -q`: **77 passed, 1 skipped** (about 85 s). New file `tests/test_phase1_governance.py` (17 tests): intent versioning and validation; intent on every audit event and hand-over; a changed intent reaching later runs while earlier runs keep theirs; intent and constraints in the model prompt; decisions becoming constraints, supersede, retire, general vs course scope; a rejected draft not passing again; gate scoring; gate retry with adjusted instructions, intent kept and model switched; retry limit and no false pass; failed generations recorded; per-model-call logging without prompt text or secrets; trace order, linkage and hash-chain verification; ORM, SQL and tamper detection; briefing in plain language; per-finding and per-draft trace.
Failures found while writing them and fixed: gate relevance compared singular and plural words as different (now 5-letter stems); a test assumed one start event per director task.

## Update 2026-11-13 (PostgreSQL and Docker)

The suite now runs on PostgreSQL with `LECTIO_TEST_DATABASE_URL` (plus `LECTIO_TEST_POSTGRES_DSN` for the column-type test). Run against PostgreSQL 15 in Docker, created from `001_initial.sql`.

| Run | Result |
|---|---|
| PostgreSQL, before the fixes | 267 passed, 22 failed, 6 errors; a second attempt hung (lock wait, see below) |
| PostgreSQL, after the fixes | **299 passed**, nothing skipped |
| SQLite, after the fixes | **297 passed, 2 skipped** (the two tests that need PostgreSQL) |

| New test | What it shows |
|---|---|
| `test_task_ids_fit_their_columns` | the longest task-id formats fit `trace_events` and `draft_reviews` with headroom |
| `test_a_trace_write_waiting_on_another_transaction_gives_up_instead_of_hanging` | PostgreSQL only: a second writer of a chain gives up within seconds instead of waiting forever |
| `test_an_audit_still_completes_when_debug_turns_on_sql_echo` | with `DEBUG=true` an audit finishes; without the fix it ends as failed ("Extra data") |
| `test_drafts_without_supporting_material_are_reported_as_such_not_as_a_provider_error` | German course in test mode: the run says no supporting passage was found, not to check an API key |

Changed test: the two tamper tests remove the trace triggers with the statement for the engine in use (they used SQLite syntax).

Docker, checked by hand in test mode: both images build; stack starts; both sample courses upload and audit; `scripts/check_ui.py` passes all 11 pages against the Docker API; traces verify; PostgreSQL refuses a direct trace UPDATE.

Not run: the stack in live mode; the CI workflow on GitHub.

## Update 2026-11-13 (Phase 4: schema file, contrast, closing run)

Baseline 292 passed, 1 skipped. After: **294 passed, 1 skipped**.

| Test | What it shows |
|---|---|
| `test_every_orm_table_and_column_is_in_the_postgres_schema_file` | every ORM table and column appears in `001_initial.sql`; runs without PostgreSQL; failed against the previous file (seven tables missing) |
| `test_text_colours_meet_wcag_aa_contrast` | white text on every Bloom badge, body and grey label text, and button text reach 4.5:1; the focus ring reaches 3:1 |

Not run: the schema file on PostgreSQL; a screen reader or keyboard-only check.

## Update 2026-11-13 (Phase 4: live alignment feedback, load test)

Baseline 280 passed, 1 skipped. After: **292 passed, 1 skipped**. `tests/test_draft_feedback.py`, 11 tests, all in test mode (verb rules and word-overlap search, no model).

| Area | What the tests show |
|---|---|
| Labelling | the answer is marked provisional, says no model was used and that it is not an audit result; every finding states its uncertainty |
| Evidence | a task on a taught topic returns the matching slide passage; only passages of this course are returned; an untaught topic is "insufficient evidence", with no passage |
| Level | below the intended level: warning; at the level: nothing; above: note; no verb recognised: "unclear", never a guess |
| Objectives (German) | a task below the level of its selected objective is flagged; the objective a task addresses is found without being selected; none found is said so |
| New objective | near-duplicate of an existing one, not matched by an exam task, outside the levels of the course intent |
| Empty course | three "not checked" reasons and no finding |
| Side effects | no draft, report or objective changes; the trace holds a fingerprint, not the text, and still verifies |
| Robustness | works during a running audit; too short, too long, unknown type or level, or an objective of another course: 422 |

Also: the new endpoint is part of the every-endpoint login and isolation tests; one test checks the load statistics (it found an off-by-one in the percentile, fixed before the recorded runs).

Checked by hand: both new buttons clicked through Streamlit's test harness against a throwaway server; `scripts/load_test.py` with 5 and 20 users (figures in `docs/DEVELOPMENT_PROGRESS.md`).

Not run: the feedback in live mode; the pages in a real browser; `.github/workflows/ci.yml`; the suite on PostgreSQL.

## Update 2026-11-13 (Phase 3, items 12 and 13: experiment runner)

Baseline 256 passed, 1 skipped. After: **280 passed, 1 skipped** (322 s). `tests/test_experiment.py`, 24 tests. Measurements in the unit tests are made up to check arithmetic.

| Area | What the tests show |
|---|---|
| Spec | the bundled spec is valid; ten malformed specs are refused; a spec cannot change secrets, database, storage, mode or the trace (8 settings tried) |
| Finding identity | the same finding is recognised in another run despite new ids and scores; different documents, dimensions, objective numbers or German verbs stay different |
| Comparison | means, stability, overlap, findings only in one condition and score changes match a hand-computed example; no change is invented for a dimension that was not assessed |
| Honesty | one run cannot show stability (n/a); failed runs are counted and listed; the report states test mode and that it does not judge correctness |
| Real run | two conditions, two runs each, on separate servers: all finish, identical runs give identical findings, trace valid, no model call, the left-out transcript removes the delivery findings, no credential in the saved results |

Also run by hand: the seven-condition spec (14 audits), results in `experiments/results/ablation_test_mode/`.

Not run: any experiment with `--live`; more than one course.

## Update 2026-11-13 (Phase 3, item 11: study pipeline)

Baseline 236 passed, 1 skipped. After: **256 passed, 1 skipped**. `tests/test_study_eval.py`, 20 tests. Every label in these tests is made up to check arithmetic.

| Area | What the tests show |
|---|---|
| Precision, recall, F1 | match a hand-computed example per dimension and in total; two findings for one issue count once for recall |
| Undefined figures | nothing judged or no issue listed gives "n/a", never 100% |
| Abstention | a dimension the system could not assess is shown but left out of the totals |
| Sheet checks | unknown dimension, duplicate issue id, wrong label, match to an unknown or other-dimension issue, match on a rejected finding: refused |
| Agreement | Cohen's kappa matches a hand-computed example; only findings both raters judged count; undefined without variation |
| Blind rating | the sheet contains no model, style, status, quality score or draft id; order is repeatable per seed |
| Draft figures | means per criterion and model, edit burden, decisions and gate cross-table match a hand-computed example; invalid ratings refused |
| Files | CSV round trip with German text, quotes, line breaks and an Excel byte-order mark |
| End to end | export from an audited course through the API, scoring of unfilled sheets (all "n/a"), then of filled sheets |

Not run: a study with lecturers; the export against a live server.

## Update 2026-11-13 (Phase 2, item 9, second part: every endpoint, injection, cancel, restart)

Baseline 225 passed, 1 skipped. After: **236 passed, 1 skipped** (about 195 s). `tests/test_phase2_access.py`, 11 tests.

| Area | What the tests show |
|---|---|
| Login | every endpoint except login and refresh refuses a missing or forged token |
| Course isolation | an outsider gets 403 or 404 on every course-scoped endpoint (50+), with valid input and real identifiers; the owner's export is unchanged |
| Admin routes | 403 for a lecturer on all of them; no self-promotion; a deactivated account is refused at once |
| Injected instructions | audit of a document carrying an instruction: nothing approved, applied or rescored, trace valid; an obedient stand-in model's reply is refused; source text is passed only as marked data |
| Cancel | run ends as cancelled, worker gone, no partial reports, one closing trace event, lock released, new audit runs |
| Restart | interrupted run and document closed as failed; recovery repeatable; finished runs untouched |

Not run: the injection against a live model; killing a real server process; several backend processes; PostgreSQL.

## Update 2026-11-13 (Phase 2, item 9, first part: approval, concurrency, roles, fuzzing)

Baseline 196 passed, 1 skipped. After: **225 passed, 1 skipped** (about 167 s). `tests/test_phase2_resilience.py`, 29 tests, run three times in a row without a failure.

| Area | What the tests show |
|---|---|
| Model output fuzzing | malformed, incomplete, over-long or fabricated drafts (non-verbatim quote, unknown source number) are refused; markup stays plain text |
| Model client, network mocked | one fallback after a temporary error; none after the quota error or a refused request; cut-off output fails; refused output is not cached; an identical validated request costs no second call |
| Upload fuzzing | too many entries, path traversal, macros, embedded objects, compression bomb, corrupt archive: all refused |
| Roles | hierarchy order; lecturer gets 403 on three admin routes; admin cannot deactivate own account |
| Approval transitions | reject then approve kept in order; revise without text 422; apply after reject 409; second apply 409; unknown decision refused |
| Concurrency | 3 parallel audit starts: one 202, others 409; 3 parallel applies: one 200, others 409 |

Not run: a role check for every endpoint; injection text in an uploaded document through a full audit; cancellation and restart recovery; any of this on PostgreSQL (SQLite serialises writers).

## Update 2026-11-13 (Phase 2, item 8: extraction and retrieval)

Baseline 133 passed, 1 skipped. After: **196 passed, 1 skipped** (about 184 s; the retrieval tests load the embedding and reranker models).

`tests/test_extraction_eval.py` (44 tests):

| Area | What the tests show |
|---|---|
| Measured quality | precision and recall of at least 90% for outcomes and schedule on the dev and the held-out cases (currently 100%); the metric code checked on a hand-computed example |
| Realistic phrasing | 11 English and German outcome formulations are found; list items count only under an outcomes heading or opening line |
| Look-alikes | 14 organisational or similar lines are not outcomes (attendance, grades, prerequisites, "the lecturer will be able to", negations, the opening line itself); 10 slide and paper lines are read strictly |
| Schedule | nine notations are read; ten lines that are not teaching weeks are left out (holiday, exam, deadline, running text, out of range); a date inside a sentence no longer cuts it |

`tests/test_retrieval_eval.py` (19 tests):

| Area | What the tests show |
|---|---|
| Set and metrics | 24 passages, 34 paraphrased queries, four language pairs; recall@k and MRR checked on a hand-computed ranking |
| Keyword search | German words stay whole; the tokeniser fix raises German MRR by more than 0.1 and leaves English unchanged; same-language recall@3 is 100% (English) and at least 90% at 5 (German) |
| Known limit | keyword search and the offline test backend find no English passage for a German query: asserted, not hidden |
| Real models (3 tests) | embeddings: recall@5 100%, MRR at least 0.85, each language pair at least 0.8; equal-weight fusion is worse than embeddings alone across languages by more than 0.3 MRR and not worse within a language; reranking 20 candidates brings cross-language top-1 back |

Measured figures are in `docs/EVALUATION.md`. All keys are provisional and synthetic.
Found and fixed: BM25 tokeniser split German words at umlauts; a sentence was cut at "1. Mai"; organisational lines were extracted as outcomes; holiday and exam weeks became schedule topics.

Not run: any of this on real MAAI documents; retrieval through the SQL vector store with a realistic number of chunks (the comparison ranks 24 passages in memory).

## Update 2026-11-12 (Phase 2, item 7: Bloom classifier)

Baseline 97 passed, 1 skipped. After: **133 passed, 1 skipped** (about 119 s). New file `tests/test_bloom.py` (36 tests):

| Area | Tests | What they show |
|---|---|---|
| Accuracy on the labelled set | 4 | set is balanced (8 per level and language) and well formed; English and German each at least 95% on dev and held-out with recall of at least 85% per level; the challenge split stays a measured weakness (between 15% and 45%, with three named failure cases); the metric code is checked on a hand-computed example |
| Rules | 17 | 14 sentence structures (noun traps, inflections, coordination, separable and conjugated German verbs, an idiom); question forms; no level invented when no demand is stated; highest level over several sentences; ambiguous verbs flagged |
| Model-assisted | 15 | the model is asked only for open items, in one call; optional re-ask for ambiguous verbs keeps the rule level on record; ten malformed replies (not JSON, wrong types, unknown level, out-of-range index, provider error) leave the item unclassified; a mixed reply is validated item by item; extraction calls the model only in live mode and when enabled |

Measured figures (agreement with a provisional, not lecturer-reviewed key): old word list 57.5% of 120, new rules 84.2%; by split see `docs/EVALUATION.md`.
Found while testing and fixed: "operating systems" was read as the verb "operate" ("-ing" forms now count only where they act as verbs); German verbs ending in "-ern" ("erläutern") were not matched.

Not run: `scripts/evaluate_bloom.py --llm` (needs a provider key and model calls), so the model-assisted accuracy is unmeasured.

## Update 2026-11-12 (Phase 2, item 6: delivery verification)

Baseline 88 passed, 1 skipped. After: **97 passed, 1 skipped** (about 118 s). New file `tests/test_delivery.py` (9 tests):

| Required case | Test | Result |
|---|---|---|
| Matching transcript is not flagged | `test_a_transcript_that_matches_its_slides_raises_no_delivery_gap` | all sections covered, nothing unplanned |
| Omitted planned topic is flagged | `test_a_transcript_that_omits_a_planned_topic_is_flagged_with_the_reason` | the omitted section is not covered, 0 of 2 points |
| Different wording is not flagged | `test_a_topic_taught_in_different_wording_is_not_flagged` | all covered although no slide sentence is repeated |
| Unexpected taught content is identified | `test_unexpected_taught_content_is_identified_and_examples_are_not_flagged` | new subject flagged; an example beside planned content listed only; small talk ignored |
| Valid transcript and slide references | `test_findings_carry_valid_transcript_and_slide_references` | chunk ids, slide numbers, documents and excerpts all resolve |
| Also | partial coverage with the missing points; semantic match of a paraphrase with no shared words and a configurable threshold (stand-in embeddings); no transcript reported as unverified; full audit of the English sample (sorting and complexity not covered, 60%, evidence ids exist in the stored excerpts, plain-language briefing) | passed |

Found while testing and fixed: a closing remark of eight content words was flagged as unplanned content (minimum raised to 12); an example without a transition is absorbed into its topic's segment, so the test now uses one that starts its own segment. One existing test was adjusted: it assumed every tool call is a retrieval; the delivery comparison is now a second kind.

Not run: the real embedding model on the semantic path, German transcripts, real lecture recordings, a live model.

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
