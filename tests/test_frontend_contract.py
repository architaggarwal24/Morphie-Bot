"""The browser UI is a React app in web/ (built by Vite into public/). Its behaviour is tested with Vitest
(web/src/test); these checks guard the seams between it and the Flask app, so a rename on either side fails
here instead of silently breaking the page."""

import re
from pathlib import Path

import app as app_module

ROOT = Path(__file__).resolve().parent.parent
WEB_SRC = ROOT / "web" / "src"
SOURCES = {p: p.read_text(encoding="utf-8") for p in WEB_SRC.rglob("*.ts*") if "test" not in p.parts}
JS = "\n".join(SOURCES.values())


def _called_paths() -> set[str]:
    # `/documents/${id}` is matched up to its slash and normalised to the route prefix
    return {p.rstrip("/") for p in re.findall(r"""(?:fetch|callApi|uploadWithProgress)(?:<[^>]*>)?\(\s*["'`](/[a-z/]+)""", JS)}


def test_every_endpoint_the_ui_calls_is_a_real_route():
    rules = {r.rule.split("<")[0].rstrip("/") or "/" for r in app_module.app.url_map.iter_rules()}
    called = _called_paths()
    assert {
        "/chat/stream", "/chat/reset", "/chat/history", "/chat/rewind", "/chat/cancel", "/chat/followups",
        "/status", "/providers", "/documents", "/documents/upload",
    } <= called
    assert called <= rules, sorted(called - rules)


def test_the_ui_sends_the_byok_headers_the_server_reads():
    server = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    for header in ("X-LLM-Provider", "X-LLM-Model", "X-LLM-Key", "X-LLM-Base-URL"):
        assert header in JS and header in server, header


def test_the_ui_never_logs_or_touches_cookies():
    assert "console." not in JS
    assert "document.cookie" not in JS
    assert "dangerouslySetInnerHTML" not in JS


def test_the_dev_proxy_covers_every_api_route_the_ui_calls():
    vite = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    proxied = set(re.findall(r'"(/[a-z]+)"', vite.split("API_ROUTES")[1].split("]")[0]))
    for path in _called_paths():
        assert "/" + path.strip("/").split("/")[0] in proxied, path


def test_the_static_headers_source_matches_flask():
    flask_csp = app_module.app.test_client().get("/status").headers["Content-Security-Policy"]
    assert f"Content-Security-Policy: {flask_csp}" in (ROOT / "web" / "public" / "_headers").read_text(encoding="utf-8")
