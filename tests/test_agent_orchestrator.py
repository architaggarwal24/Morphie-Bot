from morphie.agent.orchestrator import SYSTEM_PROMPT, AgentOrchestrator
from morphie.agent.tool_router import ToolRouter
from morphie.agent.tools import Tool
from morphie.agent.tools.calculator import calculator_tool

from helpers import ScriptedProvider, multi_tool_call_result, text_result, tool_call_result


def test_direct_chat_no_tool_needed():
    provider = ScriptedProvider([text_result("Hi there, how can I help?")])
    agent = AgentOrchestrator(provider, ToolRouter())

    result = agent.run("hello")

    assert result["content"] == "Hi there, how can I help?"
    assert result["tool_used"] is None
    assert result["tool_calls"] == []


def test_calculator_tool_call_round_trip():
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "6*7"}'),
        text_result("6 times 7 is 42."),
    ])
    agent = AgentOrchestrator(provider, ToolRouter())

    result = agent.run("what is 6*7?")

    assert result["content"] == "6 times 7 is 42."
    assert result["tool_used"] == "calculator"
    assert result["tool_calls"][0]["result"] == "42"
    assert result["tool_calls"][0]["success"] is True

    # The second request should include the calculator's result in context.
    second_call_messages = provider.calls[1][0]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert tool_msgs[0]["content"] == "42"


def test_malformed_tool_arguments_are_reported_back_to_the_model():
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", "{}"),  # missing required "expression"
        text_result("Sorry, I need a valid expression to calculate that."),
    ])
    agent = AgentOrchestrator(provider, ToolRouter())

    result = agent.run("calculate something")

    assert result["tool_calls"][0]["success"] is False
    assert "Missing required argument" in result["tool_calls"][0]["result"]
    assert result["content"] == "Sorry, I need a valid expression to calculate that."


def test_tool_failure_is_fed_back_and_agent_still_responds():
    def boom(**kwargs):
        raise RuntimeError("simulated failure")

    broken_tool = Tool(
        name="broken",
        description="",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=boom,
    )
    router = ToolRouter(tools=[broken_tool])
    provider = ScriptedProvider([
        tool_call_result("c1", "broken", "{}"),
        text_result("That tool isn't working right now, sorry!"),
    ])
    agent = AgentOrchestrator(provider, router)

    result = agent.run("do the broken thing")

    assert result["tool_calls"][0]["success"] is False
    # The failure is reported generically: exception text never reaches the model or the user.
    assert "simulated failure" not in result["tool_calls"][0]["result"]
    assert "broken" in result["tool_calls"][0]["result"]
    assert result["content"] == "That tool isn't working right now, sorry!"


def test_multiple_tool_calls_in_one_turn():
    provider = ScriptedProvider([
        multi_tool_call_result([
            ("c1", "calculator", {"expression": "2+2"}),
            ("c2", "get_current_time", {"location": "UTC"}),
        ]),
        text_result("2+2 is 4, and I also checked the time."),
    ])
    agent = AgentOrchestrator(provider, ToolRouter())

    result = agent.run("what's 2+2, and what time is it?")

    assert len(result["tool_calls"]) == 2
    assert {c["tool"] for c in result["tool_calls"]} == {"calculator", "get_current_time"}
    assert result["tool_used"] == "calculator, get_current_time"
    assert result["content"] == "2+2 is 4, and I also checked the time."


def test_maximum_tool_call_limit_stops_gracefully():
    call_count = {"n": 0}

    def always_call_tool(messages, tools):
        if tools is None:
            return text_result("Here's my best answer given what I found so far.")
        call_count["n"] += 1
        return tool_call_result(f"c{call_count['n']}", "calculator", '{"expression": "1+1"}')

    provider = ScriptedProvider([always_call_tool] * 20)  # would loop forever without a cap
    agent = AgentOrchestrator(provider, ToolRouter(), max_tool_calls=3)

    result = agent.run("keep calculating forever")

    assert len(result["tool_calls"]) == 3  # stopped exactly at the cap, not more
    assert result["content"] == "Here's my best answer given what I found so far."


def test_fallback_when_provider_does_not_support_tool_calling():
    def flaky(messages, tools):
        if tools is not None:
            raise RuntimeError("this model does not support tool calling")
        return text_result("Plain answer without tools.")

    provider = ScriptedProvider([flaky, flaky])
    agent = AgentOrchestrator(provider, ToolRouter())

    result = agent.run("anything")

    assert result["content"] == "Plain answer without tools."


def test_history_is_included_before_the_current_user_message():
    provider = ScriptedProvider([text_result("ok")])
    agent = AgentOrchestrator(provider, ToolRouter())

    history = [{"role": "user", "content": "earlier message"}, {"role": "assistant", "content": "earlier reply"}]
    agent.run("latest message", history=history)

    sent_messages = provider.calls[0][0]
    assert sent_messages[1]["content"] == "earlier message"
    assert sent_messages[2]["content"] == "earlier reply"
    assert "latest message" in sent_messages[3]["content"]


