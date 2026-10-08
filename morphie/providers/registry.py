"""
Provider registry.

The only place that knows which provider classes exist and how to build
one. The rest of the application (Agent, Flask routes) never imports a
provider class directly - it calls registry.get(provider_id, ...) and
gets back an LLMProvider, so adding a new provider later means writing
one class and adding one entry here (plus its name in
config.SUPPORTED_PROVIDERS).
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import LLMProvider
from .mistral_provider import MistralProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider


@dataclass
class ProviderInfo:
    id: str
    display_name: str
    default_model: str
    example_models: list[str]
    requires_api_key: bool
    factory: type


_PROVIDERS: dict[str, ProviderInfo] = {
    "mistral": ProviderInfo(
        id="mistral", display_name="Mistral", default_model="mistral-large-latest",
        example_models=["mistral-large-latest", "mistral-small-latest"],
        requires_api_key=True, factory=MistralProvider,
    ),
    "ollama": ProviderInfo(
        id="ollama", display_name="Ollama", default_model="llama3.1",
        example_models=["llama3.1", "qwen2.5", "gemma4:31b-cloud"],
        requires_api_key=False, factory=OllamaProvider,
    ),
    "openai": ProviderInfo(
        id="openai", display_name="OpenAI", default_model="gpt-4o-mini",
        example_models=["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
        requires_api_key=True, factory=OpenAIProvider,
    ),
}


class ProviderRegistry:
    def list_providers(self) -> list[ProviderInfo]:
        return list(_PROVIDERS.values())

    def get_info(self, provider_id: str) -> ProviderInfo | None:
        return _PROVIDERS.get(provider_id)

    def is_known(self, provider_id: str) -> bool:
        return provider_id in _PROVIDERS

    def get(self, provider_id: str, api_key: str | None = None, model: str | None = None, **kwargs) -> LLMProvider:
        info = _PROVIDERS.get(provider_id)
        if info is None:
            raise ValueError(
                f"Unknown provider '{provider_id}'. Available: {', '.join(sorted(_PROVIDERS))}."
            )
        chosen_model = model or info.default_model
        return info.factory(api_key=api_key, model=chosen_model, **kwargs)


registry = ProviderRegistry()
