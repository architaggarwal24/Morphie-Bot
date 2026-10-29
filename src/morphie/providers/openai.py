"""
OpenAI implementation of LLMProvider, plus OpenAICompatibleProvider - a
reusable base for any vendor exposing an OpenAI-style /chat/completions
endpoint. APMIX.AI (apmixai.py) is exactly that: an OpenAI-compatible
gateway (https://apmix.ai/docs), so it subclasses this rather than
duplicating the translation logic.

Implemented via plain HTTP (morphie.net: `requests`, or fetch() on Workers) rather than
the `openai` SDK, to avoid an extra heavyweight dependency for what is a
stable, simple JSON API - and so this same base class can serve any
OpenAI-compatible vendor without adding an SDK per vendor.
"""

from __future__ import annotations

import json
from typing import Callable

from .. import net as requests  # `requests` locally; fetch() on Cloudflare Workers (see morphie/net.py)
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
    follow_redirects = True

    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tools=True, vision=False, streaming=True)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _redact(self, text: str) -> str:
        """Remove this provider's API key from text that may be shown to the user or logged. With bring-your-own-key
        the key is the visitor's secret, and vendor error bodies and network errors can echo it back."""
        key = self.api_key
        return text.replace(key, "[hidden]") if key and text else text

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
        payload = {"model": self.model, "messages": _translate_messages(messages)}
        if tools:
            payload["tools"] = tools
        response = self._send(payload)

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderBadResponseError(f"{self.name} returned an unreadable response.", provider=self.name) from exc

        return _to_result(message.get("content"), message.get("tool_calls") or [])

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_delta: "Callable[[str], None] | None" = None,
        should_cancel: "Callable[[], bool] | None" = None,
    ) -> ChatResult:
        """chat() with `"stream": true`: text deltas go to `on_delta` as the server-sent events arrive; tool-call
        fragments are stitched back together by their index."""
        response = self._send({"model": self.model, "messages": _translate_messages(messages), "stream": True, **({"tools": tools} if tools else {})}, stream=True)
        if "json" in requests.content_type(response):
            # Some compatible servers ignore "stream": true and answer in one piece.
            return self._parse_whole(response, on_delta)
        text: list[str] = []
        calls: dict[int, dict] = {}
        try:
            for line in requests.decoded_lines(response):
                if should_cancel is not None and should_cancel():
                    break
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    err = chunk["error"]
                    detail = err.get("message", "") if isinstance(err, dict) else str(err)
                    raise ProviderUnavailableError(
                        f"{self.name} stopped with an error: {self._redact(str(detail))[:200]}", provider=self.name
                    )
                choices = chunk.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    text.append(piece)
                    if on_delta is not None:
                        on_delta(piece)
                for tc in delta.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    index = tc.get("index")
                    if index is None or (tc.get("id") and index in calls and calls[index]["id"] and calls[index]["id"] != tc["id"]):
                        index = len(calls)  # no index, or a new call reusing one: a new slot
                    slot = calls.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    args = fn.get("arguments")
                    if isinstance(args, dict):
                        slot["function"]["arguments"] = json.dumps(args)
                    elif isinstance(args, str):
                        slot["function"]["arguments"] += args
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"The connection to {self.name} dropped: {self._redact(str(exc))}", provider=self.name) from exc
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        return _to_result("".join(text) or None, [calls[k] for k in sorted(calls)])

    def _parse_whole(self, response, on_delta) -> ChatResult:
        try:
            message = response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderBadResponseError(f"{self.name} returned an unreadable response.", provider=self.name) from exc
        content = message.get("content")
        if content and on_delta is not None:
            on_delta(content)
        return _to_result(content, message.get("tool_calls") or [])

    def _send(self, payload: dict, stream: bool = False):
        """POST to /chat/completions; translate transport errors and error statuses."""
        if not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name} API key is not configured.", provider=self.name)
        try:
            kwargs: dict = {"stream": True} if stream else {}
            if not self.follow_redirects:
                kwargs["allow_redirects"] = False
            response = requests.post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload, timeout=DEFAULT_TIMEOUT, **kwargs
            )
        except requests.Timeout as exc:
            raise ProviderTimeoutError(f"{self.name} timed out. Please try again.", provider=self.name) from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"Could not reach {self.name}: {self._redact(str(exc))}", provider=self.name) from exc
        if response.status_code >= 400:
            raise map_http_status_to_error(response.status_code, self.name, detail=self._redact(self._error_detail(response)))
        return response


def _to_result(content: str | None, raw_tool_calls: list[dict]) -> ChatResult:
    """OpenAI-shaped content + tool_calls -> the normalized ChatResult."""
    tool_calls: list[ToolCallRequest] = []
    flat_tool_calls: list[dict] = []
    for tc in raw_tool_calls:
        fn = tc.get("function", {})
        raw_arguments = fn.get("arguments") or "{}"
        try:
            parsed_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
        except (json.JSONDecodeError, TypeError):
            parsed_arguments = {}
        if not isinstance(raw_arguments, str):
            raw_arguments = json.dumps(raw_arguments)
        tool_calls.append(ToolCallRequest(id=tc.get("id", ""), name=fn.get("name", ""), arguments=parsed_arguments))
        flat_tool_calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": raw_arguments})

    raw_assistant_message: dict = {"role": "assistant", "content": content or ""}
    if flat_tool_calls:
        raw_assistant_message["tool_calls"] = flat_tool_calls
    return ChatResult(content=content, tool_calls=tool_calls, raw_assistant_message=raw_assistant_message)


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    base_url = "https://api.openai.com/v1"
