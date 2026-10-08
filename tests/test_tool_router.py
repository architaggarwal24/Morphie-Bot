from morphie.agent.tool_router import ToolRouter
from morphie.agent.tools import Tool


def test_router_executes_valid_calculator_call():
    router = ToolRouter()
    result = router.execute("calculator", {"expression": "2 + 2"})
    assert result.success is True
    assert result.output == "4"


def test_router_rejects_unknown_tool():
    router = ToolRouter()
    result = router.execute("does_not_exist", {})
    assert result.success is False
    assert "Unknown tool" in result.error


def test_router_rejects_missing_required_argument():
    router = ToolRouter()
    result = router.execute("calculator", {})
    assert result.success is False
    assert "Missing required argument" in result.error


def test_router_rejects_wrong_argument_type():
    router = ToolRouter()
    result = router.execute("calculator", {"expression": 12345})
    assert result.success is False
    assert "should be of type" in result.error


def test_router_rejects_non_dict_arguments():
    router = ToolRouter()
    result = router.execute("calculator", "not a dict")
    assert result.success is False
    assert "must be a JSON object" in result.error


def test_router_catches_unexpected_tool_exception():
    def boom(**kwargs):
        raise RuntimeError("simulated internal failure")

    broken_tool = Tool(
        name="broken",
        description="always fails",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=boom,
    )
    router = ToolRouter(tools=[broken_tool])
    result = router.execute("broken", {})
    assert result.success is False
    # The exception text is deliberately NOT returned (it can hold secrets or paths);
    # see tests/test_tool_hardening.py for the full contract.
    assert "simulated internal failure" not in result.error
    assert "broken" in result.error


def test_router_schemas_include_all_default_tools():
    router = ToolRouter()
    schemas = router.get_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {"calculator", "get_current_time", "web_search"}
