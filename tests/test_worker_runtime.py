"""The app as Cloudflare Workers runs it: settings and a D1 binding arrive with every request, state lives in D1,
and the model is reached over HTTP. Driven through the real WSGI bootstrap with a fake `env` and a fake D1."""

import json
import os

import pytest
from werkzeug.test import Client

import app as app_module
import config as config_mod
from fake_d1 import FakeD1Binding, make_d1
from fixtures import make_txt_bytes
from morphie import net


class Env:
    """What a Python Worker's `env` looks like to Python: attributes for vars, secrets and bindings."""

    def __init__(self, **values):
        for k, v in values.items():
            setattr(self, k, v)


class FakeModelResponse:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": self._content}}]}


@pytest.fixture
def worker(monkeypatch):
    """A WSGI client whose every request goes through _WorkersBootstrap, plus the knobs a test needs."""
    # Everything the bootstrap rewrites is put back afterwards, so other test files see the normal app.
    for name in ("provider", "agent", "history", "rag_pipeline", "_rate_limiters"):
        monkeypatch.setattr(app_module, name, getattr(app_module, name))
    monkeypatch.setattr(app_module, "_make_d1", make_d1)
    monkeypatch.setattr(app_module, "IS_WORKERS", True)
    monkeypatch.setattr(config_mod, "IS_WORKERS", True)  # no generated/persisted secret key on a Worker
    saved_secret, saved_env, saved_config = app_module.app.secret_key, dict(os.environ), dict(vars(config_mod.Config))
    binding = FakeD1Binding()
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None, data=None):
        sent.append({"url": url, "json": json, "headers": headers})
        return FakeModelResponse(f"reply {len(sent)}")

    monkeypatch.setattr(net, "post", fake_post)

    class Ctx:
        pass

    ctx = Ctx()
    ctx.binding, ctx.sent = binding, sent
    ctx.env = Env(DB=binding, FLASK_SECRET_KEY="k" * 40, MISTRAL_API_KEY="mk-test", LLM_PROVIDER="mistral",
                  RATE_LIMIT_ENABLED="true", RATE_LIMIT_CHAT_PER_MINUTE="100", RATE_LIMIT_UPLOAD_PER_MINUTE="100")
    ctx.client = Client(app_module._WorkersBootstrap(app_module.app.wsgi_app))

    def call(method, path, **kw):
        kw.setdefault("environ_overrides", {})["workers.env"] = ctx.env
        return getattr(ctx.client, method)(path, **kw)

    ctx.get = lambda path, **kw: call("get", path, **kw)
    ctx.post = lambda path, **kw: call("post", path, **kw)
    ctx.delete = lambda path, **kw: call("delete", path, **kw)
    yield ctx
    app_module.app.secret_key = saved_secret
    os.environ.clear(); os.environ.update(saved_env)
    config_mod.reload_config()
    for k, v in saved_config.items():
        if k.isupper():
            setattr(config_mod.Config, k, v)


def test_settings_and_secrets_come_from_the_request_env(worker):
    res = worker.get("/status")
    assert res.status_code == 200
    assert res.get_json() == {"provider": "Mistral", "model": "mistral-large-latest", "configured": True}


def test_a_different_env_changes_the_provider_on_the_next_request(worker):
    worker.env.LLM_PROVIDER, worker.env.LLM_MODEL = "openai", "gpt-4o-mini"
    worker.env.OPENAI_API_KEY = "sk-test"
    assert worker.get("/status").get_json() == {"provider": "OpenAI", "model": "gpt-4o-mini", "configured": True}


def test_a_missing_secret_key_is_a_clean_error_not_a_crash(worker):
    worker.env.FLASK_SECRET_KEY = ""
    res = worker.get("/status")
    assert res.status_code == 500
    assert res.get_json()["code"] == "not_configured" and "Traceback" not in res.get_data(as_text=True)


def test_a_missing_d1_binding_is_a_clean_error(worker):
    del worker.env.DB
    res = worker.post("/chat", json={"message": "hello there"})
    assert res.status_code == 500 and res.get_json()["code"] == "not_configured"


def test_chat_reaches_the_model_over_http_and_remembers_context_in_d1(worker):
    first = worker.post("/chat", json={"message": "What is the capital of France?"})
    assert first.status_code == 200 and first.get_json()["content"] == "reply 1"
    assert worker.sent[0]["url"] == "https://api.mistral.ai/v1/chat/completions"
    assert worker.sent[0]["headers"]["Authorization"] == "Bearer mk-test"

    second = worker.post("/chat", json={"message": "and Germany?"})
    assert second.get_json()["content"] == "reply 2"
    roles = [(m["role"], m["content"]) for m in worker.sent[1]["json"]["messages"] if m["role"] != "system"]
    assert roles == [("user", "What is the capital of France?"), ("assistant", "reply 1"), ("user", "and Germany?")]

    rows = worker.binding.conn.execute("SELECT role FROM conversation_messages ORDER BY id").fetchall()
    assert [r["role"] for r in rows] == ["user", "assistant", "user", "assistant"]


