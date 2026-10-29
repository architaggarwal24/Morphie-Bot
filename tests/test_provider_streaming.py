"""Real token streaming from the providers (OpenAI-style SSE, Ollama's JSON lines) and remote embeddings."""

import json

import pytest

from morphie import net
from morphie.providers.embeddings_remote import EmbeddingError, OllamaEmbeddings, OpenAICompatibleEmbeddings
from morphie.providers.mistral_provider import MistralProvider
from morphie.providers.ollama import OllamaProvider
from morphie.providers.openai import OpenAIProvider


class Lines:
    status_code = 200

    def __init__(self, lines, body=None, status=200):
        self.lines, self.body, self.status_code, self.closed = lines, body, status, False

    def iter_lines(self, decode_unicode=False):
        yield from self.lines

    def json(self):
        return self.body

    def close(self):
        self.closed = True


def sse(obj):
    return "data: " + json.dumps(obj)


def test_openai_streams_text_pieces_in_order(monkeypatch):
    reply = Lines([
        ": comment", "", sse({"choices": [{"delta": {"role": "assistant"}}]}),
        sse({"choices": [{"delta": {"content": "Hel"}}]}), sse({"choices": [{"delta": {"content": "lo"}}]}),
        sse({"choices": []}), "data: [DONE]",
    ])
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return reply

    monkeypatch.setattr(net, "post", fake_post)
    pieces = []
    result = OpenAIProvider("sk-test", "gpt-4o-mini").chat_stream([{"role": "user", "content": "hi"}], on_delta=pieces.append)
    assert pieces == ["Hel", "lo"] and result.content == "Hello" and result.tool_calls == []
    assert seen["stream"] is True and seen["json"]["stream"] is True and reply.closed


def test_openai_stitches_tool_call_fragments_by_index(monkeypatch):
    reply = Lines([
        sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "calculator", "arguments": "{\"expr"}}]}}]}),
        sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "ession\": \"2+2\"}"}}]}}]}),
        "data: [DONE]",
    ])
    monkeypatch.setattr(net, "post", lambda url, **kw: reply)
    result = OpenAIProvider("sk-test", "gpt-4o-mini").chat_stream([{"role": "user", "content": "2+2"}], tools=[{"type": "function"}])
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [("c1", "calculator", {"expression": "2+2"})]
    assert result.raw_assistant_message["tool_calls"][0]["arguments"] == '{"expression": "2+2"}'


def test_mistral_tool_calls_that_arrive_whole_are_understood(monkeypatch):
    reply = Lines([
        sse({"choices": [{"delta": {"tool_calls": [{"id": "m1", "function": {"name": "calculator", "arguments": {"expression": "3*3"}}}]}}]}),
        "data: [DONE]",
    ])
    monkeypatch.setattr(net, "post", lambda url, **kw: reply)
    result = MistralProvider("mk-test-key", "mistral-small-latest").chat_stream([{"role": "user", "content": "3*3"}])
    assert result.tool_calls[0].arguments == {"expression": "3*3"}


def test_streaming_stops_reading_when_cancelled(monkeypatch):
    reply = Lines([sse({"choices": [{"delta": {"content": f"w{i} "}}]}) for i in range(10)])
    monkeypatch.setattr(net, "post", lambda url, **kw: reply)
    pieces = []
    OpenAIProvider("sk-test", "m").chat_stream([], on_delta=pieces.append, should_cancel=lambda: len(pieces) >= 3)
    assert len(pieces) == 3


def test_a_streaming_error_status_is_the_usual_friendly_error(monkeypatch):
    from morphie.providers.base import ProviderAuthError
    monkeypatch.setattr(net, "post", lambda url, **kw: Lines([], body={"error": {"message": "bad key sk-test"}}, status=401))
    with pytest.raises(ProviderAuthError) as info:
        OpenAIProvider("sk-test", "m").chat_stream([])
    assert "sk-test" not in info.value.friendly_message


def test_ollama_streams_json_lines(monkeypatch):
    reply = Lines([
        json.dumps({"message": {"role": "assistant", "content": "Bon"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": "jour"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_current_time", "arguments": {"timezone": "Europe/Paris"}}}]}, "done": True}),
    ])
    monkeypatch.setattr(net, "post", lambda url, **kw: reply)
    pieces = []
    result = OllamaProvider(None, "llama3.1").chat_stream([{"role": "user", "content": "hi"}], on_delta=pieces.append)
    assert pieces == ["Bon", "jour"] and result.content == "Bonjour"
    assert result.tool_calls[0].name == "get_current_time" and result.tool_calls[0].id == "call_0"


def test_workers_responses_can_be_read_line_by_line():
    assert list(net.WorkersResponse(200, "a\nb\n\nc").iter_lines()) == ["a", "b", "", "c"]


# ---- embeddings ----

