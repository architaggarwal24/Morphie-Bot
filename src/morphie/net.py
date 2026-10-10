"""A tiny HTTP client with the slice of the `requests` API this project uses (`post`, `Response`, and the
exception classes), and two backends:

  * normal Python: delegates to the real `requests` library, looked up at call time, so test doubles that
    patch `requests.post` (or `morphie.net.post`) keep working.
  * Cloudflare Workers: `requests` cannot open sockets inside Pyodide, so the request goes through the
    platform's `fetch()`. A Python Worker is one synchronous Flask handler, so the awaiting is done with
    `pyodide.ffi.run_sync`.

Providers and tools import this module under the name `requests` (`from .. import net as requests`) so their
code and their tests read exactly as before.
"""

from __future__ import annotations

import json as _json
from typing import Any

from .runtime import IS_WORKERS

try:  # absent on Workers (it isn't a dependency there)
    import requests as _requests
except ImportError:  # pragma: no cover - exercised only on Workers
    _requests = None

if _requests is not None:
    RequestException = _requests.RequestException
    Timeout = _requests.Timeout
    ConnectionError = _requests.ConnectionError  # noqa: A001 - mirrors requests.ConnectionError
    HTTPError = _requests.HTTPError
    Response = _requests.Response
else:  # pragma: no cover - exercised only on Workers
    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        pass

    class ConnectionError(RequestException):  # noqa: A001
        pass

    class HTTPError(RequestException):
        pass

    Response = None  # replaced by WorkersResponse below


class WorkersResponse:
    """The parts of `requests.Response` the providers and tools read."""

    def __init__(self, status_code: int, text: str, headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        try:
            return _json.loads(self.text)
        except ValueError:  # JSONDecodeError subclasses ValueError, like requests' own
            raise ValueError("Response was not valid JSON") from None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"HTTP {self.status_code}")


if _requests is None:  # pragma: no cover
    Response = WorkersResponse


class PyodideFetchTransport:
    """POSTs via the Workers runtime's fetch(). Returns (status, text, headers)."""

    def post(self, url: str, headers: dict, body: str | None, timeout_seconds: float | None) -> tuple[int, str, dict]:
        import js  # noqa: PLC0415 - only exists inside Pyodide
        from pyodide.ffi import run_sync, to_js  # noqa: PLC0415

        init: dict[str, Any] = {"method": "POST", "headers": dict(headers)}
        if body is not None:
            init["body"] = body
        if timeout_seconds:
            init["signal"] = js.AbortSignal.timeout(int(timeout_seconds * 1000))
        js_init = to_js(init, dict_converter=js.Object.fromEntries)
        response = run_sync(js.fetch(url, js_init))
        text = run_sync(response.text())
        return int(response.status), str(text), {}


_transport: Any = PyodideFetchTransport()


def set_transport(transport: Any) -> None:
    """Test hook: replace the Workers fetch backend."""
    global _transport
    _transport = transport


def workers_post(url: str, json: Any = None, headers: dict | None = None, timeout: float | None = None, data: Any = None) -> WorkersResponse:
    headers = dict(headers or {})
    body: str | None
    if json is not None:
        body = _json.dumps(json)
        if not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = "application/json"
    else:
        body = data
    try:
        status, text, response_headers = _transport.post(url, headers, body, timeout)
    except (Timeout, ConnectionError):
        raise
    except Exception as exc:  # noqa: BLE001 - a JS fetch failure surfaces as a JsException with no useful type
        label = f"{type(exc).__name__}: {exc}"
        if "Timeout" in label or "AbortError" in label or "aborted" in label.lower():
            raise Timeout("The request timed out.") from None
        raise ConnectionError("The request could not be completed.") from None
    return WorkersResponse(status, text, response_headers)


def post(*args, **kwargs):
    """requests.post, or fetch() on Workers. `requests` is resolved at call time on purpose."""
    if IS_WORKERS:
        return workers_post(*args, **kwargs)
    return _requests.post(*args, **kwargs)