def test_new_chat_clears_the_remembered_context(worker):
    worker.post("/chat", json={"message": "remember the number 7 please"})
    assert worker.post("/chat/reset", json={}).get_json() == {"cleared": True}
    worker.post("/chat", json={"message": "what did I say?"})
    non_system = [m for m in worker.sent[-1]["json"]["messages"] if m["role"] != "system"]
    assert [m["content"] for m in non_system] == ["what did I say?"]


def test_a_greeting_needs_no_model_call(worker):
    res = worker.post("/chat", json={"message": "hello"})
    assert res.status_code == 200 and worker.sent == []


def test_documents_upload_list_and_delete_through_d1_without_writing_files(worker, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    up = worker.post("/documents/upload", data={"file": (__import__("io").BytesIO(make_txt_bytes("Quarterly revenue grew twelve percent. " * 20)), "report.txt")})
    assert up.status_code == 201
    doc_id = up.get_json()["document"]["id"]
    assert [d["name"] for d in worker.get("/documents").get_json()["documents"]] == ["report.txt"]
    assert list(tmp_path.iterdir()) == []  # nothing was written to disk
    assert worker.delete(f"/documents/{doc_id}").get_json() == {"deleted": True}
    assert worker.get("/documents").get_json()["documents"] == []


def test_another_browser_does_not_see_these_documents(worker):
    worker.post("/documents/upload", data={"file": (__import__("io").BytesIO(make_txt_bytes("Private notes. " * 20)), "mine.txt")})
    other = Client(app_module._WorkersBootstrap(app_module.app.wsgi_app))  # fresh cookie jar = another browser
    res = other.get("/documents", environ_overrides={"workers.env": worker.env})
    assert res.get_json()["documents"] == []


def test_chat_is_rate_limited_across_requests_via_d1(worker):
    worker.env.RATE_LIMIT_CHAT_PER_MINUTE = "2"
    codes = [worker.post("/chat", json={"message": f"question number {i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    assert worker.post("/chat", json={"message": "again please"}).headers["Retry-After"]


def test_the_client_ip_comes_from_cloudflares_header_on_workers(worker):
    worker.env.RATE_LIMIT_CHAT_PER_MINUTE = "1"  # per-IP allowance is 5x
    codes = []
    for i in range(7):
        fresh = Client(app_module._WorkersBootstrap(app_module.app.wsgi_app))  # new cookie each time: only the IP limit applies
        res = fresh.post("/chat", json={"message": f"question number {i}"}, headers={"CF-Connecting-IP": "203.0.113.9"},
                         environ_overrides={"workers.env": worker.env})
        codes.append(res.status_code)
    assert codes[:5] == [200] * 5 and codes[5] == 429
    other = Client(app_module._WorkersBootstrap(app_module.app.wsgi_app)).post(
        "/chat", json={"message": "from elsewhere"}, headers={"CF-Connecting-IP": "198.51.100.4"},
        environ_overrides={"workers.env": worker.env})
    assert other.status_code == 200


def _events(res):
    frames = [f for f in res.get_data(as_text=True).split("\n\n") if f.strip()]
    return [(f.split("\n")[0][7:], json.loads(f.split("\n")[1][6:])) for f in frames]


def test_streaming_works_without_threads_and_emits_the_same_frames(worker):
    res = worker.post("/chat/stream", json={"message": "tell me something nice today"})
    kinds = [k for k, _ in _events(res)]
    assert res.mimetype == "text/event-stream"
    assert kinds[-1] == "message" and "token" in kinds and "error" not in kinds
    assert _events(res)[-1][1]["content"] == "reply 1"


def test_streaming_reports_a_provider_failure_as_an_error_event(worker, monkeypatch):
    def boom(*a, **k):
        raise net.ConnectionError("down")

    monkeypatch.setattr(net, "post", boom)
    events = _events(worker.post("/chat/stream", json={"message": "tell me something nice today"}))
    assert events[-1][0] == "error" and events[-1][1]["code"] == "provider_error"


def test_a_hosted_deployment_with_no_server_key_works_when_the_visitor_brings_one(worker):
    for name in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER"):
        if hasattr(worker.env, name):
            delattr(worker.env, name)
    assert worker.get("/status").get_json()["configured"] is False
    headers = {"X-LLM-Provider": "openai", "X-LLM-Key": "sk-visitor-0123456789abcdef", "X-LLM-Model": "gpt-4o-mini"}
    assert worker.get("/status", headers=headers).get_json() == {"provider": "OpenAI", "model": "gpt-4o-mini", "configured": True}
    res = worker.post("/chat", json={"message": "What is the capital of France?"}, headers=headers)
    assert res.status_code == 200 and res.get_json()["content"] == "reply 1"
    assert worker.sent[0]["headers"]["Authorization"] == "Bearer sk-visitor-0123456789abcdef"
    assert worker.sent[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert "sk-visitor" not in json.dumps(worker.binding.conn.execute("SELECT group_concat(content) FROM conversation_messages").fetchone()[0])


def test_ollama_cannot_be_chosen_on_a_hosted_deployment(worker):
    res = worker.post("/chat", json={"message": "tell me something nice today"}, headers={"X-LLM-Provider": "ollama"})
    assert res.status_code == 400 and res.get_json()["code"] == "invalid_provider"
