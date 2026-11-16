# Seeded-defect courses

Three small synthetic courses for `scripts/run_defect_suite.py`.

- `en_clean`: an aligned course. Every finding the audit raises here is a possible false alarm.
- `en_defects`: eight misalignments planted on purpose (see `manifest.json`).
- `de_defects`: five planted misalignments in German.

**Status: synthetic.** Written during development (AI-assisted); not real MAAI material and not reviewed by a lecturer. The suite shows which planted defects the audit finds and which it misses; it is a bug hunt, not an evaluation of usefulness.
