# Evaluation protocol — no results invented

The exposé defines the course artefact set as the unit of analysis and lecturer utility as the primary criterion. The supplied archive included no labelled real-course corpus or evaluation results. The automated fixtures are synthetic software tests, not evidence of educational validity.

1. Obtain permission to use real MAAI university course materials; retain versioned source IDs, hash checksums and parser warnings.
2. Freeze the course corpus and objective model. Have lecturers independently label alignment units across all four dimensions. Record missing-document and independent-study cases separately from confirmed inconsistencies.
3. Establish ground truth before inspecting the system's predictions. Resolve disagreements and record inter-rater agreement if multiple raters are available.
4. Run each model/prompt configuration against the same corpus. Record provider/model, configuration, run IDs, AgentStep logs, errors, retrieved sources and token counts. Treat any missing/failed dimension as an abstention, not a negative prediction.
5. Use `scripts/study.py` for the sheets and the figures (added 2026-11-13; see "Study pipeline" below). `scripts/evaluate.py` remains for a single hand-made CSV of 0/1 rows.
6. Score generation relevance, evidence correctness, usefulness, cognitive alignment and edit burden. Report acceptance among reviewed items separately from pending proposals.
7. Review 2–3 complete agent chains for goal propagation, conflicting recommendations, unsupported conclusions and human correction, or perform a larger interaction-log analysis when data permit.

Open study work: real participants, consent/retention process, ground truth, model comparisons, calibrated confidence, statistical analysis and the final comparative report. The code does not claim to have completed a longitudinal or real-course evaluation.

## Study pipeline (2026-11-13): tooling only, no study has been run

`scripts/study.py` and `backend/knowledge/study_eval.py` turn lecturer labels into figures. They create no label. **No lecturer has used them yet; there are no study results.**

Steps for one course:
1. `python scripts/study.py issues-template --out study/issues.csv`. Each lecturer lists the alignment issues they see, per dimension, **before** looking at the findings of the system. An existing sheet is never overwritten.
2. `python scripts/study.py export --course <id> --out study/` (needs `LECTIO_ACCESS_TOKEN` of the course owner). Writes the findings of the latest audit in random order with empty columns (`findings.csv`), the drafts without model, style, quality score or status (`drafts_blind.csv`), the key that links them back (`drafts_key.json`, keep it from the raters) and `manifest.json` (course, run, mode, model, dimensions the system could not assess).
3. Each rater copies `findings.csv` and fills `valid` (1 valid, 0 not valid, ? cannot judge) and `matches_issue` (the id of their own stage-1 issue this finding corresponds to, if any). Drafts are rated 1 to 5 for relevance, evidence correctness, usefulness and cognitive alignment, plus edit burden (none, minor, major, rewrite).
4. `python scripts/study.py score --issues ... --findings rater1.csv [rater2.csv] --drafts ... --key ... --manifest ... --out study/report` writes `report.json` and `report.md`.

Definitions, fixed before any data:
- Precision = findings judged valid / findings judged 1 or 0. "Cannot judge" and empty rows are counted and shown, not scored.
- Recall = stage-1 issues matched by at least one valid finding / stage-1 issues. The match is made by the rater, not by text similarity.
- F1 from those two. A figure with a zero denominator is "n/a".
- A dimension the system could not assess is an abstention: shown with its missed issues, left out of the totals.
- Agreement: Cohen's kappa on the valid / not valid judgements both raters gave; undefined when all judgements fall in one category.
- Drafts: mean and n per criterion, overall and per model; decisions taken in the application (approved, rejected, revised, pending) and how they relate to the pass or fail of the Stakeholder gate.

Limits: metrics use the first rater's file; combining raters (majority, adjudication) is not implemented. No confidence intervals. Recall depends on how complete the lecturer's own list is. The per-model comparison only means something if drafts from several models exist for the same course.

## Experiment runner and ablations (2026-11-13): run in test mode only

`scripts/run_experiment.py <spec.json> --out <folder>` runs the same course files through several configurations. Each run starts its own server process with an empty database and its own storage folder, so conditions cannot influence each other and the working database is not touched. A condition can change listed settings (`knowledge/experiment.py`, `ALLOWED_ENV`; secrets, database, storage, mode and the trace cannot be changed by a spec), state a course intent, record lecturer rules, or leave documents out. Output: `results.json` (every measurement) and `report.md`.

Measured per run: score and status per dimension, findings by type, objectives and their levels, drafts with the gate result and attempts, model calls and tokens from the trace, trace integrity, seconds. Compared per condition: means over repeats, whether repeated runs give the same findings, and against the first condition (the baseline) which findings appear or disappear and how scores move. A finding is recognised across runs by dimension, type and wording, ignoring run-specific ids, decimal scores and percentages.

