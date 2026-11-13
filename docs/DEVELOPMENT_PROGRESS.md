# Development progress

What was actually done, in order, with how it was verified. Latest first within each day. Counts are from the test suite at that point.

## 2026-11-05
| Change | Verification |
|---|---|
| Interface restored to the simple style with larger text (root 18 px, headings 2.5 / 1.9 / 1.45 rem); a dark "Console" redesign with a light/dark switch was built, reviewed, and set aside | all pages render without errors; screenshots in `docs/screenshots/` |
| Fixed truncated projected scores and stray markdown inside draft boxes | visual check |
| Twelve project documents added under `docs/` | this set |

## 2026-11-04
| Change | Verification |
|---|---|
| Projected scores after approved drafts (`services/projection.py`, `GET /courses/{id}/projection`); one draft closes at most one cognitive-level gap; projections capped at 95% | 10 tests; live on the English course: 64% to 75% with three drafts |
| Model findings split into problems and a separate "confirmed" list; findings that need an objective or an assessment get draftable gap types; headings stay with their text | tests; live: delivery gaps 3 to 0, a false "schedule missing" finding removed |
| Automatic drafts for the worst gaps, capped at 4, one per gap type first, no duplicates on re-audit | live: 4 drafts; identical re-audit used 0 tokens |
| Live review hardening: unverifiable findings dropped individually, cut-off replies fall back, larger audit cap | live: 4 of 4 reviews succeeded, 3 min 49 s instead of 8 min |
| German and English extraction, derived outcomes, "not assessable" reasons | live on English and German datasets |

## 2026-11-03
| Change | Verification |
|---|---|
| Page-speed fix: `localhost` costs about 2 s per request on Windows; connection reuse and a 3 s read cache | Course workbench 41 s to under 1 s |
| Concurrent model reviews, daily-quota handling, review errors shown in the report | live runs; mocked tests |
| Live robustness: token cap, truncation detection, unknown entity IDs, rate-limit pause, failed review no longer erases rule-based findings | live German run, 4 of 4 dimensions |
| Default model changed to a working free model with a cross-provider fallback | `scripts/verify_live.py` passed |
| OpenRouter client, BGE-M3 embeddings, multilingual reranker, caches, cost controls | 50 tests; German retrieval on real models |
| Baseline: existing implementation (revision 2) | 27 passed, 1 skipped |

## Commit trail
`58d9508` baseline, `2ffc2cb` provider and embeddings, `c5991f0` default model, `9db5012` live hardening, `e2e2c9e` speed and extraction, `f59db15` review robustness, `b2b13ea` automatic drafts, `6157729` projection, `b14203b` notes, `4fa386b` findings split and chunk headings, `1857fda` larger type, `2c385cc` fixes and screenshots.

## Current state
60 tests pass, 1 skipped (PostgreSQL needs a DSN). Live provider and real-model checks passed on 2026-11-03 and 2026-11-04. Not verified: Docker build, PostgreSQL deployment, external Paperclip, evaluation on real course data.

## Phase 1 (2026-11-12): Stakeholder gate, course intent, constraints, append-only trace (not committed)

**Completed and tested (17 new tests, `tests/test_phase1_governance.py`):**
- `services/trace.py` + table `trace_events`: hash-chained, append-only event log (audit created, agent start/complete/failed, agent messages, tool calls, model calls, quality checks, retries, findings, drafts, lecturer decisions, apply). ORM refuses UPDATE/DELETE; SQLite and PostgreSQL triggers abort them; `verify_chain` detects edits, removals and reordering. Not tamper-proof against a database owner who rewrites the whole chain (head hash is not anchored outside the DB).
- Every model call is logged (provider, model, prompt version, prompt fingerprint, tokens in/out/total, cache use, duration, outcome, attempt, retry reason, cost when the provider reports it). Prompt text and secrets are never stored.
- `services/intent.py` + `course_intents`: versioned course intent (goals, cognitive levels, audience, scope, constraints); API `GET/PUT /courses/{id}/intent`. Loaded by the Course Director, carried in state, named in every agent hand-over message and agent event, and placed in model prompts (reviews, drafts, outcome derivation). Earlier runs keep the version they used.
- `services/constraints.py` + `lecturer_constraints`: draft rejections/edits become structured constraints (avoid/prefer/require, course or general scope, source, decision, timestamp); supersede/retire add rows, nothing is deleted; rejected drafts are fingerprinted so they are not offered again as if new. API under `/courses/{id}/constraints`.
- `services/stakeholder_gate.py` + `draft_reviews`: every draft (automatic and requested) is checked (structure, grounding, relevance, intent fit, novelty), retried up to `QUALITY_MAX_RETRIES` with adjusted instructions and the next model, each check and retry traced; a draft that stays below `QUALITY_THRESHOLD` is shown with a warning and the reasons, never as a pass.
- `services/stakeholder_view.py`: `GET /courses/{id}/briefing` (plain-language findings with evidence and uncertainty, drafts with rationale), `GET /findings/{gap_id}/trace`, `GET /approvals/{id}/trace`, `GET /runs/{id}/trace`, `.../trace/verify`.
- Frontend (simple UI): Course intent form and learned rules in the workbench; "How was this finding produced?" per finding.
- Full suite: 77 passed, 1 skipped.