class Body:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def test_openai_compatible_embeddings_keep_input_order_and_ask_for_small_vectors(monkeypatch):
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return Body({"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})

    monkeypatch.setattr(net, "post", fake_post)
    emb = OpenAICompatibleEmbeddings("openai", "https://api.openai.com/v1", "sk-x", "text-embedding-3-small", 0.25, 512)
    assert emb.embed_batch(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert sent["url"].endswith("/embeddings") and sent["json"]["dimensions"] == 512
    assert sent["headers"]["Authorization"] == "Bearer sk-x"


def test_embedding_failures_are_one_safe_error(monkeypatch):
    monkeypatch.setattr(net, "post", lambda *a, **k: Body({}, status=401))
    with pytest.raises(EmbeddingError) as info:
        OpenAICompatibleEmbeddings("openai", "https://api.openai.com/v1", "sk-secret", "m", 0.25).embed("q")
    assert "sk-secret" not in str(info.value)

    def down(*a, **k):
        raise net.ConnectionError("sk-secret leaked?")

    monkeypatch.setattr(net, "post", down)
    with pytest.raises(EmbeddingError) as info:
        OllamaEmbeddings("http://localhost:11434", "nomic-embed-text", 0.45).embed("q")
    assert "sk-secret" not in str(info.value)


def test_ollama_embeddings(monkeypatch):
    monkeypatch.setattr(net, "post", lambda url, json=None, headers=None, timeout=None: Body({"embeddings": [[0.5, 0.5]]}))
    assert OllamaEmbeddings("http://localhost:11434", "nomic-embed-text", 0.45).embed("q") == [0.5, 0.5]


def test_utf8_survives_streaming_even_when_a_character_spans_chunks(monkeypatch):
    # bytes, as requests yields them; "é" and "ą" are multi-byte, and U+2028 must not split a line
    body = 'data: {"choices": [{"delta": {"content": "h\\u00e9llo \\u0105 \\u2028x"}}]}'.encode()
    raw = json.loads(body[6:])["choices"][0]["delta"]["content"]
    line = ("data: " + json.dumps({"choices": [{"delta": {"content": raw}}]}, ensure_ascii=False)).encode("utf-8")
    monkeypatch.setattr(net, "post", lambda url, **kw: Lines([line, b"data: [DONE]"]))
    pieces = []
    result = OpenAIProvider("sk-test", "m").chat_stream([], on_delta=pieces.append)
    assert result.content == "héllo ą  x" and pieces == [result.content]


def test_a_server_that_ignores_stream_true_still_answers(monkeypatch):
    reply = Lines([], body={"choices": [{"message": {"role": "assistant", "content": "whole answer"}}]})
    reply.headers = {"Content-Type": "application/json"}
    monkeypatch.setattr(net, "post", lambda url, **kw: reply)
    pieces = []
    assert OpenAIProvider("sk-test", "m").chat_stream([], on_delta=pieces.append).content == "whole answer"
    assert pieces == ["whole answer"]


def test_an_error_inside_the_stream_is_a_provider_error_without_the_key(monkeypatch):
    from morphie.providers.base import ProviderError
    monkeypatch.setattr(net, "post", lambda url, **kw: Lines([sse({"error": {"message": "quota for sk-test exceeded"}})]))
    with pytest.raises(ProviderError) as info:
        OpenAIProvider("sk-test", "m").chat_stream([])
    assert "sk-test" not in info.value.friendly_message
    monkeypatch.setattr(net, "post", lambda url, **kw: Lines([json.dumps({"error": "model not loaded"})]))
    with pytest.raises(ProviderError):
        OllamaProvider(None, "m").chat_stream([])


def test_parallel_calls_that_reuse_an_index_stay_separate(monkeypatch):
    reply = Lines([
        sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "calculator", "arguments": "{}"}}]}}]}),
        sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "b", "function": {"name": "get_current_time", "arguments": "{}"}}]}}]}),
    ])
    monkeypatch.setattr(net, "post", lambda url, **kw: reply)
    result = OpenAIProvider("sk-test", "m").chat_stream([])
    assert [c.name for c in result.tool_calls] == ["calculator", "get_current_time"]


def test_text_already_shown_is_withdrawn_before_a_retry():
    from helpers import ScriptedProvider, text_result
    from morphie.agent.orchestrator import AgentOrchestrator
    from morphie.agent.tool_router import ToolRouter
    from morphie.providers.base import ProviderCapabilities

    class Flaky(ScriptedProvider):
        attempts = 0

        def capabilities(self):
            return ProviderCapabilities(tools=True, vision=False, streaming=True)

        def chat_stream(self, messages, tools=None, on_delta=None, should_cancel=None):
            Flaky.attempts += 1
            if Flaky.attempts == 1:
                on_delta("half an ans")
                raise RuntimeError("model rejected the tools parameter")
            on_delta("full answer")
            return text_result("full answer")

    events, tokens = [], []
    out = AgentOrchestrator(Flaky([]), ToolRouter()).run("hi", on_step=events.append, on_token=tokens.append)
    assert out["content"] == "full answer" and {"type": "discard_text"} in events
