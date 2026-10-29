"""v2 chat endpoints: the transcript survives a reload, Stop really stops, Regenerate/Edit rewind, follow-ups."""

import time

import pytest

import app as app_module
from config import Config
from helpers import ScriptedProvider, text_result, tool_call_result
from morphie.providers.base import ProviderCapabilities
from test_app import _install_fake_provider, _install_fresh_history
from test_streaming_api import parse_sse

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def history(monkeypatch):
    return _install_fresh_history(monkeypatch)


@pytest.fixture
def client(history):
    return app_module.app.test_client()


def _send(client, message, turn_id=None, **extra):
    body = {"message": message, **({"turn_id": turn_id} if turn_id else {}), **extra}
    res = client.post("/chat/stream", json=body, headers=ORIGIN)
    res.data  # read the whole stream, like a page does (an unread stream counts as the page going away)
    return res


def test_the_history_endpoint_returns_what_the_model_remembers(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([text_result("Paris.")]))
    events = parse_sse(_send(client, "capital of France?", "turn-0001").data)
    turn = events[-1][1]["turn"]
    messages = client.get("/chat/history").get_json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [("user", "capital of France?"), ("assistant", "Paris.")]
    assert [m["id"] for m in messages] == [turn["user_message_id"], turn["assistant_message_id"]]
    assert turn["id"] == "turn-0001"


def test_another_browser_sees_none_of_it(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([text_result("Paris.")]))
    _send(client, "capital of France?")
    assert app_module.app.test_client().get("/chat/history").get_json()["messages"] == []


def test_rewind_forgets_a_message_and_what_followed(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([text_result("one"), text_result("two")]))
    _send(client, "first question")
    second = parse_sse(_send(client, "second question").data)[-1][1]["turn"]
    res = client.post("/chat/rewind", json={"before_id": second["user_message_id"]}, headers=ORIGIN)
    assert res.get_json() == {"removed": 2}
    assert [m["content"] for m in client.get("/chat/history").get_json()["messages"]] == ["first question", "one"]


@pytest.mark.parametrize("bad", ["3", -1, True, None])
def test_rewind_validates_its_input(client, bad):
    assert client.post("/chat/rewind", json={"before_id": bad}, headers=ORIGIN).status_code == 400


def test_cancel_removes_a_saved_turn_and_blocks_a_late_one(client, monkeypatch, history):
    _install_fake_provider(monkeypatch, ScriptedProvider([text_result("done")]))
    _send(client, "question", "turn-stop0001")
    assert client.post("/chat/cancel", json={"turn_id": "turn-stop0001"}, headers=ORIGIN).get_json() == {"cancelled": True}
    assert client.get("/chat/history").get_json()["messages"] == []
    # a stop that arrives before the answer is written wins too
    client.post("/chat/cancel", json={"turn_id": "turn-stop0002"}, headers=ORIGIN)
    events = parse_sse(_send(client, "question", "turn-stop0002").data)
    assert events[-1] == ("error", {"message": "That answer was stopped.", "code": "cancelled"})
    assert client.get("/chat/history").get_json()["messages"] == []


def test_cancel_ends_a_running_turn_before_its_next_model_call(client, monkeypatch):
    class SlowTool(ScriptedProvider):
        pass

    provider = ScriptedProvider([tool_call_result("c1", "calculator", '{"expression": "1+1"}'), text_result("2")])
    original_chat = provider.chat

    def slow_chat(messages, tools=None):
        out = original_chat(messages, tools)
        if len(provider.calls) == 1:
            # the person presses Stop while the first answer is on its way
            app_module._active_turns[next(iter(app_module._active_turns))].set()
        return out

    provider.chat = slow_chat
    _install_fake_provider(monkeypatch, provider)
    events = parse_sse(_send(client, "1+1?", "turn-running01").data)
    assert events[-1][1]["code"] == "cancelled"
    assert len(provider.calls) == 1
    assert client.get("/chat/history").get_json()["messages"] == []
    assert app_module._active_turns == {}


def test_bad_turn_ids_and_unknown_tools_are_rejected(client):
    assert _send(client, "hi there friend", "x").status_code == 400
    assert _send(client, "hi there friend", tool="shell").status_code == 400
    assert client.post("/chat/cancel", json={"turn_id": "../etc"}, headers=ORIGIN).status_code == 400


def test_a_tool_command_reaches_the_agent(client, monkeypatch):
    provider = ScriptedProvider([text_result("ok")])
    _install_fake_provider(monkeypatch, provider)
    _send(client, "latest news", tool="web_search")
    assert [t["function"]["name"] for t in provider.calls[0][1]] == ["web_search"]


class StreamingScripted(ScriptedProvider):
    def capabilities(self):
        return ProviderCapabilities(tools=True, vision=False, streaming=True)

    def chat_stream(self, messages, tools=None, on_delta=None, should_cancel=None):
        result = self.chat(messages, tools)
        for word in (result.content or "").split(" "):
            on_delta(word + " ")
        return result


def test_a_streaming_provider_is_streamed_live_not_replayed(client, monkeypatch):
    _install_fake_provider(monkeypatch, StreamingScripted([text_result("alpha beta gamma")]))
    events = parse_sse(_send(client, "three words please").data)
    tokens = [d["text"] for k, d in events if k == "token"]
    assert tokens == ["alpha ", "beta ", "gamma "]            # the provider's own pieces, not the 3-word replay
    assert events[-1][1]["streamed"] is True and events[-1][1]["content"] == "alpha beta gamma"


def test_followups_are_parsed_from_the_model(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([
        text_result("Paris."), text_result('Sure: ["What about Spain?", "Population of Paris?", "Best time to visit?"]'),
    ]))
    _send(client, "capital of France?")
    res = client.post("/chat/followups", json={}, headers=ORIGIN)
    assert res.get_json() == {"suggestions": ["What about Spain?", "Population of Paris?", "Best time to visit?"]}