def test_per_call_tool_router_override_is_used_instead_of_the_default():
    # The default router only has calculator; a per-call router with an
    # extra tool should make that extra tool available for just this call.
    from morphie.agent.tools.base import Tool

    extra_calls = []

    def extra_handler(query):
        extra_calls.append(query)
        return "extra tool result"

    extra_tool = Tool(
        name="extra_tool", description="extra",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=extra_handler,
    )

    provider = ScriptedProvider([
        tool_call_result("c1", "extra_tool", '{"query": "hello"}'),
        text_result("done"),
    ])
    default_router = ToolRouter(tools=[calculator_tool])
    agent = AgentOrchestrator(provider, default_router)

    per_call_router = ToolRouter(tools=[calculator_tool, extra_tool])
    result = agent.run("use the extra tool", tool_router=per_call_router)

    assert extra_calls == ["hello"]
    assert result["tool_calls"][0]["tool"] == "extra_tool"

    # The agent's own default router still only has the calculator - the
    # override didn't mutate shared state.
    assert "extra_tool" not in {s["function"]["name"] for s in default_router.get_schemas()}


# ---------------------------------------------------------------- #
# on_step: live progress events for streaming UIs
# ---------------------------------------------------------------- #

def test_on_step_is_optional_and_changes_nothing_about_the_result():
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "2+2"}'), text_result("It's 4."),
    ])
    router = ToolRouter(tools=[calculator_tool])
    without = AgentOrchestrator(provider, router).run("what is 2+2?")
    provider2 = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "2+2"}'), text_result("It's 4."),
    ])
    with_none = AgentOrchestrator(provider2, router).run("what is 2+2?", on_step=None)
    assert without == with_none


def test_on_step_reports_thinking_for_a_plain_answer_with_no_tools():
    provider = ScriptedProvider([text_result("Hi there!")])
    events = []
    AgentOrchestrator(provider, ToolRouter()).run("hello", on_step=events.append)
    assert events == [{"type": "thinking"}]


def test_on_step_reports_tool_call_and_tool_result_around_execution():
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "2+2"}'), text_result("It's 4."),
    ])
    router = ToolRouter(tools=[calculator_tool])
    events = []
    AgentOrchestrator(provider, router).run("what is 2+2?", on_step=events.append)
    assert events == [
        {"type": "thinking"},
        {"type": "tool_call", "tool": "calculator"},
        {"type": "tool_result", "tool": "calculator", "success": True},
        {"type": "thinking"},
    ]


def test_on_step_reports_a_failed_tool_call():
    def boom(**_):
        raise RuntimeError("nope")

    broken = Tool(name="broken", description="d", handler=boom,
                 parameters={"type": "object", "properties": {}, "required": []})
    provider = ScriptedProvider([tool_call_result("c1", "broken", "{}"), text_result("Sorry, that tool isn't working.")])
    events = []
    AgentOrchestrator(provider, ToolRouter(tools=[broken])).run("do the thing", on_step=events.append)
    assert {"type": "tool_result", "tool": "broken", "success": False} in events


def test_on_step_reports_every_tool_in_a_multi_tool_batch_in_order():
    provider = ScriptedProvider([
        multi_tool_call_result([("c1", "calculator", {"expression": "1+1"}), ("c2", "calculator", {"expression": "2+2"})]),
        text_result("2 and 4."),
    ])
    events = []
    AgentOrchestrator(provider, ToolRouter(tools=[calculator_tool])).run("compute both", on_step=events.append)
    calls = [e for e in events if e["type"] in ("tool_call", "tool_result")]
    assert calls == [
        {"type": "tool_call", "tool": "calculator"}, {"type": "tool_result", "tool": "calculator", "success": True},
        {"type": "tool_call", "tool": "calculator"}, {"type": "tool_result", "tool": "calculator", "success": True},
    ]


def test_on_step_reports_thinking_again_for_the_forced_final_answer(monkeypatch):
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "1+1"}'),
        tool_call_result("c2", "calculator", '{"expression": "1+1"}'),
        text_result("Done."),
    ])
    agent = AgentOrchestrator(provider, ToolRouter(tools=[calculator_tool]), max_tool_calls=2)
    events = []
    agent.run("keep calculating", on_step=events.append)
    # 2 loop iterations (one per tool-call batch, max_tool_calls=2) + 1 forced final answer
    assert events.count({"type": "thinking"}) == 3
    assert events[-1] == {"type": "thinking"}


def test_a_broken_on_step_callback_never_breaks_the_agent_loop(caplog):
    provider = ScriptedProvider([text_result("Still works.")])

    def flaky(event):
        raise ValueError("UI bug")

    result = AgentOrchestrator(provider, ToolRouter()).run("hello", on_step=flaky)
    assert result["content"] == "Still works."