**Partial / not done:**
- Trace gaps: quality-check events for the rule-based dimension agents are limited to the agent start/complete events plus tool calls; there is no per-check internal-decision event inside the rule agents.
- The Stakeholder gate checks are rule-based (no model judging); contradiction detection between drafts is not implemented.
- The briefing endpoint is not yet shown in a dedicated page; the lecturer UI shows intent, rules and the finding trace only. Draft rationale/quality is in the API response but the Approval Center page does not display it yet.
- Intent is not yet used by the rule-based dimension scoring (only by model reviews, drafts and derivation).
- Trace log has no UI page for run-level browsing and no retention policy.
- Existing databases need the new tables: they are created at start-up; guards are installed at start-up. No Alembic migration yet.
- Not exercised with a live model since the changes (mocked and local-test only).

## Phase 1 completion (2026-11-12, second session; not committed)

The four Phase 1 items were re-checked against the code and the project description before anything was changed. Baseline at the start of the session: 77 passed, 1 skipped. All four existed and their tests passed, but each fell short of the description in a specific way. Those gaps were closed in this order; 11 new tests in `tests/test_phase1_completion.py`.

| Item | What was missing | What was added | Verified by |
|---|---|---|---|
| 1. Append-only audit log | No event for an agent's own decision (only the Stakeholder's `finding_recorded`); no event closing a run; lecturer draft requests not logged; a cut-off tail or a consistently rewritten chain was undetectable; no TRUNCATE guard on PostgreSQL | `agent_decision` events (one per finding raised, one per dimension assessed, written by the producing agent); `run_finished`; `draft_requested` and its retrieval `tool_call` on the course chain; `GET /courses/{id}/trace`; chain heads anchored in `trace_anchors.jsonl` outside the database at run end and via `POST /courses/{id}/trace/anchor`, checked by `verify_chain`; TRUNCATE trigger for PostgreSQL; the per-finding trace now shows only that finding's events | 4 tests: decisions precede the stored finding and name the same agent; run closed and anchored; removed tail and rewritten last event both detected; draft request logged without its text |
| 2. Course intent to all agents | The rule-based dimension checks ignored the intent | `audit_checks._intent_checks`: intended cognitive levels are compared with the stated objectives (metadata ↔ content) and with the assessment questions (metadata ↔ assessment); an unreached level is its own finding (`intent_level_without_objective`, `intent_level_not_assessed`); each report records the intent version it used, or says none was stated | 2 tests (unit and full audit) |
| 3. Structured lecturer constraints | Only draft decisions became constraints; a rejected finding came back as new on the next audit | Rejecting a finding stores an `avoid` constraint with the finding's identity (kind + course item, or wording without numbers); revising one stores a `prefer` constraint with the lecturer's recommendation; later audits mark the same finding as previously dismissed, lower it to information and produce no draft for it; retiring the rule reinstates it | 2 tests: three audits (raise, dismissed, reinstated), identity stable across changing scores |
| 4. Stakeholder gate and retries | The gate covered drafts only; automatic drafts could not be reassigned to another model; the Approval Center did not show the verdict | A failed Division 1 step is retried (bounded by `QUALITY_MAX_RETRIES`) before it is reported as failed; a model review whose findings cite evidence that was never supplied is asked again once with the allowed ids, the better answer is kept and unverifiable findings are still dropped; automatic drafts retry on the next configured model; `GET /approvals` returns rationale and quality, and the Approval Center shows a warning for a draft that did not pass plus "How was this draft produced?" | 3 tests (mocked agents and models), 1 assertion on the approvals list |

Full suite after these changes: **88 passed, 1 skipped**.

