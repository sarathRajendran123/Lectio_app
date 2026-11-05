"""Minimal OpenRouter chat client (OpenAI-compatible API) used by all LLM call sites.

- Same call shape the code already used (`invoke([...messages]) -> .content, .response_metadata`).
- Validated results are cached on disk: an identical request is never re-sent (no tokens, no rate-limit use).
- At most one fallback model per call; no retry loops.
"""
import hashlib
import json
import logging
import os
import time
from types import SimpleNamespace

import httpx

from config import settings

logger = logging.getLogger(__name__)
_ROLES = {"system": "system", "human": "user", "ai": "assistant"}
_FALLBACK_STATUS = {404, 408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    fatal = False   # retrying or switching model cannot help (e.g. daily quota used up)


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
        body = {"model": model, "messages": msgs, "temperature": self.temperature, "max_tokens": self.max_tokens}
        if settings.llm_reasoning_effort:
            body["reasoning"] = {"effort": settings.llm_reasoning_effort}

        def send(payload):
            return httpx.post(settings.openrouter_base_url.rstrip("/") + "/chat/completions",
                              headers={"Authorization": "Bearer " + settings.openrouter_api_key, "X-Title": "Lectio"},
                              json=payload, timeout=settings.llm_timeout_seconds)
        r = send(body)
        if r.status_code == 400 and "reasoning" in body:   # model rejects the reasoning hint: resend once without it
            body.pop("reasoning")
            r = send(body)
        if r.status_code == 429 and "free-models-per-day" in r.text:
            err = LLMError("The OpenRouter free daily request limit is used up (resets 00:00 UTC). Wait for the reset or add credits.")
            err.fatal = True
            raise err
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        if not content and choice.get("finish_reason") == "length":   # hidden reasoning used the whole budget
            raise LLMError(f"{model} output was cut off at max_tokens={self.max_tokens}; raise the token cap.")
        if data.get("error") or not content:
            raise LLMError(f"Provider returned no content for {model}: {str(data.get('error'))[:200]}")
        if choice.get("finish_reason") == "length":
            raise LLMError(f"{model} output was cut off at max_tokens={self.max_tokens}; raise the token cap.")
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
        transient = True
        for attempt in range(2):  # second pass only after a pause, and only if every failure was transient
            for used in models:
                try:
                    content, tokens = self._post(used, msgs)
                    break
                except LLMError as exc:
                    if exc.fatal:
                        raise
                    if "cut off" in str(exc):
                        transient = False   # more waiting cannot help; the fallback model may be more concise
                    last = exc
                except httpx.TimeoutException as exc:
                    last = exc
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in _FALLBACK_STATUS:
                        raise LLMError(f"Provider rejected the request ({exc.response.status_code}).") from exc
                    last = exc
                logger.warning("LLM call failed for %s (%s)", used, type(last).__name__)
            else:
                if attempt == 0 and transient:
                    time.sleep(max(settings.llm_retry_wait_seconds, 0))
                    continue
                if isinstance(last, LLMError) and "cut off" in str(last):
                    raise last
                raise LLMError(f"All configured models failed: {type(last).__name__}") from last
            break
        if validate:
            validate(content)
        self._cache_put(path, content, used)
        return SimpleNamespace(content=content, response_metadata={
            "token_usage": {"total_tokens": tokens}, "model": used, "cached": False})
