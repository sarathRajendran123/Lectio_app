# Experiment report

Course files: `datasets/en_algorithms`. Mode: local_test. Runs per condition: 2. Started: 2026-11-13T09:44:39+00:00.

This report describes what the system did under each configuration. It does not say whether the findings are correct; that needs lecturer labels (`scripts/study.py`).

**Test mode: no language model was called.** Drafts are fixed templates and findings come from the rule-based checks only, so differences between conditions show the effect on those rules, not on model behaviour.

## Conditions

| Condition | What is changed |
|---|---|
| baseline | all four course files, default settings, no course intent, no lecturer rules |
| no_transcript | lecture transcript left out (no check of delivered against planned) |
| no_exam | exam left out |
| with_intent | course intent stated: analyse and evaluate levels expected |
| with_rule | one lecturer rule recorded before the audit |
| no_auto_drafts | automatic drafts after the audit switched off |
| no_gate_retries | Stakeholder gate may not ask for a second attempt |

## Scores per dimension (mean over runs; n/a = the system could not assess it)

| Condition | content assessment | content delivery | metadata assessment | metadata content |
|---|---|---|---|---|
| baseline | 28% | 60% | 0% | 71% |
| no_transcript | 28% | 38% | 0% | 56% |
| no_exam | n/a | 60% | n/a | 71% |
| with_intent | 28% | 60% | 0% | 71% |
| with_rule | 28% | 60% | 0% | 71% |
| no_auto_drafts | 28% | 60% | 0% | 71% |
| no_gate_retries | 28% | 60% | 0% | 71% |

## Findings, drafts and cost

| Condition | Runs finished | Findings (mean) | Same findings in every run | Drafts (mean) | Gate passed | Attempts per draft | Model calls | Tokens | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 2 of 2 | 18.0 | yes | 2.0 | 100% | 1.0 | 0.0 | 0.0 | 13.1 |
| no_transcript | 2 of 2 | 17.0 | yes | 2.0 | 100% | 1.0 | 0.0 | 0.0 | 12.2 |
| no_exam | 2 of 2 | 5.0 | yes | 1.0 | 100% | 1.0 | 0.0 | 0.0 | 11.7 |
| with_intent | 2 of 2 | 22.0 | yes | 2.0 | 100% | 1.0 | 0.0 | 0.0 | 13.3 |
| with_rule | 2 of 2 | 18.0 | yes | 2.0 | 100% | 1.0 | 0.0 | 0.0 | 13.4 |
| no_auto_drafts | 2 of 2 | 18.0 | yes | 0.0 | n/a | n/a | 0.0 | 0.0 | 12.9 |
| no_gate_retries | 2 of 2 | 18.0 | yes | 2.0 | 100% | 1.0 | 0.0 | 0.0 | 13.3 |

## Difference from the baseline (baseline)

### no_transcript

Findings shared with the baseline: 14 (overlap 67%). Score changes: content delivery -22%, metadata content -15%.

Only in the baseline: content_assessment: bloom_level_mismatch; content_delivery: delivery_not_covered (2); metadata_assessment: clo_not_assessed.

Only in this condition: content_assessment: bloom_level_mismatch; metadata_content: clo_not_covered (2).

### no_exam

Findings shared with the baseline: 5 (overlap 28%). Score changes: none.

Only in the baseline: content_assessment: assessment_weak_support; content_assessment: bloom_level_mismatch; content_assessment: topic_not_assessed (5); metadata_assessment: clo_not_assessed (6).

### with_intent

Findings shared with the baseline: 18 (overlap 82%). Score changes: none.

Only in this condition: metadata_assessment: intent_level_not_assessed (2); metadata_content: intent_level_without_objective (2).

### with_rule

Findings shared with the baseline: 18 (overlap 100%). Score changes: none.

### no_auto_drafts

Findings shared with the baseline: 18 (overlap 100%). Score changes: none.

### no_gate_retries

Findings shared with the baseline: 18 (overlap 100%). Score changes: none.
