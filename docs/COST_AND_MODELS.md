# Models, cost controls and reuse

| Role | Model | Notes |
|---|---|---|
| Generation / live review | `nvidia/nemotron-3-ultra-550b-a55b:free` (OpenRouter) | Zero-priced in the live catalog (2026-11-03), 1M context; passed `scripts/verify_live.py` (schema-valid, citation-checked). Free models are rate-limited and may be withdrawn: verify, override with `OPENROUTER_MODEL`. Gemma 4 models were rate-limited upstream (shared Google pool) during testing. |
| One-shot fallback | `google/gemma-4-31b-it:free` | Different provider than the primary. Tried once on 404/408/429/5xx/timeout; `OPENROUTER_FALLBACK_MODEL=` disables. |
| Embeddings | `BAAI/bge-m3` (local) | Multilingual (German + English), 1024-d, no prefix needed. ~2.3 GB, downloaded once to the `hf_cache` volume. |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (local) | Multilingual replacement for the English-only MS MARCO model. |

## Where calls are avoided
- **LLM result cache** (`$ARTIFACT_STORAGE_PATH/.llm_cache`): key = model, temperature, token cap and full prompt. Only output that passed schema/citation validation is stored, so a bad answer is retried, never replayed. Cached hits report 0 tokens. `LLM_CACHE_ENABLED=false` disables.
- **No automatic generation**: `GENERATION_AUTO_ENABLED` defaults to `false`; drafts are produced when the lecturer asks (Create drafts), up to 3 alternatives per request.
- **Embedding cache** (`.embed_cache`): content-addressed by model + text; re-uploads, ingestion retries and unchanged slides are not re-embedded. Query vectors are memoised in-process.
- **Stored vectors reused** for topic clustering (previously every chunk was re-embedded one by one).
- **Retrieval only**: prompts contain at most ~12k characters of retrieved chunks; output capped by `LLM_MAX_TOKENS_AUDIT` / `LLM_MAX_TOKENS_GENERATION` (2000).
- **Deterministic first**: structural/Bloom/verb checks are plain code; the LLM review runs once per dimension only when retrieved evidence exists.
- No retry loops: at most one fallback attempt per call; the 4 dimension reviews stay sequential on purpose (free-tier rate limits).

## Remaining costs
- First live start downloads ~2.8 GB of weights; CPU embedding of a large course takes minutes.
- Free OpenRouter models have daily/per-minute limits and may log prompts per provider policy: do not upload confidential material without checking.
