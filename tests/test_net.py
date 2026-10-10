"""morphie.net: `requests` on a normal server, fetch() on Cloudflare Workers (here driven through a fake transport)."""

import pytest

from morphie import net


class FakeTransport:
    def __init__(self, status=200, text="{}", raises=None):
        self.status, self.text, self.raises, self.calls = status, text, raises, []

    def post(self, url, headers, body, timeout_seconds):
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout_seconds})
        if self.raises:
            raise self.raises
        return self.status, self.text, {}


@pytest.fixture
def transport():
    original = net._transport
    t = FakeTransport()
    net.set_transport(t)
    yield t
    net.set_transport(original)


def test_workers_post_sends_json_with_a_content_type_and_parses_the_reply(transport):
    transport.text = '{"ok": true}'
    response = net.workers_post("https://api.example.com/x", json={"a": 1}, headers={"Authorization": "Bearer k"}, timeout=7)
    call = transport.calls[0]
    assert call["body"] == '{"a": 1}' and call["timeout"] == 7
    assert call["headers"]["Content-Type"] == "application/json" and call["headers"]["Authorization"] == "Bearer k"
    assert response.status_code == 200 and response.ok and response.json() == {"ok": True}


def test_workers_post_keeps_a_caller_supplied_content_type(transport):
    net.workers_post("https://x", json={}, headers={"content-type": "application/vnd.x+json"})
    assert "Content-Type" not in transport.calls[0]["headers"]


def test_an_unreadable_body_raises_valueerror_like_requests(transport):
    transport.text = "<html>"
    with pytest.raises(ValueError):
        net.workers_post("https://x", json={}).json()


def test_raise_for_status_raises_on_http_errors(transport):
    transport.status = 503
    response = net.workers_post("https://x", json={})
    assert response.ok is False
    with pytest.raises(net.RequestException):
        response.raise_for_status()


@pytest.mark.parametrize("message", ["TimeoutError: The operation was aborted", "AbortError: aborted"])
def test_fetch_timeouts_become_timeout(transport, message):
    transport.raises = RuntimeError(message)
    with pytest.raises(net.Timeout):
        net.workers_post("https://x", json={}, timeout=1)


def test_other_fetch_failures_become_connection_errors_without_leaking_details(transport):
    transport.raises = RuntimeError("TypeError: Failed to fetch https://api.example.com/?key=sk-secret")
    with pytest.raises(net.ConnectionError) as exc:
        net.workers_post("https://x", json={})
    assert "sk-secret" not in str(exc.value)


def test_on_a_normal_server_post_is_the_real_requests_post_resolved_at_call_time(monkeypatch):
    import requests

    sentinel = object()
    monkeypatch.setattr(requests, "post", lambda *a, **k: sentinel)
    assert net.post("https://x", json={}) is sentinel
    assert net.RequestException is requests.RequestException and net.Timeout is requests.Timeout
