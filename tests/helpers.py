"""
Test-only fakes for LLMProvider and EmbeddingProvider, so agent
logic can be tested without hitting a real Mistral API.
"""

import json

from morphie.providers.base import ChatResult, LLMProvider, ToolCallRequest
from morphie.providers.embeddings import EmbeddingProvider


class ScriptedProvider(LLMProvider):
    """A fake LLMProvider whose behavior is a list of responses, consumed
    one per call to .chat(). Each response can be a ChatResult, or a
    callable (messages, tools) -> ChatResult for conditional behavior. If
    more calls happen than scripted responses, the last one repeats."""

    name = "scripted"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # (messages_snapshot, tools) per call, for assertions

    def is_configured(self):
        return True

    def chat(self, messages, tools=None):
        self.calls.append((list(messages), tools))
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        response = self._responses[index]
        if callable(response):
            return response(messages, tools)
        return response


def text_result(content: str) -> ChatResult:
    return ChatResult(content=content, tool_calls=[], raw_assistant_message=None)


def tool_call_result(call_id: str, name: str, arguments_json: str) -> ChatResult:
    """A ChatResult representing the model requesting a single tool call."""
    return ChatResult(
        content=None,
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=json.loads(arguments_json))],
        raw_assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments_json}}
            ],
        },
    )


def multi_tool_call_result(calls) -> ChatResult:
    """calls: list of (call_id, name, arguments_dict) requested in one batch."""
    return ChatResult(
        content=None,
        tool_calls=[ToolCallRequest(id=cid, name=name, arguments=args) for cid, name, args in calls],
        raw_assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for cid, name, args in calls
            ],
        },
    )


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic 'embedding' for tests: a bag-of-words vector over a
    fixed vocabulary. Lets VectorMemoryStore's cosine-similarity plumbing
    be tested without any network call. `vocab_groups` lets a test make
    unrelated concepts (e.g. "python" and "project") land close together,
    the way a real embedding model would, without needing one."""

    name = "fake"

    def __init__(self, vocab_groups: list[list[str]] | None = None, fail: bool = False):
        self.fail = fail
        self._groups = vocab_groups or []

    def is_configured(self) -> bool:
        return True

    def embed(self, text: str) -> list[float]:
        if self.fail:
            raise RuntimeError("simulated embedding failure")
        words = set(text.lower().split())
        return [1.0 if any(w in words for w in group) else 0.0 for group in self._groups]
