"""Bring your own key: the visitor picks the provider/model/key; the server uses them for that request only."""

import json
import logging

import pytest

import app as app_module
from morphie import net

ORIGIN = {"Origin": "http://localhost"}
KEY = "sk-user-ABCDEF123456abcdef"
OTHER_KEY = "sk-other-ZYXWVU987654zyxwvu"


class ModelReply:
    def __init__(self, content="hi from the model", status=200, body=None):
        self.status_code, self._content, self._body, self.text = status, content, body, ""

    def json(self):
        if self._body is not None:
            return self._body
        return {"choices": [{"message": {"role": "assistant", "content": self._content}}]}


@pytest.fixture
def client(monkeypatch):
    # No server-side key at all, like a hosted deployment where visitors bring their own.
    from config import Config
    monkeypatch.setattr(app_module, "provider", app_module.registry.get("mistral", api_key=None), raising=True)
    monkeypatch.setattr(Config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434", raising=False)
    app_module.history.reset("byok-test")
    return app_module.app.test_client()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, data=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return ModelReply(f"reply {len(calls)}")

    monkeypatch.setattr(net, "post", fake_post)
    return calls


def byok(provider="mistral", key=KEY, model=None):
    h = {"X-LLM-Provider": provider, **ORIGIN}
    if key is not None:
        h["X-LLM-Key"] = key
    if model:
        h["X-LLM-Model"] = model
    return h


# ---- the provider list ----

def test_providers_endpoint_lists_what_the_settings_dialog_can_offer(client):
    data = client.get("/providers").get_json()
    ids = [p["id"] for p in data["providers"]]
    assert set(ids) == {"mistral", "openai", "ollama"}  # ollama is offered when running on your own machine
    mistral = data["providers"][0]
    assert mistral["requires_key"] is True and mistral["default_model"] and mistral["models"]
    assert data["server_default"]["configured"] is False


def test_ollama_is_not_offered_or_accepted_on_a_hosted_deployment(client, monkeypatch):
    monkeypatch.setattr(app_module, "IS_WORKERS", True)
    assert {p["id"] for p in client.get("/providers").get_json()["providers"]} == {"mistral", "openai"}
    res = client.get("/status", headers={"X-LLM-Provider": "ollama"})
    assert res.status_code == 400 and res.get_json()["code"] == "invalid_provider"


# ---- /status reflects the visitor's own choice ----

def test_status_with_a_key_is_configured_and_shows_the_chosen_model(client):
    res = client.get("/status", headers=byok("openai", model="gpt-4.1"))
    assert res.get_json() == {"provider": "OpenAI", "model": "gpt-4.1", "configured": True}


def test_status_defaults_the_model_and_reports_a_missing_key(client):
    assert client.get("/status", headers=byok("mistral", key=None)).get_json() == {
        "provider": "Mistral", "model": "mistral-large-latest", "configured": False}


def test_status_with_no_headers_still_reports_the_servers_own_provider(client):
    assert client.get("/status").get_json()["configured"] is False


@pytest.mark.parametrize("headers,code", [
    ({"X-LLM-Provider": "skynet"}, "invalid_provider"),
    ({"X-LLM-Provider": "openai", "X-LLM-Model": "gpt 4; drop table"}, "invalid_model"),
    ({"X-LLM-Provider": "openai", "X-LLM-Model": "../../etc/passwd"}, "invalid_model"),
    ({"X-LLM-Provider": "openai", "X-LLM-Key": "short"}, "invalid_api_key"),
    ({"X-LLM-Provider": "openai", "X-LLM-Key": "has a space in it 123456"}, "invalid_api_key"),
])
def test_malformed_choices_are_rejected_without_echoing_the_key(client, headers, code):
    res = client.get("/status", headers=headers)
    assert res.status_code == 400 and res.get_json()["code"] == code
    assert headers.get("X-LLM-Key", "\0") not in res.get_data(as_text=True)


# ---- /chat uses the visitor's key, for that request only ----

def test_chat_calls_the_chosen_provider_with_the_visitors_key_and_model(client, sent):
    res = client.post("/chat", json={"message": "What is the capital of France?"}, headers=byok("openai", model="gpt-4.1"))
    assert res.status_code == 200 and res.get_json()["content"] == "reply 1"
    assert sent[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert sent[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert sent[0]["json"]["model"] == "gpt-4.1"


def test_mistral_goes_to_mistrals_endpoint_with_its_default_model(client, sent):
    client.post("/chat", json={"message": "What is the capital of France?"}, headers=byok("mistral"))
    assert sent[0]["url"] == "https://api.mistral.ai/v1/chat/completions"
    assert sent[0]["json"]["model"] == "mistral-large-latest"


def test_two_visitors_keys_never_cross(client, sent):
    other = app_module.app.test_client()
    client.post("/chat", json={"message": "first visitor question"}, headers=byok("openai", key=KEY))
    other.post("/chat", json={"message": "second visitor question"}, headers=byok("openai", key=OTHER_KEY))
    client.post("/chat", json={"message": "first visitor again"}, headers=byok("openai", key=KEY))
    assert [c["headers"]["Authorization"] for c in sent] == [f"Bearer {KEY}", f"Bearer {OTHER_KEY}", f"Bearer {KEY}"]
    assert app_module.provider.api_key is None  # the server's own provider was never given anyone's key


def test_streaming_uses_the_key_even_though_it_runs_on_a_background_thread(client, sent):
    res = client.post("/chat/stream", json={"message": "tell me something nice today"}, headers=byok("openai"))
    assert b"event: message" in res.data and b"reply 1" in res.data
    assert sent[0]["headers"]["Authorization"] == f"Bearer {KEY}"


def test_no_key_gives_an_actionable_error_and_never_calls_the_model(client, sent):
    res = client.post("/chat", json={"message": "What is the capital of France?"}, headers=byok("openai", key=None))
    body = res.get_json()
    assert body["code"] == "provider_not_configured" and "Settings" in body["error"] and res.status_code >= 400
    assert sent == []


def test_a_greeting_still_works_before_any_key_is_set(client, sent):
    assert client.post("/chat", json={"message": "hello"}, headers=byok("openai", key=None)).status_code == 200
    assert sent == []


def test_with_no_headers_the_servers_provider_is_used_exactly_as_before(client, sent):
    res = client.post("/chat", json={"message": "What is the capital of France?"}, headers=ORIGIN)
    assert res.get_json()["code"] == "provider_not_configured" and res.status_code >= 400
    assert "Settings" in res.get_json()["error"] and ".env" in res.get_json()["error"]


# ---- the key is a secret ----

def test_a_rejected_key_gives_a_friendly_error_that_does_not_contain_it(client, monkeypatch, caplog):
    monkeypatch.setattr(net, "post", lambda *a, **k: ModelReply(status=401, body={"error": {"message": f"Incorrect API key provided: {KEY}"}}))
    with caplog.at_level(logging.DEBUG):
        res = client.post("/chat", json={"message": "What is the capital of France?"}, headers=byok("openai"))
    assert res.status_code in (401, 502) and KEY not in res.get_data(as_text=True)
    assert KEY not in caplog.text


def test_a_network_failure_does_not_leak_the_key(client, monkeypatch, caplog):
    def boom(*a, **k):
        raise net.ConnectionError(f"could not reach https://api.openai.com with {KEY}")

    monkeypatch.setattr(net, "post", boom)
    with caplog.at_level(logging.DEBUG):
        res = client.post("/chat/stream", json={"message": "tell me something nice today"}, headers=byok("openai"))
    assert KEY.encode() not in res.data
    assert KEY not in caplog.text


def test_the_key_is_not_stored_in_the_session_cookie_or_history(client, sent):
    client.post("/chat", json={"message": "remember this for me please"}, headers=byok("openai"))
    assert KEY not in str(client.get_cookie("session").value)
    with client.session_transaction() as sess:
        user_id = sess["user_id"]
    assert KEY not in json.dumps(app_module.history.get(user_id))


def test_ollama_works_locally_through_the_servers_configured_url_without_a_key(client, monkeypatch):
    seen = []

    class OllamaReply(ModelReply):
        def json(self):
            return {"message": {"role": "assistant", "content": "local reply"}}

    monkeypatch.setattr(net, "post", lambda url, **k: (seen.append(url), OllamaReply())[1])
    res = client.post("/chat", json={"message": "tell me something nice today"}, headers={"X-LLM-Provider": "ollama", **ORIGIN})
    assert res.status_code == 200 and seen and seen[0].startswith("http://127.0.0.1:11434")
