# Bloom evaluation set

`labelled.csv`: 120 learning objectives and assessment questions, 60 English and 60 German. 96 ordinary items (8 per cognitive level and language) and 24 deliberately hard ones.

**Status of the labels: provisional.** The items and labels were written during development (AI-assisted), following the process categories of Anderson & Krathwohl (2001). They have **not** been reviewed by a lecturer and are not real MAAI course material. Treat every number computed from this file as agreement with a provisional key, not as measured accuracy on real courses. Replace or extend the file with lecturer-labelled items before reporting results.

Labelling rules used:
- The level is that of the main demand of the item, not of every verb in it ("deconstruct a trace to explain ..." is analyse).
- Coordinated demands take the higher level ("propose and build" is create).
- Following Anderson & Krathwohl, comparing is part of *understand*; differentiating and organising are *analyse*. Many verb lists put "compare" under analyse, so this choice affects results.
- Questions without an action verb are labelled by what they ask for ("What is the running time of ...?" is remember).

Columns: `id`, `language` (en/de), `kind` (objective/question), `split`, `level`, `text`.

`split`: the classifier rules were adjusted while looking only at `dev` errors (70 items); `test` items (26) were held out and looked at only for the final measurement; `challenge` items (24: purpose clauses, demands hidden in nouns, verbs outside the lexicon) were never tuned against. The same author wrote the items and the rules, so even the held-out split is weak evidence.

Run: `python scripts/evaluate_bloom.py` (add `--split test`, or `--llm` for the model-assisted variant, which needs a provider key and uses model calls).
