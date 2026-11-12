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

**Next (Phase 2 onward, per the master prompt):** transcript-to-slide delivery verification; Bloom validation; extraction/retrieval evaluation; role-matrix, concurrency, injection and fuzz tests; Paperclip decision document; evaluation pipeline; experiment runner; live alignment feedback; PostgreSQL/CI.
