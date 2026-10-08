"""
LLM provider interface.

Every vendor (Mistral, Ollama, OpenAI, Gemini, Anthropic, APMIX.AI...)
implements this same interface. Nothing outside this package should
import a vendor SDK or build a vendor-specific request/response shape -
the Agent, the Design Agent, and the Flask routes only ever talk to an
LLMProvider, and only ever see the normalized message/result shapes
defined here.

Normalized message format (what the Agent builds and what every
provider must accept as `messages` and produce as `raw_assistant_message`):

    {"role": "system", "content": "..."}
    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [
        {"id": "...", "name": "...", "arguments": "...json string..."}
    ]}  # "tool_calls" key is omitted entirely when there were none
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}

This happens to already match OpenAI/Mistral's own wire format closely,
which keeps those providers' translation layer trivial - but it is
Morphie's own normalized format, not any one vendor's. Providers whose
wire format looks nothing like this (Anthropic, Gemini) do the full
translation both ways on every call; see anthropic.py and gemini.py for
what that looks like in practice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    """A single tool call the model asked for, normalized across vendors."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    """Normalized response from any LLM provider."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    # The normalized representation of the assistant's turn (see module
    # docstring), so it can be appended back onto the message history for
    # the next round-trip (needed for multi-step tool calling).
    raw_assistant_message: dict | None = None


@dataclass
class ProviderCapabilities:
    """What a provider (and, in principle, a specific model) can do.
    Exposed to the frontend so the UI can explain a limitation instead of
    just failing, and used by the Agent to decide whether to offer tools
    at all."""

    tools: bool
    vision: bool
    streaming: bool

    def to_dict(self) -> dict:
        return {"tools": self.tools, "vision": self.vision, "streaming": self.streaming}


# ---- Friendly, non-leaking provider errors ----
#
# Every provider translates whatever it gets back (HTTP status codes,
# vendor-specific error bodies, connection failures) into one of these.
# Callers (AgentOrchestrator, Flask routes) catch ProviderError once and
# show `.friendly_message` - never the raw exception text, which could
# contain request/response bodies that echo back part of the API key or
# other request details.

class ProviderError(Exception):
    """Base class for all provider-facing errors. `friendly_message` is
    always safe to show directly to the user; never include headers,
    request bodies, or the API key in it."""

    def __init__(self, friendly_message: str, *, provider: str = "", retryable: bool = False):
        super().__init__(friendly_message)
        self.friendly_message = friendly_message
        self.provider = provider
        self.retryable = retryable


class ProviderNotConfiguredError(ProviderError):
    """No API key / configuration set for this provider yet."""


class ProviderAuthError(ProviderError):
    """The API key was rejected (invalid, revoked, wrong provider)."""


class ProviderRateLimitError(ProviderError):
    """Too many requests - safe to retry later."""


class ProviderModelNotFoundError(ProviderError):
    """The requested model doesn't exist or isn't available to this key."""


class ProviderUnavailableError(ProviderError):
    """The provider is unreachable or returned a server-side error."""


class ProviderTimeoutError(ProviderError):
    """The request took too long."""


class ProviderBadResponseError(ProviderError):
    """The provider responded, but not in a shape we could parse."""


def map_http_status_to_error(status_code: int, provider_name: str, detail: str = "") -> ProviderError:
    """Shared status-code -> friendly-error mapping used by every
    HTTP-based provider, so the same status code always means the same
    thing to the rest of the app regardless of which vendor sent it.
    `detail` should already be scrubbed of anything sensitive (never pass
    a raw response body that might echo the request, including the key)."""
    suffix = f" ({detail})" if detail else ""
    if status_code == 401 or status_code == 403:
        return ProviderAuthError(
            f"{provider_name} rejected the API key. Check that it's correct and active.{suffix}",
            provider=provider_name,
        )
    if status_code == 404:
        return ProviderModelNotFoundError(
            f"{provider_name} could not find that model. Check the model name and try again.{suffix}",
            provider=provider_name,
        )
    if status_code == 429:
        return ProviderRateLimitError(
            f"{provider_name} is rate-limiting this key right now. Please wait and try again.{suffix}",
            provider=provider_name,
            retryable=True,
        )
    if status_code in (500, 502, 503, 504, 529):
        return ProviderUnavailableError(
            f"{provider_name} is temporarily unavailable. Please try again shortly.{suffix}",
            provider=provider_name,
            retryable=True,
        )
    return ProviderBadResponseError(
        f"{provider_name} returned an unexpected error (HTTP {status_code}).{suffix}",
        provider=provider_name,
    )


class LLMProvider(ABC):
    """Common interface every LLM backend must implement."""

    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider has the credentials it needs to run."""

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        """Send a chat completion request and return a normalized result.

        Raises a ProviderError subclass on any failure - callers never
        need to know which vendor is behind this instance to handle it.
        """

    def stream(self, messages: list[dict], tools: list[dict] | None = None):
        """Optional: yield text deltas as they arrive. Not every provider
        implements this yet (see capabilities().streaming); the default
        raises so a caller can detect and fall back to chat()."""
        raise NotImplementedError(f"{self.name} does not support streaming.")

    def capabilities(self) -> ProviderCapabilities:
        """Default: text + tool calling, no vision, no streaming.
        Providers override this to reflect what they (and, coarsely,
        their currently selected model) actually support."""
        return ProviderCapabilities(tools=True, vision=False, streaming=False)
