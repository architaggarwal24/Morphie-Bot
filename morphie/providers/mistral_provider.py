"""
Mistral implementation of LLMProvider.

This is the only file in the project that imports the `mistralai` SDK.
Keeping the vendor SDK isolated here means the Agent, the Design Agent,
and the Flask routes never need to know which provider is selected.
"""

from __future__ import annotations

import json

import httpx
from mistralai import Mistral
from mistralai.models.mistralerror import MistralError

from .base import (
    ChatResult,
    LLMProvider,
    ProviderCapabilities,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCallRequest,
    map_http_status_to_error,
)


def _wrap_tool_calls(flat_tool_calls: list[dict]) -> list[dict]:
    """Normalized {"id","name","arguments"} -> Mistral/OpenAI wire shape."""
    return [
        {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
        for tc in flat_tool_calls
    ]


def _translate_messages(messages: list[dict]) -> list[dict]:
    """Mistral's wire format matches Morphie's normalized format almost
    exactly - the only fix-up needed is re-wrapping an assistant
    message's flat tool_calls into Mistral/OpenAI's nested shape."""
    translated = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = {**m, "tool_calls": _wrap_tool_calls(m["tool_calls"])}
        translated.append(m)
    return translated


class MistralProvider(LLMProvider):
    name = "mistral"

    def __init__(self, api_key: str | None, model: str):
        self.model = model
        self._client = Mistral(api_key=api_key) if api_key else None

    def is_configured(self) -> bool:
        return self._client is not None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tools=True, vision=False, streaming=True)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError("Mistral API key is not configured.", provider=self.name)

        kwargs = {"model": self.model, "messages": _translate_messages(messages)}
        if tools:
            kwargs["tools"] = tools

        try:
            response = self._client.chat.complete(**kwargs)
        except MistralError as exc:
            raise map_http_status_to_error(exc.status_code, "Mistral") from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Mistral timed out. Please try again.", provider=self.name) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Could not reach Mistral: {exc}", provider=self.name) from exc

        message = response.choices[0].message

        tool_calls: list[ToolCallRequest] = []
        flat_tool_calls: list[dict] = []

        for tc in getattr(message, "tool_calls", None) or []:
            raw_arguments = tc.function.arguments
            try:
                parsed_arguments = (
                    json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
                )
            except (json.JSONDecodeError, TypeError):
                parsed_arguments = {}

            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=parsed_arguments))
            flat_tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": raw_arguments})

        raw_assistant_message: dict = {"role": "assistant", "content": message.content or ""}
        if flat_tool_calls:
            raw_assistant_message["tool_calls"] = flat_tool_calls

        return ChatResult(
            content=message.content,
            tool_calls=tool_calls,
            raw_assistant_message=raw_assistant_message,
        )
