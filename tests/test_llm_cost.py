"""Provider client, cache and cost-control behaviour (HTTP mocked; no network, no model downloads)."""
import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from config import settings
from llm.openrouter import LLMError, OpenRouterChat

MSGS = [SystemMessage(content="sys"), HumanMessage(content="Erkläre Binärsuche.")]


def _reply(text="ok", tokens=7, status=200):
    body = {"choices": [{"message": {"content": text}}], "usage": {"total_tokens": tokens}}
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://x"))


@pytest.fixture
def llm(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_fallback_model", "fallback/model:free")
    calls = []
    return OpenRouterChat(model="primary/model:free"), calls


def _patch_post(monkeypatch, calls, *responses):
    queue = list(responses)

    def post(url, **kw):
        calls.append(kw["json"]["model"])
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(httpx, "post", post)


def test_identical_request_is_served_from_cache(llm, monkeypatch):
    chat, calls = llm
    _patch_post(monkeypatch, calls, _reply("first", 11))
    a = chat.invoke(MSGS)
    b = chat.invoke(MSGS)  # would raise IndexError if it hit the network again
    assert (a.content, b.content) == ("first", "first")
    assert a.response_metadata["token_usage"]["total_tokens"] == 11
    assert b.response_metadata["cached"] and b.response_metadata["token_usage"]["total_tokens"] == 0
    assert len(calls) == 1


def test_invalid_output_is_never_cached(llm, monkeypatch):
    chat, calls = llm
    _patch_post(monkeypatch, calls, _reply("garbage"), _reply('{"a":1}'))

    def need_json(raw):
        import json
        json.loads(raw)
    with pytest.raises(ValueError):
        chat.invoke(MSGS, validate=need_json)
    assert chat.invoke(MSGS, validate=need_json).content == '{"a":1}'
    assert len(calls) == 2


def test_single_bounded_fallback_on_rate_limit(llm, monkeypatch):
    chat, calls = llm
    limited = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    _patch_post(monkeypatch, calls, limited, _reply("from fallback"))
    r = chat.invoke(MSGS)
    assert r.content == "from fallback" and r.response_metadata["model"] == "fallback/model:free"
    assert calls == ["primary/model:free", "fallback/model:free"]


def test_all_models_failing_raises_without_looping(llm, monkeypatch):
    chat, calls = llm
    limited = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    _patch_post(monkeypatch, calls, limited, limited)
    with pytest.raises(LLMError):
        chat.invoke(MSGS)
    assert len(calls) == 2


def test_client_error_does_not_fall_back(llm, monkeypatch):
    chat, calls = llm
    _patch_post(monkeypatch, calls, httpx.Response(401, request=httpx.Request("POST", "http://x")))
    with pytest.raises(LLMError):
        chat.invoke(MSGS)
    assert len(calls) == 1


def test_missing_key_fails_before_any_request(llm, monkeypatch):
    chat, calls = llm
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    _patch_post(monkeypatch, calls)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        chat.invoke(MSGS)
    assert calls == []


def test_secrets_never_in_health_or_status(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-very-secret")
    assert "sk-or-very-secret" not in repr(settings.llm_models)


def test_generation_is_not_automatic_by_default():
    assert settings.generation_auto_enabled is False


def test_embedding_cache_reuses_vectors_and_prefixes(monkeypatch, tmp_path):
    import numpy as np
    from rag.chunking.chunk_models import RawChunk
    from rag.embedding.bge_embedder import BGEEmbedder, _prefixes
    assert _prefixes("BAAI/bge-m3") == ("", "")
    assert _prefixes("intfloat/multilingual-e5-large") == ("query: ", "passage: ")
    assert _prefixes("BAAI/bge-large-en-v1.5")[0].startswith("Represent")
    monkeypatch.setattr(settings, "artifact_storage_path", str(tmp_path))
    seen = []

    class FakeModel:
        def encode(self, texts, **k):
            seen.extend(texts)
            return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)
    emb = BGEEmbedder("BAAI/bge-m3")
    emb._model = FakeModel()
    mk = lambda t, i: RawChunk(text=t, chunk_index=i, artifact_id="a", course_id="c", file_type="txt", artifact_type="slides")
    chunks = [mk("Binärsuche halbiert den Suchraum.", 1), mk("Sortierte Arrays.", 2)]
    first = emb.embed_chunks(chunks)
    again = emb.embed_chunks(chunks + [mk("Neuer Text über Graphen.", 3)])
    assert len(first) == 2 and len(again) == 3
    assert len(seen) == 3  # 2 on first call, only the 1 new chunk on the second
    assert emb.embed_query("Suche") is emb.embed_query("Suche")  # memoised query vector


def test_vectors_from_another_embedding_model_are_ignored(monkeypatch):
    from types import SimpleNamespace as NS
    from vector_db.sql_vector_store import SQLVectorStore
    monkeypatch.setattr(settings, "runtime_mode", "live")
    monkeypatch.setattr(settings, "retrieval_backend", "neural")
    monkeypatch.setattr(settings, "embedding_model", "BAAI/bge-m3")
    mk = lambda cid, model: NS(id=cid, text="t", course_id="c", page_number=1, slide_number=None, section_title=None,
                               week_number=None, embedding_model=model, metadata_={"vector": [1.0, 0.0]})
    art = NS(id="a", artifact_type="slides", original_filename="f.txt")
    rows = [(mk("new", "BAAI/bge-m3"), art), (mk("old", "BAAI/bge-large-en-v1.5"), art)]

    async def fake_rows(course_id):
        return rows
    store = SQLVectorStore()
    monkeypatch.setattr(store, "_rows", fake_rows)
    assert [c.chunk_id for c in store.query("c", [1.0, 0.0])] == ["new"]
