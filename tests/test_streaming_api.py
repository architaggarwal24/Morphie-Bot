"""
/chat/stream (Server-Sent Events) and /chat/reset ("New chat").

/chat/stream must accept exactly the input /chat does, apply the same
validation, rate limit, and CSRF rules, and its final `message` event must
carry the identical JSON body /chat would have returned - it is a delivery
mechanism, not a second API. See its docstring in app.py for the SSE
event vocabulary (step / token / message / error).
"""

import json

import pytest

import app as app_module
from morphie.providers.base import ProviderNotConfiguredError

from helpers import ScriptedProvider, text_result, tool_call_result
from test_app import _install_fake_provider, _install_fresh_history


def parse_sse(raw: bytes) -> list[tuple[str, dict]]:
    """A full SSE response body -> [(event, data), ...]."""
    text = raw.decode("utf-8")
    events = []
    for frame in (f for f in text.split("\n\n") if f.strip()):
        event_name, data = None, None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((event_name, data))
    return events


def _stream(client, **body):
    res = client.post("/chat/stream", json=body)
    return res, parse_sse(res.data)


@pytest.fixture
def client(monkeypatch):
    _install_fresh_history(monkeypatch)
    return app_module.app.test_client()


# ---------------------------------------------------------------- #
# /chat/stream: contract parity with /chat
# ---------------------------------------------------------------- #

def test_a_plain_reply_streams_steps_tokens_and_a_final_message_event(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([text_result("Paris is the capital of France.")]))
    res, events = _stream(client, message="what is the capital of France?")

    assert res.status_code == 200 and res.mimetype == "text/event-stream"
    assert res.headers["Cache-Control"] == "no-cache"
    kinds = [k for k, _ in events]
    assert kinds[0] == "step" and kinds.count("token") >= 1 and kinds[-1] == "message"
    assert events[0][1] == {"type": "thinking"}
    tokens = "".join(data["text"] for kind, data in events if kind == "token")
    assert tokens == "Paris is the capital of France."
    final = events[-1][1]
    assert final["content"] == "Paris is the capital of France."


def test_the_final_message_event_is_byte_for_byte_the_same_json_chat_would_return(client, monkeypatch):
    scripted = [
        tool_call_result("c1", "calculator", '{"expression": "6*7"}'),
        text_result("6 times 7 is 42."),
    ]
    _install_fake_provider(monkeypatch, ScriptedProvider(list(scripted)))
    normal = client.post("/chat", json={"message": "what is 6 times 7?"}).get_json()

    _install_fake_provider(monkeypatch, ScriptedProvider(list(scripted)))
    _, events = _stream(client, message="what is 6 times 7?")
    streamed = events[-1][1]

    assert streamed == normal


def test_tool_calls_appear_as_live_step_events_in_order(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "1+1"}'), text_result("It's 2."),
    ]))
    _, events = _stream(client, message="what is 1+1?")
    steps = [data for kind, data in events if kind == "step"]
    assert steps == [
        {"type": "thinking"},
        {"type": "tool_call", "tool": "calculator"}, {"type": "tool_result", "tool": "calculator", "success": True},
        {"type": "thinking"},
    ]


def test_a_greeting_streams_with_no_steps_and_no_model_call(client, monkeypatch):
    provider = ScriptedProvider([text_result("should never be called")])
    _install_fake_provider(monkeypatch, provider)
    res, events = _stream(client, message="hello!")
    assert [k for k, _ in events][0] == "token"           # no "step" events at all
    assert not any(k == "step" for k, _ in events)
    assert "Morphie" in events[-1][1]["content"] and provider.calls == []


# ---------------------------------------------------------------- #
# /chat/stream: validation happens before any streaming starts
# ---------------------------------------------------------------- #

@pytest.mark.parametrize("body", [{"message": 123}, {"message": ["hi"]}, {}])
def test_bad_input_is_a_normal_json_4xx_not_a_stream(client, body):
    res = client.post("/chat/stream", json=body)
    assert res.mimetype == "application/json" and res.status_code in (400, 400)
    assert res.get_json()["code"] in ("invalid_field", "empty_message")


