"""
The MorphieOrchestrator with every real component (agent loop, tool router,
short-term history, RAG pipeline with local embeddings) and only the LLM
scripted: one message in, the right capability out.
"""

import pytest

from morphie.agent.orchestrator import AgentOrchestrator
from morphie.agent.tool_router import ToolRouter
from morphie.history import ConversationHistory
from morphie.orchestrator import GREETING_REPLY, MAX_TOOL_RESULT_CHARS_IN_RESPONSE, MorphieOrchestrator
from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.rag.pipeline import RAGPipeline
from morphie.rag.vector_store import LocalVectorStore

from fixtures import make_txt_bytes
from helpers import ScriptedProvider, text_result, tool_call_result

USER = "user-1"


@pytest.fixture
def parts(tmp_path):
    rag = RAGPipeline(LocalEmbeddingProvider(dim=256), LocalVectorStore(db_path=str(tmp_path / "rag.sqlite3")),
                      upload_dir=str(tmp_path / "docs"), chunk_size=300, chunk_overlap=50, min_score=0.1)
    return dict(rag=rag, history=ConversationHistory(max_messages=20))


@pytest.fixture
def orchestrator(parts):
    return MorphieOrchestrator(
        agent=AgentOrchestrator(ScriptedProvider([]), ToolRouter()),
        tool_router=ToolRouter(), history=parts["history"], rag=parts["rag"],
    )


def _chat(orchestrator, provider, text, document_ids=None, user=USER):
    return orchestrator.handle_chat(user_id=user, text=text, document_ids=document_ids, provider=provider)


# ---- one message in, the right capability out ----

def test_greetings_never_touch_the_model(orchestrator):
    provider = ScriptedProvider([text_result("should not be used")])
    out = _chat(orchestrator, provider, "hello!")
    assert out == {"type": "text", "content": GREETING_REPLY}
    assert provider.calls == []


def test_math_uses_the_calculator(orchestrator):
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "500 * 0.2"}'),
        text_result("20% of 500 is 100."),
    ])
    out = _chat(orchestrator, provider, "What's 20% of 500?")
    assert out["tool_used"] == "calculator"
    assert out["tool_calls"][0]["result"] == "100.0" and out["content"] == "20% of 500 is 100."
    assert len(provider.calls) == 2                                   # tool call + answer, nothing else


def test_a_provider_can_be_supplied_lazily_and_is_only_built_when_needed(orchestrator):
    built = []

    def lazy():
        built.append(1)
        return ScriptedProvider([text_result("hi")])

    assert _chat(orchestrator, lazy, "hello")["content"] == GREETING_REPLY and built == []     # greeting: never built
    assert _chat(orchestrator, lazy, "tell me something")["content"] == "hi" and built == [1]


def test_conversation_history_is_kept_per_user_and_sent_on_the_next_turn(orchestrator, parts):
    first = ScriptedProvider([text_result("Nice to meet you, Sam.")])
    _chat(orchestrator, first, "My name is Sam and I like tea.")
    second = ScriptedProvider([text_result("Tea!")])
    _chat(orchestrator, second, "What do I like?")
    sent = [m["content"] for m in second.calls[0][0]]
    assert any("My name is Sam" in c for c in sent) and any("Nice to meet you" in c for c in sent)

    stranger = ScriptedProvider([text_result("I don't know.")])
    _chat(orchestrator, stranger, "What do I like?", user="someone-else")
    assert not any("Sam" in m["content"] for m in stranger.calls[0][0])         # another user's turns never leak


def test_greetings_are_not_added_to_the_history(orchestrator, parts):
    _chat(orchestrator, ScriptedProvider([]), "hi")
    assert parts["history"].get(USER) == []


def test_documents_are_searched_and_cited_with_real_sources(orchestrator, parts):
    parts["rag"].ingest(USER, "resume.txt", make_txt_bytes(
        "Jane Doe. Skills: Python, Flask, PostgreSQL. Five years of Python experience building data pipelines."))
    provider = ScriptedProvider([
        tool_call_result("d1", "search_documents", '{"query": "Python experience"}'),
        text_result("Your resume says you have five years of Python experience."),
    ])
    out = _chat(orchestrator, provider, "What does my resume say about Python?")
    assert out["tool_used"] == "search_documents"
    assert out["sources"] == [{"document": "resume.txt", "page": None}]
    assert "Five years of Python" in provider.calls[1][0][-1]["content"]      # the model was handed the real text


def test_document_search_can_be_scoped_to_selected_documents(orchestrator, parts):
    parts["rag"].ingest(USER, "a.txt", make_txt_bytes("Alpha document about Python programming."))
    b = parts["rag"].ingest(USER, "b.txt", make_txt_bytes("Beta document about Python cooking."))
    provider = ScriptedProvider([
        tool_call_result("d1", "search_documents", '{"query": "Python"}'), text_result("ok")])
    out = _chat(orchestrator, provider, "What is in my documents about Python?", document_ids=[b.id])
    assert {s["document"] for s in out["sources"]} == {"b.txt"}


def test_large_tool_results_are_shortened_for_the_browser_but_not_for_the_model(orchestrator, parts):
    parts["rag"].ingest(USER, "big.txt", make_txt_bytes("Python " * 400))
    provider = ScriptedProvider([tool_call_result("d1", "search_documents", '{"query": "Python"}'), text_result("done")])
    out = _chat(orchestrator, provider, "What do my documents say about Python?")
    assert len(out["tool_calls"][0]["result"]) <= MAX_TOOL_RESULT_CHARS_IN_RESPONSE + 3
    assert len(provider.calls[1][0][-1]["content"]) > MAX_TOOL_RESULT_CHARS_IN_RESPONSE   # the model saw the full text


def test_errors_from_the_provider_propagate_to_the_caller_to_be_mapped_once(orchestrator):
    from morphie.providers.base import ProviderRateLimitError

    def boom(messages, tools):
        raise ProviderRateLimitError("Slow down.")

    with pytest.raises(ProviderRateLimitError):
        _chat(orchestrator, ScriptedProvider([boom]), "What's the capital of France?")


# ------------------------------------------------------------------ #
# on_step: live progress for streaming UIs
# ------------------------------------------------------------------ #

def test_on_step_is_optional_and_the_default_changes_nothing(orchestrator):
    provider = ScriptedProvider([text_result("Hi!")])
    events = []
    with_events = orchestrator.handle_chat(user_id="a", text="hello there", document_ids=None,
                                           provider=provider, on_step=events.append)
    provider2 = ScriptedProvider([text_result("Hi!")])
    without = orchestrator.handle_chat(user_id="b", text="hello there", document_ids=None, provider=provider2)
    assert with_events == without and events == [{"type": "thinking"}]


def test_a_greeting_emits_no_steps(orchestrator):
    events = []
    orchestrator.handle_chat(user_id="u", text="hello", document_ids=None,
                             provider=ScriptedProvider([]), on_step=events.append)
    assert events == []


def test_chat_turn_reports_thinking_and_tool_events(orchestrator):
    provider = ScriptedProvider([
        tool_call_result("c1", "calculator", '{"expression": "1+1"}'), text_result("It's 2."),
    ])
    events = []
    orchestrator.handle_chat(user_id="u", text="what's 1+1?", document_ids=None,
                             provider=provider, on_step=events.append)
    assert events == [
        {"type": "thinking"}, {"type": "tool_call", "tool": "calculator"},
        {"type": "tool_result", "tool": "calculator", "success": True}, {"type": "thinking"},
    ]