**What this is not:** it does not say whether a finding is correct. That needs lecturer labels (study pipeline above).

### Result of `experiments/ablation_test_mode.json` (synthetic English course, test mode, 2 runs per condition)

Test mode calls no model: findings come from the rule-based checks, drafts are fixed templates. Full output: `experiments/results/ablation_test_mode/`.

| Condition | Content and assessment | Delivery | Objectives and assessment | Objectives and content | Findings | Drafts |
|---|---|---|---|---|---|---|
| baseline (all four files) | 28% | 60% | 0% | 71% | 18 | 2 |
| transcript left out | 28% | 38% | 0% | 56% | 17 | 2 |
| exam left out | not assessable | 60% | not assessable | 71% | 5 | 1 |
| course intent stated (analyse, evaluate) | 28% | 60% | 0% | 71% | 22 | 2 |
| one lecturer rule recorded | 28% | 60% | 0% | 71% | 18 | 2 |
| automatic drafts off | 28% | 60% | 0% | 71% | 18 | 0 |
| gate retries off | 28% | 60% | 0% | 71% | 18 | 2 |

What it shows:
- Repeated runs gave the same findings in all seven conditions; every trace verified; no model call and no token in any run.
- Leaving out the exam makes two dimensions "not assessable" instead of producing a low score, and 13 exam-dependent findings disappear.
- Leaving out the transcript removes the two "planned but not delivered" findings and lowers two scores, because the transcript also counts as teaching evidence.
- A stated course intent adds four findings (two levels without an objective, two levels not assessed) and changes no score.
- A lecturer rule and the gate-retry setting change nothing here. That is expected in test mode: template drafts always pass the gate and rules only steer model-written drafts. **Their effect can only be measured with `--live`, which has not been run.**

Limits: one synthetic course; test mode only; two runs per condition; seconds are from one laptop and include server start-up. With `--live` every run sends real requests and repeats are not served from an earlier run's cache, so conditions times repeats audits are spent from the provider quota.

## Bloom classifier: measured against a provisional key (2026-11-12)

Set: `datasets/bloom/labelled.csv`, 120 items (60 English, 60 German). **The labels are provisional**: written during development (AI-assisted) following Anderson & Krathwohl, not reviewed by a lecturer, not real MAAI material. The figures below are agreement with that key, not accuracy on real courses.

| Split | Items | What it contains | Before (word list) | After (rules) |
|---|---|---|---|---|
| dev | 70 | ordinary objectives and questions; rules were adjusted on these | 70.0% | 100% |
| test | 26 | same kind, held out during rule changes | 57.7% | 100% |
| challenge | 24 | purpose clauses, demands hidden in nouns, verbs outside the lexicon; never tuned against | 20.8% | 20.8% |
| all | 120 | | 57.5% | 84.2% |

German alone on dev and test: 50% before, 100% after. Coverage (items given any level) on dev and test: 71% before, 100% after; on challenge 46% before, 50% after.

How to read this:
- The 100% on the held-out split is weak evidence. The same author wrote the items and the rules, so the split shows the rules generalise to phrasing of the same kind, not to real syllabi.
- The challenge split is the realistic warning: about one in five right. The rules fail when the first verb is not the main demand ("use ... to evaluate"), when the demand sits in a noun ("develop an understanding"), when two demands are joined across a clause ("compare ... and decide"), and for verbs outside the lexicon ("sketch", "trace", "schreiben", "herleiten"). Half of these are left unclassified rather than guessed.
- Several verbs belong to more than one level in the literature ("compare", "develop", "write"). One level is chosen per verb; `classify_detail` flags them as ambiguous. The key follows Anderson & Krathwohl (comparing is *understand*); a lecturer who places "compare" under *analyse* will disagree with both key and classifier.

Model-assisted variant: `classify_hybrid` asks the model only for items the rules leave open (optionally also for ambiguous verbs), in one call, with the reply validated item by item. It is wired into course-model extraction in live mode (`BLOOM_LLM_FALLBACK`). **Its accuracy has not been measured**: `python scripts/evaluate_bloom.py --llm` needs a provider key and was not run. The comparison "rules versus rules + model" is therefore still open.

To do before reporting Bloom results: have a lecturer review or replace the key, add real objectives and exam questions from the MAAI courses, run the `--llm` variant on the same file, and report both.

## Extraction: measured against a provisional key (2026-11-13)

Set: `datasets/extraction/cases.json`, 8 synthetic syllabus, module-manual and slide snippets (English and German) with 24 outcome lines and 22 schedule entries, each mixed with look-alikes. **Provisional key, not lecturer-reviewed, not real MAAI material.**

