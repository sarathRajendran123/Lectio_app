# Extraction evaluation cases

`cases.json`: 8 short syllabus, module-manual and slide snippets (4 English, 4 German) with the learning-outcome lines and schedule entries a careful reader would extract: 24 outcomes and 22 schedule entries in total.

**Status: provisional and synthetic.** Written during development (AI-assisted). Not real MAAI material, not reviewed by a lecturer. Figures computed from this file are agreement with a provisional key.

Each snippet mixes real outcomes with look-alikes that must not be extracted (attendance and registration rules, prerequisites, "the lecturer will be able to ...", holiday and exam weeks).

Fields: `id`, `language`, `split`, `doc_type` (`syllabus` / `module_manual` are plan documents; `slides` is a delivery document, read strictly and never for the schedule), `text`, `outcomes`, `weeks` (`[number, topic]`).

Comparison ignores list markers, case, spacing and closing punctuation.

`split`: rules were adjusted on `dev` (4 cases); `test` (4 cases) was held out. The same author wrote cases and rules, so the held-out result is weak evidence.

Run: `python scripts/evaluate_extraction.py` (no database or model needed).
