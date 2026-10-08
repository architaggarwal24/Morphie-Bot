"""
Ollama implementation of LLMProvider.

Talks to Ollama's own /api/chat endpoint (not the OpenAI-compatibility
layer some Ollama versions also expose), since that's the most reliably
available surface across versions. Two real quirks vs. the OpenAI-style
providers:

  - No API key is required for a local Ollama server - `is_configured()`
    is always True; an api_key is only sent (as a Bearer token) when one
    is provided, which is how Ollama Cloud models (e.g. names ending in
    "-cloud") authenticate.
  - Ollama's tool_calls often omit an "id" entirely, and `arguments`
    comes back as a native JSON object rather than a string - both are
    normalized here so the rest of Morphie never has to know.
"""

from __future__ import annotations

import json

import requests

from .base import (
    ChatResult,
    LLMProvider,
    ProviderBadResponseError,
    ProviderCapabilities,
    ProviderModelNotFoundError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCallRequest,
)

DEFAULT_TIMEOUT = 120  # local models can be slow to load/first-token


def _wrap_tool_calls(flat_tool_calls: list[dict]) -> list[dict]:
    return [
        {"function": {"name": tc["name"], "arguments": json.loads(tc["arguments"])}}
        for tc in flat_tool_calls
    ]


def _translate_messages(messages: list[dict]) -> list[dict]:
    translated = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = {**m, "tool_calls": _wrap_tool_calls(m["tool_calls"])}
        translated.append(m)
    return translated


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, api_key: str | None, model: str, base_url: str = "http://localhost:11434"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def is_configured(self) -> bool:
        return True  # local Ollama needs no key; connection issues surface as ProviderUnavailableError

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tools=True, vision=False, streaming=True)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        payload = {"model": self.model, "messages": _translate_messages(messages), "stream": False}
        if tools:
            payload["tools"] = tools

        try:
            response = requests.post(
                f"{self.base_url}/api/chat", headers=self._headers(), json=payload, timeout=DEFAULT_TIMEOUT
            )
        except requests.Timeout as exc:
            raise ProviderTimeoutError("Ollama timed out. The model may still be loading.", provider=self.name) from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError(
                f"Could not reach Ollama at {self.base_url}. Is it running?", provider=self.name
            ) from exc

        if response.status_code == 404:
            raise ProviderModelNotFoundError(
                f"Ollama doesn't have model '{self.model}' - pull it first with `ollama pull {self.model}`.",
                provider=self.name,
            )
        if response.status_code >= 400:
            detail = self._error_detail(response)
            raise ProviderUnavailableError(
                f"Ollama returned an error{f': {detail}' if detail else ''}.", provider=self.name
            )

        try:
            data = response.json()
            message = data["message"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderBadResponseError("Ollama returned an unreadable response.", provider=self.name) from exc

        content = message.get("content")
        tool_calls: list[ToolCallRequest] = []
        flat_tool_calls: list[dict] = []

        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function", {})
            call_id = tc.get("id") or f"call_{i}"
            arguments = fn.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
            tool_calls.append(ToolCallRequest(id=call_id, name=fn.get("name", ""), arguments=arguments))
            flat_tool_calls.append({"id": call_id, "name": fn.get("name", ""), "arguments": json.dumps(arguments)})

        raw_assistant_message: dict = {"role": "assistant", "content": content or ""}
        if flat_tool_calls:
            raw_assistant_message["tool_calls"] = flat_tool_calls

        return ChatResult(content=content, tool_calls=tool_calls, raw_assistant_message=raw_assistant_message)

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            data = response.json()
            return str(data.get("error", ""))[:200]
        except ValueError:
            return ""
