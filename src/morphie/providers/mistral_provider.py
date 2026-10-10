"""
Mistral implementation of LLMProvider.

Mistral's La Plateforme exposes an OpenAI-compatible /chat/completions endpoint (same request and response
shapes, same tool-calling format, same error statuses), so this reuses OpenAICompatibleProvider over plain HTTP
instead of the `mistralai` SDK. That keeps the dependency list small and, importantly, works on Cloudflare
Workers, where the SDK's synchronous httpx client cannot run.
"""

from __future__ import annotations

from .openai import OpenAICompatibleProvider


class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    base_url = "https://api.mistral.ai/v1"

    def _error_detail(self, response) -> str:
        """Mistral error bodies are `{"message": "..."}` (sometimes `{"detail": ...}`) rather than OpenAI's
        `{"error": {...}}`. Return a short, safe excerpt only, never the whole body."""
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, dict):
            for key in ("message", "detail"):
                value = data.get(key)
                if isinstance(value, str):
                    return value[:200]
        return super()._error_detail(response)
