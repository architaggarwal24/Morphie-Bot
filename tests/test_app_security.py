"""Security and robustness checks for the HTTP layer: CSRF, cookies and headers,
rate limits, input validation, the single error shape, and the CSP.

These run against the real Flask app with a scripted fake provider, so they
exercise exactly the code that ships."""

import io

import pytest

import app as app_module
from config import Config

from fixtures import make_txt_bytes
from helpers import ScriptedProvider, text_result

HOST = "localhost"                                     # the Flask test client's default Host
CROSS = {"Origin": "https://evil.example"}


@pytest.fixture
def client():
    return app_module.app.test_client()


def _use(monkeypatch, provider):
    monkeypatch.setattr(app_module, "provider", provider)
    monkeypatch.setattr(app_module.agent, "provider", provider)


def _error_shape(res):
    body = res.get_json()
    assert set(body) >= {"error", "code"} and isinstance(body["error"], str) and body["error"]
    for leaked in ("Traceback", "File \"", ".py", "Exception", "KeyError", "werkzeug"):
        assert leaked not in body["error"], body
    return body


# ---------------------------------------------------------------- #
# CSRF
# ---------------------------------------------------------------- #

UNSAFE = [
    ("post", "/chat", {"json": {"message": "hello"}}),
    ("post", "/chat/stream", {"json": {"message": "hello"}}),
    ("post", "/chat/reset", {"json": {}}),
    ("post", "/documents/upload", {"data": {"file": (io.BytesIO(b"hello world"), "a.txt")}, "content_type": "multipart/form-data"}),
    ("delete", "/documents/some-id", {}),
]


@pytest.mark.parametrize("method, path, kwargs", UNSAFE)
def test_cross_site_state_changing_requests_are_blocked_before_they_do_anything(client, method, path, kwargs):
    res = getattr(client, method)(path, headers=CROSS, **_fresh(kwargs))
    assert res.status_code == 403
    assert _error_shape(res)["code"] == "cross_site"


def _fresh(kwargs):
    """Multipart file objects are consumed once; rebuild them per call."""
    kwargs = dict(kwargs)
    if "data" in kwargs and "file" in kwargs["data"]:
        kwargs["data"] = {"file": (io.BytesIO(b"hello world"), "a.txt")}
    return kwargs


def test_a_cross_site_upload_stores_nothing(client):
    client.post("/documents/upload", headers=CROSS, data={"file": (io.BytesIO(make_txt_bytes("secret notes")), "n.txt")},
                content_type="multipart/form-data")
    assert client.get("/documents").get_json()["documents"] == []


@pytest.mark.parametrize("headers", [
    {}, {"Origin": f"http://{HOST}"}, {"Sec-Fetch-Site": "same-origin"},
])
def test_same_origin_and_non_browser_requests_still_work(client, monkeypatch, headers):
    _use(monkeypatch, ScriptedProvider([text_result("hi")]))
    assert client.post("/chat", json={"message": "what is the capital of France?"}, headers=headers).status_code == 200