**Still partial or not done (stated plainly):**
- The anchor file sits on the same machine as the database. Someone who can rewrite both is not detected; copy the file elsewhere for that. Lecturer decisions made after a run's anchor are protected only after the next anchor.
- A trace event that cannot be written is logged as an error and the work continues; there is no counter of lost events.
- PostgreSQL trigger SQL (including the new TRUNCATE trigger) is still not run against PostgreSQL.
- Intent: only the cognitive levels are checked by rules. Goals, audience and scope reach the model prompts but no rule compares them with the materials. The intent findings do not change the dimension scores.
- Dismissed findings are matched by identity. Model-review findings have no stable identity (new wording every run), so for those the dismissal acts only through the constraint text in the prompt.
- Constraint text is passed to the model and recorded; apart from rejected-draft and dismissed-finding identities, no rule checks that an output obeys it.
- The gate's checks are rule-based (no model judge). Contradictions between drafts are not detected. Retrying a failed Division 1 step repeats it unchanged; there is no second agent to reassign a dimension to.
- The Approval Center and workbench changes were compiled and covered through the API only; the pages were not opened in a browser this session.
- Nothing in this session was run against a live model.
- No Alembic migration; `docs/Tasks.md`, `DATABASE_SCHEMA.md` and `Architecture.md` do not yet describe the Phase 1 tables and events.

## Phase 2, item 6 (2026-11-12): transcript-to-slide delivery verification (not committed)

Phase 1 was committed as `dc0ae46`. Baseline before this item: 88 passed, 1 skipped.

**Before:** the fourth dimension (content ↔ delivery) only checked that slides or a transcript exist for each planned weekly topic, and could not be scored without a weekly schedule. The plain-language texts for `delivery_not_covered`, `delivery_partial` and `delivery_unplanned` existed, but no code produced those findings.

**Now** (`backend/services/delivery_check.py`, called from `agents/audit_checks.py` for the delivery dimension):
- Each slide or notes paragraph is a planned section, split into its points (sentences). The transcript is split into teaching segments at transitions ("next", "finally", "als Nächstes") or when a sentence shares no content word with the running segment.
- A planned point is addressed when a transcript segment contains enough of its content words (default 40%) or, with the neural backend, is semantically close (default 0.55). Literal wording is never required.
- A section is covered (default: at least 60% of its points addressed), partial, or not covered. Substantive transcript segments that match no planned section are reported as taught but not planned; a segment that reads as an example beside planned content is listed, not flagged; short segments (small talk) are ignored.
- Findings: `delivery_not_covered` (warning), `delivery_partial` and `delivery_unplanned` (information), each with the slide reference, the transcript excerpt and the unmatched points. The report stores the full comparison under `delivery_verification`.
- When a transcript and planned material both exist, the dimension is scored on the share of planned sections found in the transcript (partial counts half) and no longer needs a weekly schedule; the earlier planned-material number is kept as `planned_material_score`. Without a transcript the report says delivery is unverified.
- All thresholds are settings (`DELIVERY_*`). The comparison is a traced tool call.

**Verified:** 9 tests in `tests/test_delivery.py`; full suite **97 passed, 1 skipped**. On the English sample course the audit now reports binary search, hash tables and graph traversal as covered and sorting and complexity analysis as not covered (the sample lecture never mentions them): 60%, warning.

**Limits:** with the lexical test backend only shared words count, so real synonyms need the neural backend; that path was tested with a stand-in embedding function, not with the real model. Not run on real lecture recordings, on German material, or against a live model. Timestamps are not shown because the chunker does not keep them. The thresholds are defaults, not calibrated against labelled data. The delivery findings are not yet shown in a dedicated part of the reports page (they appear in the findings list and the briefing).

## Phase 2, item 7 (2026-11-12): Bloom classifier validation and improvement (not committed)

Baseline before this item: 97 passed, 1 skipped.

