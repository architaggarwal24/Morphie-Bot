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


def _core(events):
    """Just which step happened (the details - input, output preview, timing - are checked separately)."""
    return [{k: v for k, v in e.items() if k in ("type", "tool", "success")} for e in events]


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
    assert _core(events) == [
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
    assert {"type": "tool_result", "tool": "broken", "success": False} in _core(events)


def test_on_step_reports_every_tool_in_a_multi_tool_batch_in_order():
    provider = ScriptedProvider([
        multi_tool_call_result([("c1", "calculator", {"expression": "1+1"}), ("c2", "calculator", {"expression": "2+2"})]),
        text_result("2 and 4."),
    ])
    events = []
    AgentOrchestrator(provider, ToolRouter(tools=[calculator_tool])).run("compute both", on_step=events.append)
    calls = [e for e in _core(events) if e["type"] in ("tool_call", "tool_result")]
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


def test_steps_carry_the_tool_input_a_short_output_and_timing():
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "6*7"}'), text_result("It's 42."),
    ])
    events = []
    AgentOrchestrator(provider, ToolRouter(tools=[calculator_tool])).run("6*7?", on_step=events.append)
    call = next(e for e in events if e["type"] == "tool_call")
    result = next(e for e in events if e["type"] == "tool_result")
    assert call["input"] == "6*7"
    assert "42" in result["output"] and isinstance(result["ms"], int)


def test_web_search_results_become_link_cards():
    from morphie.agent.orchestrator import _links
    out = "- Example News: something happened (https://news.example/a)\n- Other: more (https://other.example/b)"
    assert _links("web_search", out) == [
        {"title": "Example News", "url": "https://news.example/a"}, {"title": "Other", "url": "https://other.example/b"},
    ]
    assert _links("calculator", out) == []


class StreamingProvider(ScriptedProvider):
    """Scripted, but streams: the reply text is handed over in pieces."""

    def capabilities(self):
        from morphie.providers.base import ProviderCapabilities
        return ProviderCapabilities(tools=True, vision=False, streaming=True)

    def chat_stream(self, messages, tools=None, on_delta=None, should_cancel=None):
        result = self.chat(messages, tools)
        if result.content and on_delta:
            for piece in result.content.split(" "):
                on_delta(piece + " ")
        return result


def test_a_streaming_provider_sends_the_answer_as_tokens():
    tokens = []
    out = AgentOrchestrator(StreamingProvider([text_result("one two three")]), ToolRouter()).run("count", on_token=tokens.append)
    assert "".join(tokens).strip() == "one two three" and out["streamed"] is True


def test_text_written_before_a_tool_call_is_withdrawn():
    from morphie.providers.base import ChatResult, ToolCallRequest
    pre = tool_call_result("c1", "calculator", '{"expression": "1+1"}')
    pre = ChatResult(content="Let me check", tool_calls=pre.tool_calls, raw_assistant_message=pre.raw_assistant_message)
    events, tokens = [], []
    AgentOrchestrator(StreamingProvider([pre, text_result("It's 2.")]), ToolRouter(tools=[calculator_tool])).run(
        "1+1?", on_step=events.append, on_token=tokens.append)
    assert {"type": "discard_text"} in events
    assert events.index({"type": "discard_text"}) < next(i for i, e in enumerate(events) if e["type"] == "tool_call")


def test_a_provider_that_cannot_stream_is_not_asked_to():
    tokens = []
    out = AgentOrchestrator(ScriptedProvider([text_result("plain")]), ToolRouter()).run("hi", on_token=tokens.append)
    assert tokens == [] and out["streamed"] is False and out["content"] == "plain"


def test_cancel_stops_before_the_next_model_or_tool_call():
    from morphie.agent.orchestrator import TurnCancelled
    import pytest
    provider = ScriptedProvider([tool_call_result("c1", "calculator", '{"expression": "1+1"}'), text_result("2")])
    stop = {"now": False}

    def on_step(e):
        if e["type"] == "tool_result":
            stop["now"] = True

    with pytest.raises(TurnCancelled):
        AgentOrchestrator(provider, ToolRouter(tools=[calculator_tool])).run(
            "1+1", on_step=on_step, should_cancel=lambda: stop["now"])
    assert len(provider.calls) == 1  # the second model call never happened


def test_a_tool_hint_offers_only_that_tool_first_and_says_so():
    provider = ScriptedProvider([text_result("ok")])
    AgentOrchestrator(provider, ToolRouter()).run("news please", tool_hint="web_search")
    messages, tools = provider.calls[0]
    assert [t["function"]["name"] for t in tools] == ["web_search"]
    assert any("web_search" in m["content"] for m in messages if m["role"] == "system")


def test_an_unknown_tool_hint_is_ignored():
    provider = ScriptedProvider([text_result("ok")])
    AgentOrchestrator(provider, ToolRouter()).run("hi", tool_hint="rm_rf")
    assert len(provider.calls[0][1]) > 1
