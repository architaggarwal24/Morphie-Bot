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

from .agent.orchestrator import AgentOrchestrator
from .agent.tool_router import ToolRouter
from .agent.tools.document_search import DocumentSearchTool, build_sources
from .history import ConversationHistory
from .providers.base import LLMProvider
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
    ) -> dict:
        """`provider` may be a zero-argument callable that returns the
        provider. It is only called when the model is actually needed, so a
        greeting works even before any provider is configured.

        `on_step`, if given, is called with small progress events as the turn
        happens ("thinking", "tool_call", "tool_result" - see
        AgentOrchestrator.run). Purely for a streaming UI; never changes the
        return value. A greeting emits nothing - there is nothing to wait for."""
        if is_greeting(text):
            return {"type": "text", "content": GREETING_REPLY}

        if not isinstance(provider, LLMProvider) and callable(provider):
            provider = provider()

        # Document search is scoped to this user (and optionally to the
        # documents they ticked), so the tool set is built per request.
        document_search = DocumentSearchTool(self.rag, user_id, document_ids=document_ids)
        router = ToolRouter(tools=[*self.tool_router.tools, document_search.as_tool()])

        result = self.agent.run(
            text, history=self.history.get(user_id), tool_router=router, provider=provider, on_step=on_step,
        )

        self.history.append(user_id, "user", text)
        self.history.append(user_id, "assistant", result["content"])

        used_document_search = any(call["tool"] == "search_documents" for call in result["tool_calls"])
        return {
            "type": "text",
            "content": result["content"],
            "tool_used": result["tool_used"],
            "tool_calls": _public_tool_calls(result["tool_calls"]),
            "sources": build_sources(document_search.last_retrieved) if used_document_search else [],
        }
