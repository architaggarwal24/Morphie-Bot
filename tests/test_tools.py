from morphie.agent.tools.calculator import calculate
from morphie.agent.tools.time import get_current_time
from morphie.agent.tools.web_search import StubSearchProvider, get_search_provider, web_search


# ---- calculator ----

def test_calculator_basic_arithmetic():
    assert calculate("2 + 2") == "4"
    assert calculate("(12 + 8) * 3") == "60"


def test_calculator_supports_whitelisted_functions():
    assert calculate("sqrt(144) + 20") == "32.0"
    assert calculate("round(3.14159, 2)") == "3.14"


def test_calculator_percentage_expressed_as_multiplication():
    # The model is expected to convert "18% of X" into decimal
    # multiplication itself; the tool just evaluates the arithmetic.
    assert calculate("74500 * 0.18") == "13410.0"


def test_calculator_invalid_input_fails_gracefully():
    result = calculate("this is not math")
    assert "Could not evaluate" in result


def test_calculator_division_by_zero_fails_gracefully():
    result = calculate("1/0")
    assert "division by zero" in result


def test_calculator_rejects_code_injection_attempts():
    assert "Could not evaluate" in calculate("__import__('os').system('echo hi')")
    assert "Could not evaluate" in calculate("open('/etc/passwd').read()")


# ---- time ----

def test_time_lookup_by_city_name():
    result = get_current_time("London")
    assert "Unknown location" not in result
    assert "London" in result


def test_time_lookup_by_iana_zone():
    result = get_current_time("Asia/Tokyo")
    assert "Unknown location" not in result


def test_time_lookup_unknown_location_fails_gracefully():
    result = get_current_time("Not/ARealZone")
    assert "Unknown location" in result


# ---- web search ----

def test_web_search_stub_when_unconfigured(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "TAVILY_API_KEY", None)
    assert isinstance(get_search_provider(), StubSearchProvider)
    result = web_search("anything")
    assert "not currently configured" in result
