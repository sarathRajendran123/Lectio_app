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
from services import trace

logger = logging.getLogger(__name__)
_ROLES = {"system": "system", "human": "user", "ai": "assistant"}
_FALLBACK_STATUS = {404, 408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    fatal = False   # retrying or switching model cannot help (e.g. daily quota used up)


class OpenRouterChat:
    def __init__(self, model: str | None = None, temperature: float = 0.1, max_tokens: int = 2000,
                 prompt_version: str = "unversioned"):
        self.model = model or settings.openrouter_model
        self.prompt_version = prompt_version   # recorded with every call so a trace names the prompt template used
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
        content, usage = self._post_usage(model, msgs)
        return content, int(usage.get("total_tokens") or 0)

    def _post_usage(self, model: str, msgs: list[dict]) -> tuple[str, dict]:
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
        return content, dict(data.get("usage") or {})

    def _record(self, model: str, fp: str, started: float, *, outcome: str, attempt: int, reason: str = "",
                usage: dict | None = None, cached: bool = False, error: str = "") -> None:
        """One trace event per model call. The prompt itself is never stored, only its fingerprint and size."""
        usage = usage or {}
        trace.emit("model_call", {
            "provider": "openrouter", "model": model, "prompt_version": self.prompt_version, "prompt_fingerprint": fp,
            "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
            "tokens_total": int(usage.get("total_tokens") or 0), "cost": usage.get("cost"), "cached": cached,
            "duration_ms": int((time.monotonic() - started) * 1000), "outcome": outcome, "error": error[:300],
            "attempt": attempt, "retry_reason": reason, "temperature": self.temperature, "max_tokens": self.max_tokens})

    def invoke(self, messages, validate=None):
        """Call the model. `validate(content)` runs before caching; if it raises, nothing is cached."""
        msgs = self._payload_messages(messages)
        fp = trace.fingerprint(msgs)
        path = self._cache_path(msgs)
        started = time.monotonic()
        hit = self._cache_get(path)
        if hit and hit.get("content"):
            try:
                if validate:
                    validate(hit['content'])
            except Exception as exc:
                # A cached answer can predate the current validation rules.
                # Reject it before use, then obtain and validate a fresh answer.
                self._record(hit.get('model') or self.model, fp, started,
                             outcome='rejected_by_validation', attempt=0, cached=True, error=str(exc))
            else:
                self._record(hit.get("model") or self.model, fp, started, outcome="ok", attempt=0, cached=True)
                return SimpleNamespace(content=hit["content"], response_metadata={
                    "token_usage": {"total_tokens": 0}, "model": hit.get("model"), "cached": True})
        if not settings.llm_ready:
            raise ValueError("OPENROUTER_API_KEY is not configured; use local_test for deterministic testing.")
        models = [self.model]
        if settings.openrouter_fallback_model and settings.openrouter_fallback_model != self.model:
            models.append(settings.openrouter_fallback_model)
        last: Exception | None = None
        transient = True
        number, reason = 0, ""
        for attempt in range(2):  # second pass only after a pause, and only if every failure was transient
            for used in models:
                number += 1
                started = time.monotonic()
                try:
                    content, usage = self._post_usage(used, msgs)
                    break
                except LLMError as exc:
                    self._record(used, fp, started, outcome="error", attempt=number, reason=reason, error=str(exc))
                    if exc.fatal:
                        raise
                    if "cut off" in str(exc):
                        transient = False   # more waiting cannot help; the fallback model may be more concise
                    last = exc
                except httpx.TimeoutException as exc:
                    self._record(used, fp, started, outcome="timeout", attempt=number, reason=reason, error=type(exc).__name__)
                    last = exc
                except httpx.HTTPStatusError as exc:
                    self._record(used, fp, started, outcome="error", attempt=number, reason=reason,
                                 error=f"HTTP {exc.response.status_code}")
                    if exc.response.status_code not in _FALLBACK_STATUS:
                        raise LLMError(f"Provider rejected the request ({exc.response.status_code}).") from exc
                    last = exc
                reason = f"previous attempt failed: {type(last).__name__}"
                logger.warning("LLM call failed for %s (%s)", used, type(last).__name__)
            else:
                if attempt == 0 and transient:
                    time.sleep(max(settings.llm_retry_wait_seconds, 0))
                    continue
                if isinstance(last, LLMError) and "cut off" in str(last):
                    raise last
                raise LLMError(f"All configured models failed: {type(last).__name__}") from last
            break
        tokens = int(usage.get("total_tokens") or 0)
        if validate:
            try:
                validate(content)
            except Exception as exc:
                self._record(used, fp, started, outcome="rejected_by_validation", attempt=number, reason=reason, usage=usage,
                             error=str(exc))
                raise
        self._record(used, fp, started, outcome="ok", attempt=number, reason=reason, usage=usage)
        self._cache_put(path, content, used)
        return SimpleNamespace(content=content, response_metadata={
            "token_usage": {"total_tokens": tokens}, "model": used, "cached": False})
