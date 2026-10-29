"""
Morphie orchestrator: the single entry point the Flask layer talks to.

    Flask API
       |
    MorphieOrchestrator.handle_chat()
       |
       +-- greeting ------> canned reply, no model call
       |
       '-- anything else -> Agent loop (agent/orchestrator.py)
                              |- Tools: calculator, clock, web search
                              '- RAG: search_documents over the user's uploads
       |
    LLMProvider (Mistral, OpenAI or Ollama - chosen in .env)

The orchestrator holds no HTTP concepts: it takes the user id, the message
and the provider to use, and returns a plain dict. Errors (ProviderError,
...) propagate to the caller, which is the one place that turns them into
user-facing responses.
"""

from __future__ import annotations

from typing import Callable

from .agent.orchestrator import AgentOrchestrator, TurnCancelled
from .agent.tool_router import ToolRouter
from .agent.tools.document_search import DocumentSearchTool
from .history import ConversationHistory
from .providers.base import LLMProvider
from .providers.embeddings import EmbeddingProvider
from .rag.pipeline import RAGPipeline
from .routing import is_greeting

GREETING_REPLY = "Hey 👋 I’m Morphie."
MAX_TOOL_RESULT_CHARS_IN_RESPONSE = 300


def _public_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Tool calls as sent to the browser. Results can be large (document
    text, search results) and the UI only needs to know *which* tools ran,
    so results are shortened; the full text was already given to the model."""
    shortened = []
    for call in tool_calls:
        result = str(call.get("result", ""))
        if len(result) > MAX_TOOL_RESULT_CHARS_IN_RESPONSE:
            result = result[:MAX_TOOL_RESULT_CHARS_IN_RESPONSE] + "..."
        shortened.append({**call, "result": result})
    return shortened


class MorphieOrchestrator:
    def __init__(
        self,
        *,
        agent: AgentOrchestrator,
        tool_router: ToolRouter,
        history: ConversationHistory,
        rag: RAGPipeline,
    ):
        self.agent = agent
        self.tool_router = tool_router
        self.history = history
        self.rag = rag

    def handle_chat(
        self,
        *,
        user_id: str,
        text: str,
        document_ids: list[str] | None,
        provider: "LLMProvider | Callable[[], LLMProvider]",
        on_step: "Callable[[dict], None] | None" = None,
        on_token: "Callable[[str], None] | None" = None,
        turn_id: str | None = None,
        should_cancel: "Callable[[], bool] | None" = None,
        tool_hint: str | None = None,
        semantic: "EmbeddingProvider | Callable[[], EmbeddingProvider | None] | None" = None,
    ) -> dict:
        """`provider` may be a zero-argument callable that returns the
        provider. It is only called when the model is actually needed, so a
        greeting works even before any provider is configured.

        `on_step`, if given, is called with small progress events as the turn
        happens ("thinking", "tool_call", "tool_result" - see
        AgentOrchestrator.run). Purely for a streaming UI; never changes the
        return value. A greeting emits nothing - there is nothing to wait for.

        `on_token` receives the answer as the provider streams it (see AgentOrchestrator.run).
        `turn_id` (from the page) names this question-and-answer pair in the history, so a
        Stop can drop it and `should_cancel` can end it early - a cancelled turn is never saved
        and raises TurnCancelled. `tool_hint` forces one tool ("/calc", "/web", ...).
        `semantic` (or a callable returning it) enables meaning-based document search.

        The reply includes `turn` (the ids of the saved messages, for Regenerate / Edit) and
        `sources`: numbered citations with the matched text."""
        if is_greeting(text):
            return {"type": "text", "content": GREETING_REPLY}

        if not isinstance(provider, LLMProvider) and callable(provider):
            provider = provider()

        # Document search is scoped to this user (and optionally to the
        # documents they ticked), so the tool set is built per request.
        if callable(semantic) and not isinstance(semantic, EmbeddingProvider):
            semantic = semantic() if self.rag.has_documents(user_id) else None
        document_search = DocumentSearchTool(self.rag, user_id, document_ids=document_ids, semantic=semantic)
        router = ToolRouter(tools=[*self.tool_router.tools, document_search.as_tool()])

        result = self.agent.run(
            text, history=self.history.get(user_id), tool_router=router, provider=provider, on_step=on_step,
            on_token=on_token, should_cancel=should_cancel, tool_hint=tool_hint,
        )

        used_document_search = any(call["tool"] == "search_documents" for call in result["tool_calls"])
        sources = document_search.citations() if used_document_search else []
        tools = [{"tool": c["tool"], "success": c["success"]} for c in result["tool_calls"]]
        meta = {k: v for k, v in (("sources", sources), ("tools", tools)) if v}

        if should_cancel is not None and should_cancel():
            raise TurnCancelled()
        ids = self.history.append_turn(user_id, turn_id, text, result["content"], meta)
        if ids is None:  # Stop arrived while the answer was being written
            raise TurnCancelled()

        return {
            "type": "text",
            "content": result["content"],
            "tool_used": result["tool_used"],
            "tool_calls": _public_tool_calls(result["tool_calls"]),
            "sources": sources,
            "streamed": bool(result.get("streamed")),
            "turn": {"id": turn_id, "user_message_id": ids[0], "assistant_message_id": ids[1]},
        }
