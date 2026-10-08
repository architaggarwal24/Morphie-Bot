"""
OpenAI implementation of LLMProvider, plus OpenAICompatibleProvider - a
reusable base for any vendor exposing an OpenAI-style /chat/completions
endpoint. APMIX.AI (apmixai.py) is exactly that: an OpenAI-compatible
gateway (https://apmix.ai/docs), so it subclasses this rather than
duplicating the translation logic.

Implemented via plain HTTP (requests, already a dependency) rather than
the `openai` SDK, to avoid an extra heavyweight dependency for what is a
stable, simple JSON API - and so this same base class can serve any
OpenAI-compatible vendor without adding an SDK per vendor.
"""

from __future__ import annotations

import json

import requests

from .base import (
    ChatResult,
    LLMProvider,
    ProviderBadResponseError,
    ProviderCapabilities,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCallRequest,
    map_http_status_to_error,
)

DEFAULT_TIMEOUT = 60


def _wrap_tool_calls(flat_tool_calls: list[dict]) -> list[dict]:
    """Normalized {"id","name","arguments"} -> OpenAI wire shape."""
    return [
        {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
        for tc in flat_tool_calls
    ]


def _translate_messages(messages: list[dict]) -> list[dict]:
    translated = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = {**m, "tool_calls": _wrap_tool_calls(m["tool_calls"])}
        translated.append(m)
    return translated


class OpenAICompatibleProvider(LLMProvider):
    """Base for any vendor speaking the OpenAI chat-completions wire
    format. Subclasses set `name` and `base_url`; override `_error_detail`
    for a vendor with richer error payloads."""

    name = "openai-compatible"
    base_url = "https://api.openai.com/v1"

    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tools=True, vision=False, streaming=True)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _error_detail(self, response: requests.Response) -> str:
        """A short, safe detail string from a vendor error body - never
        the full body, which could echo back request content."""
        try:
            data = response.json()
            err = data.get("error")
            if isinstance(err, dict):
                return str(err.get("message", ""))[:200]
            if isinstance(err, str):
                return err[:200]
        except ValueError:
            pass
        return ""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name} API key is not configured.", provider=self.name)

        payload = {"model": self.model, "messages": _translate_messages(messages)}
        if tools:
            payload["tools"] = tools

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload, timeout=DEFAULT_TIMEOUT
            )
        except requests.Timeout as exc:
            raise ProviderTimeoutError(f"{self.name} timed out. Please try again.", provider=self.name) from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"Could not reach {self.name}: {exc}", provider=self.name) from exc

        if response.status_code >= 400:
            raise map_http_status_to_error(response.status_code, self.name, detail=self._error_detail(response))

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderBadResponseError(f"{self.name} returned an unreadable response.", provider=self.name) from exc

        content = message.get("content")
        tool_calls: list[ToolCallRequest] = []
        flat_tool_calls: list[dict] = []

        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_arguments = fn.get("arguments") or "{}"
            try:
                parsed_arguments = (
                    json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
                )
            except (json.JSONDecodeError, TypeError):
                parsed_arguments = {}
            tool_calls.append(
                ToolCallRequest(id=tc.get("id", ""), name=fn.get("name", ""), arguments=parsed_arguments)
            )
            flat_tool_calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": raw_arguments})

        raw_assistant_message: dict = {"role": "assistant", "content": content or ""}
        if flat_tool_calls:
            raw_assistant_message["tool_calls"] = flat_tool_calls

        return ChatResult(content=content, tool_calls=tool_calls, raw_assistant_message=raw_assistant_message)


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    base_url = "https://api.openai.com/v1"
