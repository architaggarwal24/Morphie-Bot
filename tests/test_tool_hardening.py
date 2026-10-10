"""Tool abuse resistance: resource exhaustion, error/detail leakage, output size."""

import logging
import time

import pytest
import requests

from config import Config
from morphie.agent.tool_router import MAX_ARGUMENT_CHARS, MAX_TOOL_OUTPUT_CHARS, ToolRouter
from morphie.agent.tools import Tool
from morphie.agent.tools.calculator import MAX_EXPRESSION_CHARS, calculate
from morphie.agent.tools.web_search import (
    StubSearchProvider, TavilySearchProvider, get_search_provider, web_search,
)


# ---------------------------------------------------------------- #
# Calculator
# ---------------------------------------------------------------- #

@pytest.mark.parametrize("expression", [
    "9**9**9**9", "10**10**10", "2**100000", "(10**300)**1000", "pow(9, 9**9)",
    "((10**300)**300)**300", "999999999999**999999999999", "7**7**7**7**7", "2**(10**9)",
    "10**301", "(-2)**100000", "1.5**100000000",
])
def test_enormous_powers_are_refused_immediately_instead_of_hanging_the_server(expression):
    started = time.perf_counter()
    result = calculate(expression)
    assert time.perf_counter() - started < 0.5
    assert "too large" in result.lower()


@pytest.mark.parametrize("expression, expected", [
    ("2**10", "1024"), ("2**-2", "0.25"), ("pow(2, 8)", "256"), ("sqrt(144) + 20", "32.0"),
    ("74500 * 0.18", "13410.0"), ("(12 + 8) * 3", "60"), ("10**300", str(10**300)), ("2**0.5", str(2**0.5)),
    ("0**0", "1"), ("1**1000000", "1"), ("(-1)**1000001", "-1"), ("17 % 5", "2"), ("7 // 2", "3"), ("-(3+4)", "-7"),
])
def test_ordinary_arithmetic_still_works(expression, expected):
    assert calculate(expression) == expected


def test_overlong_expressions_are_refused():
    assert calculate("1+" * MAX_EXPRESSION_CHARS + "1").lower().startswith("could not evaluate")
    assert "too long" in calculate("1+" * MAX_EXPRESSION_CHARS + "1").lower()


def test_pathological_nesting_is_an_error_not_a_crash():
    assert calculate("(" * 400 + "1" + ")" * 400).startswith("Could not evaluate")
    assert calculate("-" * 300 + "1").startswith(("Could not evaluate", "1", "-1"))


def test_results_that_are_not_real_numbers_are_refused():
    assert "real number" in calculate("(-8)**(1/3)")


@pytest.mark.parametrize("expression", [
    "__import__('os').system('id')", "open('/etc/passwd')", "().__class__", "[x for x in range(10**9)]",
    "lambda: 1", "1 if True else 2", "'a' * 10**9", "sqrt(1, 2, 3)", "abs(x=1)", "9 if 1 else 0",
])
def test_code_and_non_arithmetic_input_is_never_evaluated(expression):
    assert calculate(expression).startswith("Could not evaluate")


# ---------------------------------------------------------------- #
# Tool router
# ---------------------------------------------------------------- #

def _tool(handler, name="t"):
    return Tool(name=name, description="d", handler=handler,
                parameters={"type": "object", "properties": {"q": {"type": "string"}}, "required": []})


def test_a_tools_exception_text_is_never_returned_but_is_logged(caplog):
    def boom(**_):
        raise RuntimeError("secret detail: /home/me/.ssh/id_rsa password=hunter2")

    with caplog.at_level(logging.WARNING):
        result = ToolRouter(tools=[_tool(boom, "broken")]).execute("broken", {})
    assert result.success is False
    assert "hunter2" not in result.error and "id_rsa" not in result.error and "RuntimeError" not in result.error
    assert "broken" in result.error                                  # tells the model/user which tool failed
    assert "RuntimeError" in caplog.text                              # ...and the operator can still find out why


def test_tool_output_is_capped_before_it_reaches_the_model():
    result = ToolRouter(tools=[_tool(lambda **_: "x" * 500_000)]).execute("t", {})
    assert result.success and len(result.output) <= MAX_TOOL_OUTPUT_CHARS + 50
    assert "truncated" in result.output


def test_short_output_is_untouched():
    assert ToolRouter(tools=[_tool(lambda **_: "ok")]).execute("t", {}).output == "ok"


def test_oversized_string_arguments_are_rejected_before_the_tool_runs():
    ran = []
    router = ToolRouter(tools=[_tool(lambda **kw: ran.append(kw) or "ran")])
    result = router.execute("t", {"q": "x" * (MAX_ARGUMENT_CHARS + 1)})
    assert result.success is False and "too long" in result.error and ran == []


# ---------------------------------------------------------------- #
# Web search
# ---------------------------------------------------------------- #

def test_search_provider_is_chosen_from_config_at_call_time(monkeypatch):
    monkeypatch.setattr(Config, "TAVILY_API_KEY", None)
    assert isinstance(get_search_provider(), StubSearchProvider)
    monkeypatch.setattr(Config, "TAVILY_API_KEY", "tvly-test")
    provider = get_search_provider()
    assert isinstance(provider, TavilySearchProvider) and provider.api_key == "tvly-test"


def test_tavily_key_travels_in_a_header_not_the_request_body(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": [{"title": "T", "url": "https://x.example", "content": "c" * 500}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers, timeout=timeout)
        return Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    out = TavilySearchProvider("tvly-secret").search("langchain release")
    assert seen["headers"]["Authorization"] == "Bearer tvly-secret"
    assert "tvly-secret" not in str(seen["json"]) and seen["timeout"] <= 15
    assert "x.example" in out and len(out) < 600                       # snippet truncated


def test_search_failures_are_generic_and_do_not_echo_exception_text(monkeypatch, caplog):
    def fail(*a, **k):
        raise requests.ConnectionError("HTTPSConnectionPool(host='api.tavily.com', port=443): key=tvly-secret")

    monkeypatch.setattr(requests, "post", fail)
    with caplog.at_level(logging.WARNING):
        out = TavilySearchProvider("tvly-secret").search("anything")
    assert "tvly-secret" not in out and "HTTPSConnectionPool" not in out
    assert "couldn't" in out.lower() or "could not" in out.lower()
    assert "tvly-secret" not in caplog.text                              # the key never reaches the logs either


def test_unreadable_search_response_is_a_generic_failure(monkeypatch):
    class Resp:
        def raise_for_status(self): pass
        def json(self): raise ValueError("boom")

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    assert "unreadable" in TavilySearchProvider("k").search("q").lower()


def test_web_search_tool_reports_missing_configuration_helpfully(monkeypatch):
    monkeypatch.setattr(Config, "TAVILY_API_KEY", None)
    assert "TAVILY_API_KEY" in web_search("latest langchain release")