def test_followups_are_quietly_empty_when_there_is_nothing_or_the_model_fails(client, monkeypatch):
    assert client.post("/chat/followups", json={}, headers=ORIGIN).get_json() == {"suggestions": []}

    def broken(*a, **k):
        raise RuntimeError("down")

    provider = ScriptedProvider([text_result("Paris.")])
    _install_fake_provider(monkeypatch, provider)
    _send(client, "capital of France?")
    monkeypatch.setattr(provider, "chat", broken)
    assert client.post("/chat/followups", json={}, headers=ORIGIN).get_json() == {"suggestions": []}


def test_followups_can_be_turned_off(client, monkeypatch):
    monkeypatch.setattr(Config, "FOLLOWUP_SUGGESTIONS", False)
    assert client.post("/chat/followups", json={}, headers=ORIGIN).get_json() == {"suggestions": []}


def test_parse_followups_accepts_lines_too():
    assert app_module._parse_followups("1. First one?\n2. Second one?\n- Third one?") == ["First one?", "Second one?", "Third one?"]


# ---- Custom URL is the owner's choice ----

def test_custom_url_is_not_offered_or_accepted_unless_the_owner_allows_it(client, monkeypatch):
    headers = {"X-LLM-Provider": "custom", "X-LLM-Base-URL": "http://localhost:1234/v1", **ORIGIN}
    assert "custom" not in {p["id"] for p in client.get("/providers").get_json()["providers"]}
    assert client.post("/chat", json={"message": "what is the meaning of life"}, headers=headers).status_code == 400

    monkeypatch.setattr(Config, "ALLOW_CUSTOM_LLM_URL", True)
    listed = {p["id"]: p for p in client.get("/providers").get_json()["providers"]}
    assert listed["custom"]["needs_base_url"] is True


@pytest.mark.parametrize("url", [
    "", "ftp://x", "http://user:pw@host/v1", "javascript:alert(1)", "http://h/v1?x=1",
    "http://169.254.169.254/latest", "http://2130706433/v1", "http://0.0.0.0:80/v1", "http://metadata.google.internal/v1",
])
def test_custom_url_must_be_a_plain_http_url(client, monkeypatch, url):
    monkeypatch.setattr(Config, "ALLOW_CUSTOM_LLM_URL", True)
    headers = {"X-LLM-Provider": "custom", "X-LLM-Base-URL": url, **ORIGIN}
    res = client.post("/chat", json={"message": "what is the meaning of life"}, headers=headers)
    assert res.status_code == 400 and res.get_json()["code"] == "invalid_base_url"


def test_custom_url_calls_that_server(client, monkeypatch):
    from morphie import net
    sent = []

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"role": "assistant", "content": "local hi"}}]}

    def fake_post(url, json=None, headers=None, timeout=None, data=None, stream=False, **kw):
        sent.append((url, headers, kw))
        return Reply()

    monkeypatch.setattr(net, "post", fake_post)
    monkeypatch.setattr(Config, "ALLOW_CUSTOM_LLM_URL", True)
    headers = {"X-LLM-Provider": "custom", "X-LLM-Base-URL": "http://localhost:1234/v1", "X-LLM-Model": "qwen2.5-7b", **ORIGIN}
    res = client.post("/chat", json={"message": "what is the meaning of life"}, headers=headers)
    assert res.get_json()["content"] == "local hi"
    assert sent[0][0] == "http://localhost:1234/v1/chat/completions" and "Authorization" not in sent[0][1]
    assert sent[0][2].get("allow_redirects") is False      # a redirect can't send it somewhere else


def test_closing_the_stream_mid_answer_stops_the_turn_and_saves_nothing(client, monkeypatch, history):
    def slow(messages, tools):
        time.sleep(0.3)
        return text_result("too late")

    _install_fake_provider(monkeypatch, ScriptedProvider([slow]))
    res = client.post("/chat/stream", json={"message": "long one please", "turn_id": "turn-close001"}, headers=ORIGIN, buffered=False)
    first = next(iter(res.response))          # the "thinking" step: the turn is running
    assert b"thinking" in first
    res.close()                                # the page went away (Stop / closed tab)
    time.sleep(0.5)
    assert all(not msgs for msgs in history._conversations.values())  # nobody's history got "too late"


def test_uploads_are_indexed_by_meaning_with_the_visitors_provider(client, monkeypatch, tmp_path):
    from test_app import _install_fresh_rag_pipeline
    from morphie import net
    _install_fresh_rag_pipeline(monkeypatch, tmp_path)

    class Emb:
        status_code = 200

        def __init__(self, n):
            self.n = n

        def json(self):
            return {"data": [{"index": i, "embedding": [1.0, 0.0]} for i in range(self.n)]}

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(url)
        return Emb(len(json["input"]))

    monkeypatch.setattr(net, "post", fake_post)
    headers = {"X-LLM-Provider": "openai", "X-LLM-Key": "sk-visitor-0123456789", **ORIGIN}
    import io
    res = client.post("/documents/upload", data={"file": (io.BytesIO(b"Python developer resume."), "cv.txt")}, headers=headers)
    assert res.status_code == 201 and res.get_json()["document"]["search"] == "semantic"
    assert calls == ["https://api.openai.com/v1/embeddings"]

    def down(*a, **k):
        raise net.ConnectionError("no")

    monkeypatch.setattr(net, "post", down)
    res = client.post("/documents/upload", data={"file": (io.BytesIO(b"Another file entirely."), "b.txt")}, headers=headers)
    body = res.get_json()
    assert res.status_code == 201 and body["document"]["search"] == "keyword" and "keyword search only" in body["notice"]