def test_an_overlong_message_is_rejected_before_streaming(client):
    from config import Config

    res = client.post("/chat/stream", json={"message": "x" * (Config.MAX_MESSAGE_CHARS + 1)})
    assert res.status_code == 413 and res.mimetype == "application/json"


def test_cross_site_requests_to_stream_are_blocked_before_anything_runs(client, monkeypatch):
    provider = ScriptedProvider([text_result("should never be called")])
    _install_fake_provider(monkeypatch, provider)
    res = client.post("/chat/stream", json={"message": "hi"}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403 and res.mimetype == "application/json" and provider.calls == []


def test_stream_and_chat_share_one_rate_limit_bucket(client, monkeypatch):
    _install_fake_provider(monkeypatch, ScriptedProvider([text_result("a"), text_result("b")]))
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(2, 10))
    first = client.post("/chat", json={"message": "what is 1 plus one?"})
    second = client.post("/chat/stream", json={"message": "what is 2 plus one?"})
    third = client.post("/chat/stream", json={"message": "what is 3 plus one?"})
    assert first.status_code == 200 and second.status_code == 200
    assert third.status_code == 429 and third.mimetype == "application/json"


# ---------------------------------------------------------------- #
# /chat/stream: failures become an `error` event, never a traceback
# ---------------------------------------------------------------- #

def test_an_unconfigured_provider_becomes_an_error_event_with_status_still_200(client, monkeypatch):
    class Off(ScriptedProvider):
        def is_configured(self):
            return False

    _install_fake_provider(monkeypatch, Off([text_result("x")]))
    res, events = _stream(client, message="what is the capital of France?")
    assert res.status_code == 200                                   # headers were already sent as text/event-stream
    kind, data = events[-1]
    assert kind == "error" and data["code"] == "provider_not_configured" and ".env" in data["message"]


def test_an_unexpected_failure_becomes_a_generic_error_event_with_no_internals(client, monkeypatch, caplog):
    class Broken(ScriptedProvider):
        def chat(self, messages, tools=None):
            raise KeyError("provider")

    _install_fake_provider(monkeypatch, Broken([text_result("x")]))
    res, events = _stream(client, message="what is the capital of France?")
    kind, data = events[-1]
    assert kind == "error" and data["code"] == "request_failed"
    assert "KeyError" not in json.dumps(data) and "provider'" not in json.dumps(data)
    assert "KeyError" in caplog.text                                # ...but the operator's log has it


def test_a_provider_rate_limit_error_becomes_a_502_shaped_error_event(client, monkeypatch):
    from morphie.providers.base import ProviderRateLimitError

    def boom(messages, tools):
        raise ProviderRateLimitError("Slow down.")

    _install_fake_provider(monkeypatch, ScriptedProvider([boom]))
    _, events = _stream(client, message="what is the capital of France?")
    kind, data = events[-1]
    assert kind == "error" and data["code"] == "provider_error" and data["message"] == "Slow down."


# ---------------------------------------------------------------- #
# /chat/reset ("New chat")
# ---------------------------------------------------------------- #

def test_reset_clears_the_short_term_conversation_for_this_user(client, monkeypatch):
    history = _install_fresh_history(monkeypatch)
    with client.session_transaction() as sess:
        sess["user_id"] = "u1"
    history.append("u1", "user", "hello")
    history.append("u1", "assistant", "hi")
    assert history.get("u1") != []

    res = client.post("/chat/reset", json={})
    assert res.status_code == 200 and res.get_json() == {"cleared": True}
    assert history.get("u1") == []


def test_reset_does_not_touch_another_users_conversation(client, monkeypatch):
    history = _install_fresh_history(monkeypatch)
    history.append("someone-else", "user", "hello")
    with client.session_transaction() as sess:
        sess["user_id"] = "u1"
    client.post("/chat/reset", json={})
    assert history.get("someone-else") != []


def test_reset_requires_json_and_is_csrf_protected(client):
    assert client.post("/chat/reset", data={}).status_code == 415
    assert client.post("/chat/reset", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_reset_is_not_rate_limited(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(1, 1))
    assert all(client.post("/chat/reset", json={}).status_code == 200 for _ in range(20))
