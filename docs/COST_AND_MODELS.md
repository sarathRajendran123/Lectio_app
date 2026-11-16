# Models, cost controls and reuse

| Role | Model | Notes |
|---|---|---|
| Generation / live review | `nvidia/nemotron-3.5-super-vl:free` (OpenRouter) | Zero-priced in the live catalog (2026-11-03), 1M context, ~10 s on a realistic audit prompt (Ultra ~30 s, which timed out on full prompts); valid JSON. Free models are rate-limited and may be withdrawn: verify, override with `OPENROUTER_MODEL`. Gemma 4 models were rate-limited upstream (shared Google pool) during testing. |
| One-shot fallback | `nvidia/nemotron-3-ultra-550b-a55b:free` | Larger and slower. Tried once on 404/408/429/5xx/timeout; `OPENROUTER_FALLBACK_MODEL=` disables. |
| Embeddings | `BAAI/bge-m3` (local) | Multilingual (German + English), 1024-d, no prefix needed. ~2.3 GB, downloaded once to the `hf_cache` volume. |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (local) | Multilingual replacement for the English-only MS MARCO model. |

## Where calls are avoided
- **LLM result cache** (`$ARTIFACT_STORAGE_PATH/.llm_cache`): key = model, temperature, token cap and full prompt. Only output that passed schema/citation validation is stored, so a bad answer is retried, never replayed. Cached hits report 0 tokens. `LLM_CACHE_ENABLED=false` disables.
- **Capped automatic drafts**: after an audit, `GENERATION_AUTO_ENABLED=true` (default) drafts fixes for the worst gaps only, at most `GENERATION_MAX_ITEMS_PER_RUN=4`, one per gap type first, critical before warning. Re-running an unchanged audit reuses cached text and adds no duplicate drafts. Lecturers can request more via Create drafts (up to 3 alternatives).
- **Embedding cache** (`.embed_cache`): content-addressed by model + text; re-uploads, ingestion retries and unchanged slides are not re-embedded. Query vectors are memoised in-process.
- **Stored vectors reused** for topic clustering (previously every chunk was re-embedded one by one).
- **Retrieval only**: prompts contain at most ~12k characters of retrieved chunks; output capped by `LLM_MAX_TOKENS_AUDIT` / `LLM_MAX_TOKENS_GENERATION` (2000).
- **Deterministic first**: structural/Bloom/verb checks are plain code; the LLM review runs once per dimension only when retrieved evidence exists.
- No retry loops: at most one fallback attempt per call; the 4 dimension reviews stay sequential on purpose (free-tier rate limits).

## Remaining costs
- First live start downloads ~2.8 GB of weights; CPU embedding of a large course takes minutes.
- Free OpenRouter models have daily/per-minute limits and may log prompts per provider policy: do not upload confidential material without checking.

## Free-tier quota (measured 2026-11-03)
- An OpenRouter account without credits gets **50 free-model requests per day** (1000 after buying 10 credits). One audit uses about 5 (up to 4 reviews + 1 outcome derivation); a draft request uses 1 per alternative. Cache hits are free.
- When the daily limit is hit the client stops at once with a clear message (no fallback, no retry) and the report keeps its rule-based score with a "Model review unavailable" note. Resets 00:00 UTC.
- The four model reviews run concurrently, so audit time is the slowest call (free models varied from ~10 s to ~70 s for the same prompt), not the sum. `LLM_REASONING_EFFORT=low` limits hidden thinking tokens (sent as `reasoning.effort`; resent without it if a model rejects it).

## Outcomes derived when none are stated
At audit start, if neither explicit extraction (English and German phrasings) nor the lecturer produced objectives, `services/auto_derive.py` clusters the *taught* material (slides, transcripts; not schedule/grading text), ranks clusters by size, document spread and artefact-type reinforcement, and proposes up to 8 outcomes (`DER-n`, flagged generated, Bloom-classified). One cached model call writes the wording; without a model, a template is used. Stated outcomes always win; derived ones are never added when any exist.