- **Evaluation set** `datasets/bloom/labelled.csv`: 120 items, English and German, with dev, held-out and challenge splits. The labels are provisional (written during development, not lecturer-reviewed); `datasets/bloom/README.md` states the labelling rules.
- **Measurement** `backend/knowledge/bloom_eval.py` and `scripts/evaluate_bloom.py`: accuracy, coverage, precision, recall and F1 per level, per language.
- **Weaknesses found in the old word list** (57.5% on the whole set, German 43%): no inflected forms ("categorises", "erklärt"); no German separable verbs ("wenden ... an", "einzusetzen"); the longest verb anywhere in the text won, not the main demand; nouns counted as verbs ("a list", "the test"); verbs listed under two levels silently took the later one; questions without a verb got nothing.
- **Classifier rewritten** (`backend/knowledge/bloom_classifier.py`, same `classify_text` signature): inflections, separable verbs, noun guards (determiners in English, capitalisation in German, "-ing" adjectives), main demand = first action verb with directly coordinated verbs taking the higher level, highest level over several sentences, question-form fallback, one level per verb with an explicit list of ambiguous verbs, and `classify_detail` returning the evidence.
- **Model fallback wired in**: `classify_hybrid` / `classify_many_with_llm` (one call, reply validated item by item, items are treated as data); used by course-model extraction in live mode for objectives and questions the rules cannot classify (`BLOOM_LLM_FALLBACK`, `BLOOM_LLM_MAX_ITEMS`), traced as its own task.
- **Results** (agreement with the provisional key; details in `docs/EVALUATION.md`): dev 70% to 100%, held-out 58% to 100%, challenge 21% to 21%, all 57.5% to 84.2%.

**Verified:** 36 tests in `tests/test_bloom.py`; full suite **133 passed, 1 skipped**.

**Limits:** the key is not lecturer-reviewed and the same author wrote items and rules, so the held-out figure is weak evidence. The challenge split shows the rules still fail on purpose clauses, nominalised demands and verbs outside the lexicon. The model-assisted variant was tested with a mock only; its accuracy is unmeasured, so the keyword-versus-hybrid comparison is still open. On long teaching text the level is a weak signal.

## Phase 2, item 8 (2026-11-13): extraction and retrieval evaluation (not committed)

Baseline before this item: 133 passed, 1 skipped.

**Extraction**
- Labelled cases `datasets/extraction/cases.json` (8 snippets, English and German, 24 outcomes, 22 schedule entries, with look-alikes). Provisional, synthetic key.
- The line rules moved to `backend/knowledge/outline_rules.py` (no database import) and were rewritten: outcome codes, "students can / will be able to / sind in der Lage" with organisational and negated lines excluded, list items under an outcomes heading or an opening line, a modal directly governing an action verb; delivery documents stay strict. Schedule lines now cover "Wk. 3", "Lecture 4", "2. Woche", "Week 3 (12 Oct)", and leave out holiday and exam weeks.
- `services/course_model.py` uses these functions; extracted outcomes are stored without their list marker.
- Result on all cases: outcomes precision 57% to 100%, recall 71% to 100%; schedule precision 74% to 100%, recall 64% to 100% (agreement with the provisional key; held-out cases included).
- Bug fixed on the way: a German sentence was cut at "1. Mai".

**Retrieval**
- Labelled set `datasets/retrieval/labelled.json` (24 passages, 34 paraphrased queries, 12 of them cross-language). Provisional, synthetic key.
- `backend/knowledge/quality_eval.py` measures recall@1/3/5 and MRR per language pair for keyword search, the offline test backend, embeddings, rank fusion and reranking; `scripts/evaluate_retrieval.py --neural` runs the real models.
- **Defect fixed:** the BM25 tokeniser split German words at umlauts. German top-1 with keyword search 45% to 64%.
- **Measured with the real models:** embeddings alone MRR 0.90; equal-weight fusion 0.72 because cross-language queries drop to 0.39 and 0.27; fusion plus reranker (as the application does) 0.84, with cross-language repaired but same-language top-1 lower. Full table in `docs/EVALUATION.md`.
- Lexical scoring moved to `backend/rag/lexical.py` so it can be measured without a database; behaviour unchanged.

**Verified:** 44 tests in `tests/test_extraction_eval.py`, 19 in `tests/test_retrieval_eval.py` (3 of them with the real embedding and reranker models); full suite **196 passed, 1 skipped**.

**Limits and open decisions:** both keys are synthetic and written by the same author as the rules; eight extraction cases is a small sample. Outcomes in tables or free prose are not extracted. The fusion weakness was recorded, not fixed: the 24-passage set exaggerates it and tuning on it would overfit, so it has to be re-measured on a real bilingual course. Courses extracted before this change stored list-item outcomes with their marker ("- explain ..."); re-extracting such a course can add the same outcome again without the marker.

**Next (Phase 2 onward, per the master prompt):** role-matrix, concurrency, injection and fuzz tests; Paperclip decision document; evaluation pipeline; experiment runner; live alignment feedback; PostgreSQL/CI.