| | Before (line patterns) | After (`knowledge/outline_rules.py`) |
|---|---|---|
| Outcomes, all cases | precision 57% (17 of 30 extracted), recall 71% (17 of 24) | 24 of 24 extracted and expected |
| Outcomes, held-out cases | precision 73%, recall 80% | 10 of 10 |
| Schedule, all cases | precision 74% (14 of 19), recall 64% (14 of 22) | 22 of 22 |
| Schedule, held-out cases | precision 75%, recall 50% | 6 of 6 |

What was wrong before: any line with "able to", "students will/should" or "Lernziel" counted as an outcome (attendance rules, grade announcements, prerequisites); list items under "students will be able to:" were only found for ten hard-coded verbs; a sentence was cut at "1. Mai"; "Wk. 3", "Lecture 4", "2. Woche" and "Week 3 (12 Oct)" were not read as schedule lines; holiday and exam weeks became topics.

The perfect score after the change is weak evidence: the same author wrote the cases and the rules, and there are only eight cases. Not covered: outcomes in tables, outcomes written as running prose without any signal phrase, schedules in table form. Re-run on real module manuals before reporting.

## Retrieval: measured comparison of methods (2026-11-13)

Set: `datasets/retrieval/labelled.json`, 24 synthetic passages and 34 paraphrased queries (11 English, 11 German, 12 cross-language). **Provisional key; a corpus this small makes absolute numbers optimistic.** Embedding model `BAAI/bge-m3` and reranker `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` were run for real. Ranking was done in memory with the application's tokeniser, fusion constant and models, not through the SQL vector store.

MRR / recall@1 / recall@5:

| Method | All | English | German | German query, English passage | English query, German passage |
|---|---|---|---|---|---|
| Keyword (BM25), old tokeniser | 0.52 / 0.44 / 0.65 | 0.91 / 0.82 / 1.00 | 0.62 / 0.45 / 0.91 | 0 / 0 / 0 | 0.17 / 0.17 / 0.17 |
| Keyword (BM25), fixed tokeniser | 0.57 / 0.50 / 0.65 | 0.91 / 0.82 / 1.00 | 0.76 / 0.64 / 0.91 | 0 / 0 / 0 | 0.17 / 0.17 / 0.17 |
| Offline test backend | 0.55 / 0.47 / 0.65 | 0.86 / 0.73 / 1.00 | 0.74 / 0.64 / 0.91 | 0 / 0 / 0 | 0.17 / 0.17 / 0.17 |
| Embeddings only | 0.90 / 0.82 / 1.00 | 0.95 / 0.91 / 1.00 | 0.84 / 0.73 / 1.00 | 0.92 / 0.83 / 1.00 | 0.88 / 0.83 / 1.00 |
| Hybrid (embeddings + BM25, equal rank fusion) | 0.72 / 0.62 / 0.82 | 0.95 / 0.91 / 1.00 | 0.91 / 0.82 / 1.00 | 0.39 / 0.17 / 0.67 | 0.27 / 0.17 / 0.33 |
| Hybrid + reranker (top 20), as the application does | 0.84 / 0.71 / 0.97 | 0.78 / 0.64 / 0.91 | 0.77 / 0.55 / 1.00 | 1.00 / 1.00 / 1.00 | 0.92 / 0.83 / 1.00 |

Findings:
1. **Defect fixed:** the keyword tokeniser only kept `a-z0-9`, so German words were split at umlauts ("schlüssel" became "schl", "ssel"). With whole words, German top-1 rises from 45% to 64%.
2. **Keyword methods cannot cross languages** (0 of 6 German queries find the English passage). Expected, now measured. The offline test backend has the same limit, so automated tests in test mode say nothing about cross-language retrieval.
3. **Equal-weight rank fusion hurts cross-language queries.** A passage found by both lists outranks one found only by embeddings, so same-language keyword hits push the right passage down (MRR 0.39 and 0.27 against 0.92 and 0.88 for embeddings alone). Lowering the keyword weight to 0.2 did not repair it. Same-language queries are not hurt; German improves slightly.
4. **The reranker repairs most of that, at a cost.** With 20 candidates cross-language top-1 returns to 100% and 83%, but same-language top-1 falls (English 91% to 64%, German 82% to 55%). With only 8 candidates the English-to-German group stays at 33%, because the right passage never reaches the reranker.

No change was made to the fusion or reranking in the application on this evidence: in a 24-passage corpus almost every passage appears in both candidate lists, which exaggerates finding 3, and tuning weights on a synthetic set would overfit. This is the first thing to re-measure on a real bilingual course (`python scripts/evaluate_retrieval.py --neural --file ...`). Candidate fixes to test there: fuse only when the keyword list has a strong hit, or rerank a deeper candidate list.
