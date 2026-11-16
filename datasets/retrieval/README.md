# Retrieval evaluation set

`labelled.json`: 24 passages (12 English, 12 German) and 34 queries with the passages that answer them.

**Status: provisional and synthetic.** Written during development (AI-assisted). Not real MAAI material, not reviewed by a lecturer. With 24 passages the set is far smaller than a real course, so absolute numbers are optimistic; use it to compare methods and to catch regressions.

Query groups (`pair`): `en-en` and `de-de` (11 each, same-language), `de-en` and `en-de` (6 each: the topic exists only in the other language). Queries are paraphrases; none copies a passage. Each language has one organisational passage as a distractor, and some topics are deliberately close (merge sort / quicksort, hash keys / encryption keys).

Metrics: recall@k = share of queries with a relevant passage in the first k results; MRR = mean of 1 / rank of the first relevant passage.

Run: `python scripts/evaluate_retrieval.py` (keyword methods) or `python scripts/evaluate_retrieval.py --neural` (adds the embedding model, rank fusion and the reranker; downloads the models on first use).
