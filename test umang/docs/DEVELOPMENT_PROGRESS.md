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
