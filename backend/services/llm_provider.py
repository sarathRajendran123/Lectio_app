"""Provider selection for lecturer-reviewed draft and audit requests."""
from types import SimpleNamespace

OPENROUTER_ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'


class OpenRouterChat:
    def __init__(self, model, key, timeout, temperature, max_tokens):
        self.model, self.key, self.timeout = model, key, timeout
        self.temperature, self.max_tokens = temperature, max_tokens

    def invoke(self, messages):
        import httpx
        roles = {'system': 'system', 'human': 'user', 'ai': 'assistant'}
        payload = {'model': self.model, 'temperature': self.temperature,
                   'max_tokens': self.max_tokens,
                   'messages': [{'role': roles[m.type], 'content': m.content} for m in messages]}
        try:
            response = httpx.post(OPENROUTER_ENDPOINT, json=payload,
                                  headers={'Authorization': 'Bearer ' + self.key},
                                  timeout=self.timeout, follow_redirects=False)
            response.raise_for_status()
            data = response.json()
            content = data['choices'][0]['message']['content']
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Empty model response')
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            # Never log provider response bodies or credentials.
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            raise RuntimeError('OpenRouter request failed' + (f' (HTTP {status})' if status else '') +
                               '. Check the model, key and connection.') from None
        return SimpleNamespace(content=content, response_metadata={'token_usage': data.get('usage') or {}})


def build_chat(settings, model=None, temperature=.1, max_tokens=4000):
    model = model or settings.active_model
    if not model or not settings.active_api_key:
        raise ValueError(f'{settings.llm_provider} model and API key must be configured.')
    if settings.llm_provider == 'openrouter':
        return OpenRouterChat(model, settings.active_api_key, settings.llm_timeout_seconds, temperature, max_tokens)
    from langchain_groq import ChatGroq
    return ChatGroq(model=model, timeout=settings.llm_timeout_seconds, max_retries=1,
                    groq_api_key=settings.active_api_key, temperature=temperature, max_tokens=max_tokens)
