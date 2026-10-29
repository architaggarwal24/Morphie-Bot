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

from dataclasses import dataclass, field

from .base import LLMProvider
from .embeddings import EmbeddingProvider
from .embeddings_remote import OllamaEmbeddings, OpenAICompatibleEmbeddings
from .mistral_provider import MistralProvider
from .ollama import OllamaProvider
from .openai import OpenAICompatibleProvider, OpenAIProvider


class CustomCompatibleProvider(OpenAICompatibleProvider):
    """Any OpenAI-compatible server at a URL the person types (LM Studio, vLLM, llama.cpp, a gateway...).
    Only offered when the server owner allows it (ALLOW_CUSTOM_LLM_URL), because a visitor-chosen URL lets
    visitors make this server send requests to arbitrary addresses. The key is optional (local servers)."""

    name = "custom"
    follow_redirects = False  # a redirect could point anywhere; the typed URL is the only place it may call

    def __init__(self, api_key: str | None, model: str, base_url: str = ""):
        super().__init__(api_key, model)
        self.base_url = (base_url or "").rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _error_detail(self, response) -> str:
        return ""  # never reflect another server's response body back to the visitor


def _compatible(provider_id: str, display_name: str, base_url: str) -> type:
    """An OpenAICompatibleProvider subclass bound to one vendor's fixed endpoint (no visitor-chosen URL)."""
    return type(f"{display_name.replace(' ', '')}Provider", (OpenAICompatibleProvider,), {"name": display_name, "base_url": base_url})


@dataclass
class ProviderInfo:
    id: str
    display_name: str
    default_model: str
    example_models: list[str]
    requires_api_key: bool
    factory: type
    # "native" (its own adapter), "compatible" (a fixed OpenAI-compatible endpoint) or "custom" (a typed URL)
    group: str = "native"
    # Meaning-based document search with this provider's embeddings (None = keyword search only)
    embedding_model: str | None = None
    embedding_min_score: float = 0.3
    embedding_dimensions: int | None = None
    base_url: str | None = None
    tags: list[str] = field(default_factory=list)


_PROVIDERS: dict[str, ProviderInfo] = {
    "mistral": ProviderInfo(
        id="mistral", display_name="Mistral", default_model="mistral-large-latest",
        example_models=["mistral-large-latest", "mistral-small-latest"],
        requires_api_key=True, factory=MistralProvider,
        embedding_model="mistral-embed", embedding_min_score=0.6, base_url="https://api.mistral.ai/v1",
    ),
    "ollama": ProviderInfo(
        id="ollama", display_name="Ollama", default_model="llama3.1",
        example_models=["llama3.1", "qwen2.5", "gemma4:31b-cloud"],
        requires_api_key=False, factory=OllamaProvider,
        embedding_model="nomic-embed-text", embedding_min_score=0.45,
    ),
    "openai": ProviderInfo(
        id="openai", display_name="OpenAI", default_model="gpt-4o-mini",
        example_models=["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
        requires_api_key=True, factory=OpenAIProvider,
        embedding_model="text-embedding-3-small", embedding_min_score=0.25, embedding_dimensions=512,
        base_url="https://api.openai.com/v1",
    ),
    # OpenAI-compatible vendors at fixed, well-known endpoints. Model names change often: these are only
    # suggestions, any model id the vendor offers can be typed in Settings.
    "groq": ProviderInfo(
        id="groq", display_name="Groq", default_model="llama-3.3-70b-versatile",
        example_models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        requires_api_key=True, factory=_compatible("groq", "Groq", "https://api.groq.com/openai/v1"), group="compatible",
    ),
    "openrouter": ProviderInfo(
        id="openrouter", display_name="OpenRouter", default_model="openai/gpt-4o-mini",
        example_models=["openai/gpt-4o-mini", "anthropic/claude-3.5-haiku", "meta-llama/llama-3.3-70b-instruct"],
        requires_api_key=True, factory=_compatible("openrouter", "OpenRouter", "https://openrouter.ai/api/v1"), group="compatible",
    ),
    "together": ProviderInfo(
        id="together", display_name="Together AI", default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        example_models=["meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"],
        requires_api_key=True, factory=_compatible("together", "Together AI", "https://api.together.xyz/v1"), group="compatible",
    ),
    "deepseek": ProviderInfo(
        id="deepseek", display_name="DeepSeek", default_model="deepseek-chat",
        example_models=["deepseek-chat", "deepseek-reasoner"],
        requires_api_key=True, factory=_compatible("deepseek", "DeepSeek", "https://api.deepseek.com/v1"), group="compatible",
    ),
    "custom": ProviderInfo(
        id="custom", display_name="Custom URL", default_model="local-model",
        example_models=[], requires_api_key=False, factory=CustomCompatibleProvider, group="custom",
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

    def get_embedder(self, provider_id: str, api_key: str | None = None, base_url: str | None = None) -> EmbeddingProvider | None:
        """Meaning-based embeddings for document search from this provider, or None when it has none (or needs a
        key that isn't there). `base_url` is only used for Ollama (the server's own OLLAMA_BASE_URL)."""
        info = _PROVIDERS.get(provider_id)
        if info is None or not info.embedding_model:
            return None
        if info.id == "ollama":
            return OllamaEmbeddings(base_url or "http://localhost:11434", info.embedding_model, info.embedding_min_score, api_key)
        if not api_key or not info.base_url:
            return None
        return OpenAICompatibleEmbeddings(
            info.id, info.base_url, api_key, info.embedding_model, info.embedding_min_score, info.embedding_dimensions,
        )


registry = ProviderRegistry()
