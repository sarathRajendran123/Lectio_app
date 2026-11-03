"""Minimal OpenRouter chat client (OpenAI-compatible API) used by all LLM call sites.

- Same call shape the code already used (`invoke([...messages]) -> .content, .response_metadata`).
- Validated results are cached on disk: an identical request is never re-sent (no tokens, no rate-limit use).
- At most one fallback model per call; no retry loops.
"""
import hashlib
import json
import logging
import os
from types import SimpleNamespace

import httpx

from config import settings

logger = logging.getLogger(__name__)
_ROLES = {"system": "system", "human": "user", "ai": "assistant"}
_FALLBACK_STATUS = {404, 408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


class OpenRouterChat:
    def __init__(self, model: str | None = None, temperature: float = 0.1, max_tokens: int = 2000):
        self.model = model or settings.openrouter_model
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ── cache ─────────────────────────────────────────────────────────────────
    def _payload_messages(self, messages) -> list[dict]:
        return [{"role": _ROLES.get(m.type, "user"), "content": m.content} for m in messages]

    def _cache_path(self, msgs: list[dict]) -> str:
        raw = json.dumps([self.model, self.temperature, self.max_tokens, msgs], sort_keys=True, ensure_ascii=False)
        return os.path.join(settings.llm_cache_dir, hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".json")

    def _cache_get(self, path: str):
        if not settings.llm_cache_enabled:
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _cache_put(self, path: str, content: str, model: str) -> None:
        if not settings.llm_cache_enabled:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"content": content, "model": model}, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            logger.warning("LLM cache write failed; continuing without cache.")

    # ── transport ─────────────────────────────────────────────────────────────
    def _post(self, model: str, msgs: list[dict]) -> tuple[str, int]:
        r = httpx.post(
            settings.openrouter_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + settings.openrouter_api_key, "X-Title": "Lectio"},
            json={"model": model, "messages": msgs, "temperature": self.temperature, "max_tokens": self.max_tokens},
            timeout=settings.llm_timeout_seconds,
        )
        r.raise_for_status()
        data = r.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if data.get("error") or not content:
            raise LLMError(f"Provider returned no content for {model}: {str(data.get('error'))[:200]}")
        return content, int((data.get("usage") or {}).get("total_tokens") or 0)

    def invoke(self, messages, validate=None):
        """Call the model. `validate(content)` runs before caching; if it raises, nothing is cached."""
        msgs = self._payload_messages(messages)
        path = self._cache_path(msgs)
        hit = self._cache_get(path)
        if hit and hit.get("content"):
            return SimpleNamespace(content=hit["content"], response_metadata={
                "token_usage": {"total_tokens": 0}, "model": hit.get("model"), "cached": True})
        if not settings.llm_ready:
            raise ValueError("OPENROUTER_API_KEY is not configured; use local_test for deterministic testing.")
        models = [self.model]
        if settings.openrouter_fallback_model and settings.openrouter_fallback_model != self.model:
            models.append(settings.openrouter_fallback_model)
        last: Exception | None = None
        for used in models:
            try:
                content, tokens = self._post(used, msgs)
                break
            except (httpx.TimeoutException, LLMError) as exc:
                last = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in _FALLBACK_STATUS:
                    raise LLMError(f"Provider rejected the request ({exc.response.status_code}).") from exc
                last = exc
            logger.warning("LLM call failed for %s (%s)", used, type(last).__name__)
        else:
            raise LLMError(f"All configured models failed: {type(last).__name__}") from last
        if validate:
            validate(content)
        self._cache_put(path, content, used)
        return SimpleNamespace(content=content, response_metadata={
            "token_usage": {"total_tokens": tokens}, "model": used, "cached": False})