def test_sec_fetch_site_cross_site_is_blocked_even_without_an_origin_header(client):
    assert client.post("/chat/reset", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_reading_data_is_not_subject_to_the_origin_check_but_writes_are(client):
    assert client.get("/documents", headers=CROSS).status_code == 200            # a cross-site page can't read the response anyway
    assert client.delete("/documents/x", headers=CROSS).status_code == 403


def test_extra_trusted_origins_can_be_configured(client, monkeypatch):
    monkeypatch.setattr(Config, "TRUSTED_ORIGINS", ["https://morphie.mycorp.example"])
    assert client.post("/chat/reset", json={}, headers={"Origin": "https://morphie.mycorp.example"}).status_code == 200
    assert client.post("/chat/reset", json={}, headers=CROSS).status_code == 403


# ---------------------------------------------------------------- #
# Cookies and headers
# ---------------------------------------------------------------- #

def test_the_session_cookie_is_httponly_and_samesite(client):
    cookie = client.get("/").headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_security_headers_are_present_on_pages_and_api_responses(client):
    for path in ("/", "/documents", "/nope"):
        headers = client.get(path).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_personal_json_is_never_cached_but_the_page_is_unaffected(client):
    for path in ("/documents", "/status"):
        assert client.get(path).headers["Cache-Control"] == "no-store", path
    assert "no-store" not in client.get("/").headers.get("Cache-Control", "")


# ---------------------------------------------------------------- #
# Rate limiting
# ---------------------------------------------------------------- #

def test_chat_is_rate_limited_per_user_with_a_friendly_message_and_retry_hint(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(3, 10))
    _use(monkeypatch, ScriptedProvider([text_result("ok")]))
    codes = [client.post("/chat", json={"message": f"what is {i} plus one?"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    res = client.post("/chat", json={"message": "again?"})
    body = _error_shape(res)
    assert body["code"] == "rate_limited" and "too quickly" in body["content"] and body["content"].startswith("⚠️")
    assert int(res.headers["Retry-After"]) >= 1


def test_one_users_limit_does_not_block_another_user(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(1, 10))
    _use(monkeypatch, ScriptedProvider([text_result("ok")]))
    other = app_module.app.test_client()
    assert client.post("/chat", json={"message": "what is 1+1?"}).status_code == 200
    assert client.post("/chat", json={"message": "what is 1+1?"}).status_code == 429
    assert other.post("/chat", json={"message": "what is 1+1?"}).status_code == 200


def test_uploads_have_their_own_stricter_limit(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(30, 2))
    codes = []
    for i in range(4):
        data = {"file": (io.BytesIO(make_txt_bytes(f"document number {i} " * 5)), f"d{i}.txt")}
        codes.append(client.post("/documents/upload", data=data, content_type="multipart/form-data").status_code)
    assert codes == [201, 201, 429, 429]


def test_reads_and_cheap_writes_are_not_rate_limited(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(1, 1))
    assert all(client.get("/documents").status_code == 200 for _ in range(20))
    assert all(client.get("/status").status_code == 200 for _ in range(20))
    assert all(client.post("/chat/reset", json={}).status_code == 200 for _ in range(20))


def test_limits_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(1, 1, enabled=False))
    _use(monkeypatch, ScriptedProvider([text_result("ok")]))
    assert all(client.post("/chat", json={"message": "what is 1+1?"}).status_code == 200 for _ in range(10))


# ---------------------------------------------------------------- #
# Input validation
# ---------------------------------------------------------------- #

@pytest.mark.parametrize("body", [{"message": 123}, {"message": ["hi"]}, {"message": {"a": 1}}, {"message": True}])
def test_non_string_messages_are_a_clean_400_not_a_crash(client, body):
    res = client.post("/chat", json=body)
    assert res.status_code == 400 and _error_shape(res)["code"] == "invalid_field"
    assert res.get_json()["content"].startswith("⚠️")


@pytest.mark.parametrize("payload", [[], "hello", 5, None])
def test_a_json_body_that_is_not_an_object_is_treated_as_empty(client, payload):
    res = client.post("/chat", json=payload)
    assert res.status_code == 400 and res.get_json()["content"] == "Please enter a message."


def test_overlong_messages_are_rejected_with_the_limit_in_the_message(client):
    res = client.post("/chat", json={"message": "x" * (Config.MAX_MESSAGE_CHARS + 1)})
    assert res.status_code == 413 and "too long" in res.get_json()["error"]
    assert str(Config.MAX_MESSAGE_CHARS)[:1] in res.get_json()["error"]


def test_oversized_json_bodies_are_refused_before_parsing(client):
    res = client.post("/chat", data=b'{"message": "' + b"x" * 300_000 + b'"}', content_type="application/json")
    assert res.status_code == 413 and _error_shape(res)["code"] == "too_large"


@pytest.mark.parametrize("ids", ["all", 5, {"a": 1}, [1, None, {"x": 1}], ["ok"] * 500, [""]])
def test_odd_document_ids_never_break_chat(client, monkeypatch, ids):
    _use(monkeypatch, ScriptedProvider([text_result("fine")]))
    res = client.post("/chat", json={"message": "what does my resume say?", "document_ids": ids})
    assert res.status_code == 200


# ---------------------------------------------------------------- #
# One error shape, and never a traceback
# ---------------------------------------------------------------- #

def test_unknown_routes_and_methods_are_json_errors_not_html_pages(client):
    for res in (client.get("/nope"), client.post("/documents/1"), client.get("/chat")):
        assert res.mimetype == "application/json" and _error_shape(res)["code"] == "http_error"


def test_an_unexpected_exception_becomes_a_generic_500_without_internals(client, monkeypatch, caplog):
    def boom(user_id):
        raise RuntimeError("secret /etc/passwd password=hunter2")

    monkeypatch.setattr(app_module.rag_pipeline, "list_documents", boom)
    res = client.get("/documents")
    body = res.get_json()
    assert res.status_code == 500 and "hunter2" not in str(body) and "passwd" not in str(body) and "Traceback" not in str(body)
    assert "RuntimeError" in caplog.text                                     # ...but the operator's log has it


def test_an_unexpected_failure_inside_chat_shows_a_friendly_message(client, monkeypatch):
    class Broken(ScriptedProvider):
        def chat(self, messages, tools=None):
            raise KeyError("provider")

    _use(monkeypatch, Broken([text_result("x")]))
    res = client.post("/chat", json={"message": "what is the capital of France?"})
    body = res.get_json()
    assert res.status_code == 502 and "KeyError" not in str(body) and "provider'" not in str(body)
    assert body["content"] == "⚠️ Morphie could not complete that request. Please try again."


def test_document_upload_errors_use_the_same_shape(client):
    res = client.post("/documents/upload", data={"file": (io.BytesIO(b"MZ\x90 executable"), "virus.exe")}, content_type="multipart/form-data")
    body = _error_shape(res)
    assert res.status_code == 400 and body["code"] == "upload_rejected" and "Unsupported file type" in body["error"]
    assert client.post("/documents/upload", data={}, content_type="multipart/form-data").get_json()["code"] == "no_file"


def test_an_oversized_upload_is_a_friendly_413(client):
    big = io.BytesIO(b"x" * (Config.RAG_MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 200_000))
    res = client.post("/documents/upload", data={"file": (big, "big.txt")}, content_type="multipart/form-data")
    assert res.status_code == 413 and "too large" in _error_shape(res)["error"]


def test_uploading_the_same_file_twice_reports_a_duplicate_instead_of_reindexing(client):
    def upload():
        return client.post("/documents/upload", content_type="multipart/form-data",
                           data={"file": (io.BytesIO(make_txt_bytes("Quarterly report. Revenue grew 12 percent.")), "q.txt")})

    first, second = upload(), upload()
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.get_json()["duplicate"] is False and second.get_json()["duplicate"] is True
    assert first.get_json()["document"]["id"] == second.get_json()["document"]["id"]
    assert len(client.get("/documents").get_json()["documents"]) == 1


# ---------------------------------------------------------------- #
def test_a_client_that_discards_cookies_is_still_limited_by_ip(client, monkeypatch):
    monkeypatch.setattr(app_module, "_rate_limiters", app_module._build_limiters(2, 10))     # per-IP cap = 5x = 10
    _use(monkeypatch, ScriptedProvider([text_result("ok")]))
    bot = app_module.app.test_client(use_cookies=False)                                       # a fresh identity every time
    codes = [bot.post("/chat", json={"message": "what is 1+1?"}).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]


def test_the_configured_chunk_cap_is_actually_applied_by_the_running_app(client, monkeypatch):
    """Guards against a setting that is defined in config.py but never wired into the pipeline."""
    assert app_module.rag_pipeline.max_chunks_per_document == Config.RAG_MAX_CHUNKS_PER_DOCUMENT
    monkeypatch.setattr(app_module.rag_pipeline, "max_chunks_per_document", 3)
    text = "\n\n".join(f"Paragraph {i}: " + "lorem ipsum dolor sit amet " * 30 for i in range(20))
    res = client.post("/documents/upload", data={"file": (io.BytesIO(make_txt_bytes(text)), "long.txt")}, content_type="multipart/form-data")
    assert res.status_code == 400 and "too large to index" in res.get_json()["error"]
    assert client.get("/documents").get_json()["documents"] == []


# ---------------------------------------------------------------- #
# Content-Security-Policy: scripts may only come from this origin
# ---------------------------------------------------------------- #

def test_the_csp_only_allows_scripts_from_this_origin(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    directives = {d.strip().split(" ", 1)[0]: d.strip() for d in csp.split(";") if d.strip()}
    assert directives["script-src"] == "script-src 'self'"            # no 'unsafe-inline', no CDNs, no 'unsafe-eval'
    assert "unsafe-inline" not in directives["script-src"] and "unsafe-eval" not in csp


def test_the_page_really_has_no_inline_scripts_or_handlers_so_that_csp_can_hold(client):
    """The CSP above is only enforceable because the shell has no inline JS.
    Guard that: an inline <script> or onclick= would be silently blocked in a
    real browser, so catch it here instead."""
    import re

    html = client.get("/").get_data(as_text=True)
    inline_blocks = [body for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I) if body.strip()]
    assert inline_blocks == []
    assert not re.search(r'\son[a-z]+\s*=\s*"', html, re.I)             # no onclick="..." style handlers
    assert not re.search(r"<script[^>]+src=\"https?:", html, re.I)      # no third-party script hosts


def test_the_csp_still_covers_every_response_including_errors(client):
    for path in ("/", "/nope", "/documents"):
        assert "script-src 'self'" in client.get(path).headers["Content-Security-Policy"], path
