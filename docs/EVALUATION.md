# Evaluation protocol — no results invented

The exposé defines the course artefact set as the unit of analysis and lecturer utility as the primary criterion. The supplied archive included no labelled real-course corpus or evaluation results. The automated fixtures are synthetic software tests, not evidence of educational validity.

1. Obtain permission to use real MAAI university course materials; retain versioned source IDs, hash checksums and parser warnings.
2. Freeze the course corpus and objective model. Have lecturers independently label alignment units across all four dimensions. Record missing-document and independent-study cases separately from confirmed inconsistencies.
3. Establish ground truth before inspecting the system's predictions. Resolve disagreements and record inter-rater agreement if multiple raters are available.
4. Run each model/prompt configuration against the same corpus. Record provider/model, configuration, run IDs, AgentStep logs, errors, retrieved sources and token counts. Treat any missing/failed dimension as an abstention, not a negative prediction.
5. Export labelled CSV rows with `predicted`, `actual` (0/1), optional `accepted` (0/1) and `quality` (1..5). Define units and matching rules before computing precision/recall. `python scripts/evaluate.py labels.csv` calculates metrics; undefined denominators produce null, not an invented perfect score.
6. Score generation relevance, evidence correctness, usefulness, cognitive alignment and edit burden. Report acceptance among reviewed items separately from pending proposals.
7. Review 2–3 complete agent chains for goal propagation, conflicting recommendations, unsupported conclusions and human correction, or perform a larger interaction-log analysis when data permit.

Open study work: real participants, consent/retention process, ground truth, model comparisons, calibrated confidence, statistical analysis and the final comparative report. The code does not claim to have completed a longitudinal or real-course evaluation.
