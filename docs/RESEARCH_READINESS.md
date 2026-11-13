# Requirements matrix and research readiness

Written 2026-11-13 at the end of the work plan in the master prompt (Phases 1 to 4). Every status below rests on code in this repository and on a test or command that was run on that date; anything not run says so. Details and figures: `docs/DEVELOPMENT_PROGRESS.md`, `docs/TESTING_REPORT.md`, `docs/EVALUATION.md`.

Status words: **Done** = implemented and verified as described; **Partly** = implemented, with a named part not verified or not built; **Open** = not done; **Needs a decision** = cannot be finished by development alone.

Suite on 2026-11-13: 294 passed, 1 skipped (the PostgreSQL schema test, which needs a database). All of it runs in test mode: no language model is called and retrieval is word overlap, except 6 tests that load the real embedding and reranker models.

## 1. Work plan items

| # | Item | Status | Evidence | Not verified or not built |
|---|---|---|---|---|
| 1 | Stakeholder quality gate, internal retries | Done | `services/stakeholder_gate.py`; `test_phase1_governance.py`, `test_phase1_completion.py` | gate is rule-based; no model judge; no contradiction check between drafts |
| 2 | Structured lecturer constraints and feedback | Done | `services/constraints.py`; insert-only rules; decisions become rules; dismissed findings stay dismissed | |
| 3 | Course intent and goal propagation | Done | `services/intent.py`; intent reaches every agent and the trace; intent checks in the audit | scope and audience text is passed on but not checked by rules |
| 4 | Append-only trace | Done | hash chain, database triggers, anchor file outside the database; tamper tests | anchor file lies on the same host |
| 5 | Per-finding trace view | Done | `/findings/{id}/trace`, `/approvals/{id}/trace`, workbench view | no separate briefing page |
| 6 | Transcript-to-slide delivery check | Done | `services/delivery_check.py`; `test_delivery.py` (9) | thresholds set on synthetic material |
| 7 | Bloom classifier validation | Partly | 120-item set; agreement with provisional key 57.5% to 84.2%; challenge split 20.8% | key not lecturer-reviewed; model-assisted variant not measured (`--llm` not run) |
| 8 | Extraction and retrieval evaluation | Partly | extraction and retrieval sets, metrics, real embedding and reranker models; umlaut tokeniser bug fixed | keys synthetic; fusion weakness across languages recorded, not fixed |
| 9 | Approval, concurrency, recovery, security tests | Done | `test_phase2_resilience.py` (29), `test_phase2_access.py` (11) | concurrency only on SQLite; injection not run against a live model |
| 10 | Paperclip integration or supervisor decision | Needs a decision | decision paper with three options in `docs/PAPERCLIP.md`; process adapter with mocked contract tests | no Paperclip installation; no decision recorded |
| 11 | Evaluation and ground-truth pipeline | Partly | `scripts/study.py`: issue sheet, blind export, precision / recall / F1 per dimension, kappa, draft ratings; `test_study_eval.py` (20) | no lecturer has labelled anything; adjudication between raters and confidence intervals not built |
| 12 | Experiment runner and ablations | Partly | `scripts/run_experiment.py`, isolated server per run; 7-condition ablation run in test mode | no `--live` run, so model-dependent conditions (rules, gate retries) show no effect yet |
| 13 | Research metrics and report outputs | Partly | JSON and Markdown reports from the study and experiment tools | no study data to report; interaction-log analysis beyond event counts not built |
| 14 | Live alignment feedback | Done (rules only) | `/courses/{id}/draft-feedback`; buttons in Approval Center and workbench; `test_draft_feedback.py` | live-mode retrieval path not run; no model judgement; verb and word-overlap limits |
| 15 | PostgreSQL, migrations, durable jobs, Docker, browser CI, load | Partly | schema file completed and now checked by a test; CI workflow written; load test run (20 users, no errors) | no PostgreSQL run; no migration tool (new dependency, needs approval); no durable queue; Docker daemon not running; CI never executed |
| 16 | Accessibility and smaller items | Partly | colour contrast measured and fixed (two Bloom badges, one grey); contrast test | no screen-reader or keyboard test; pages not opened in a real browser this session |

## 2. Required automated tests (master prompt list)

| Required test | Present | Where | Runs in the default suite |
|---|---|---|---|
| Delivery verification | yes | `test_delivery.py` | yes |
| Bloom accuracy | yes | `test_bloom.py` | yes |
| Extraction look-alikes | yes | `test_extraction_eval.py` | yes |
| Retrieval recall and ranking, English and German | yes | `test_retrieval_eval.py`, `test_german_retrieval.py` | yes (real models; skippable) |
| Approval workflow transitions | yes | `test_phase2_resilience.py` | yes |
| Re-run stability | yes | cache and validation tests; identical findings on repeat in `test_experiment.py` | yes |
| Prompt injection | yes | `test_phase2_access.py` | yes (test mode and a stand-in model) |
| Model-output fuzzing | yes | `test_phase2_resilience.py` | yes |
| Concurrency | yes | `test_phase2_resilience.py` | yes (SQLite) |
| Role matrix, every endpoint | yes | `test_phase2_access.py` (endpoint list read from the app) | yes |
| Upload fuzzing | yes | `test_security.py`, `test_phase2_resilience.py` | yes |
| PostgreSQL | partly | schema completeness runs always; column types and the whole suite need a database | no |
| Browser flow | script only | `scripts/check_browser.py`, CI job | no |
| Load | script and statistics test | `scripts/load_test.py`, `test_experiment.py` | statistics only |
| Security CI | written | `.github/workflows/ci.yml` (pip-audit, secret scan) | never executed |

## 3. Research readiness

**What can be studied now.** The tooling for the study in the exposé exists: a lecturer can list issues before seeing findings, judge exported findings, rate blind drafts, and get precision, recall, F1 per dimension, rater agreement and draft ratings. Configurations can be compared on the same course with isolated runs.

**What blocks a study result.**
1. Real MAAI course materials with permission to use them.
2. Lecturers who label: an issue list per course before seeing findings, and judgements of the exported findings and drafts.
3. Live-model runs, which spend provider quota: `scripts/run_experiment.py --live` and `scripts/evaluate_bloom.py --llm`.
4. A supervisor decision on Paperclip (`docs/PAPERCLIP.md`).

**What must not be reported as a result.** Every figure measured so far is agreement with keys the developer wrote, on synthetic material, mostly in test mode. They show that the software computes what it should and where the rules fail; they say nothing about usefulness to lecturers.

**Before deployment.** PostgreSQL run of the suite, a migration tool, Docker verification, a first CI run, and rotation of credentials that were exposed earlier (by the account owner).
