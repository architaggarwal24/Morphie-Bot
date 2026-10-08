"""The browser UI is plain HTML + one JS file, so the cheapest way to catch a broken
page is to check the three pieces agree with each other:

  templates/chatbot.html  <->  static/app.js  <->  the Flask routes in app.py

No browser needed. If you rename an element id or an endpoint, one of these fails
instead of the page silently breaking."""

import re
from pathlib import Path

import pytest

import app as app_module

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "templates" / "chatbot.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")


def _html_ids() -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', HTML))


def test_every_element_the_script_looks_up_by_id_exists_in_the_page():
    wanted = set(re.findall(r'getElementById\(\s*["\']([^"\']+)["\']\s*\)', JS))
    assert wanted, "expected app.js to look elements up by id"
    missing = sorted(wanted - _html_ids())
    assert not missing, f"app.js uses ids that chatbot.html does not define: {missing}"


def test_every_query_selector_id_the_script_uses_exists_in_the_page():
    wanted = set(re.findall(r'querySelector(?:All)?\(\s*["\']#([A-Za-z][\w-]*)', JS))
    assert not (wanted - _html_ids()), sorted(wanted - _html_ids())


def test_the_page_has_no_duplicate_ids():
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_every_endpoint_the_script_calls_is_a_real_route():
    called = set(re.findall(r'["\'](/(?:chat(?:/stream|/reset)?|documents(?:/upload)?|status))["\']', JS))
    assert {"/chat/stream", "/chat/reset", "/status", "/documents", "/documents/upload"} <= called
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    assert called <= rules, sorted(called - rules)


def test_the_script_no_longer_references_endpoints_this_project_does_not_have():
    for gone in ("/memory", "/design", "/providers", "/logout"):
        assert f'"{gone}' not in JS and f"'{gone}" not in JS, gone


def test_static_assets_referenced_by_the_page_are_served():
    client = app_module.app.test_client()
    for path in ("/static/app.js", "/static/app.css"):
        assert client.get(path).status_code == 200, path
    for ref in re.findall(r"filename='([^']+)'", HTML):
        assert (ROOT / "static" / ref).exists(), ref


def test_css_classes_used_by_the_page_are_defined():
    used = {c for attr in re.findall(r'class="([^"]+)"', HTML) for c in attr.split() if c.startswith("mp-")}
    defined = set(re.findall(r"\.(mp-[\w-]+)", CSS))
    assert not (used - defined), sorted(used - defined)


@pytest.mark.parametrize("name", ["previewPanel", "memoryPanel", "providerPanel", "designBtn", "memoryBtn", "providerBtn"])
def test_removed_features_leave_no_ui_behind(name):
    assert name not in HTML and name not in JS


def test_the_script_renders_the_welcome_screen_on_load():
    """A top-level (IIFE-indented) call, not one inside a function: without it the chat area is blank on first load."""
    assert re.search(r"^  renderMessages\(\);\s*$", JS, re.M)
    assert re.search(r"^  loadStatus\(\);", JS, re.M)
