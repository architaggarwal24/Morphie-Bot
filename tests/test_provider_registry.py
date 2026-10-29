import pytest

from morphie.providers.mistral_provider import MistralProvider
from morphie.providers.ollama import OllamaProvider
from morphie.providers.openai import OpenAIProvider
from morphie.providers.registry import ProviderRegistry


def test_lists_the_native_compatible_and_custom_providers():
    registry = ProviderRegistry()
    by_group = {}
    for p in registry.list_providers():
        by_group.setdefault(p.group, set()).add(p.id)
    assert by_group == {
        "native": {"mistral", "ollama", "openai"},
        "compatible": {"groq", "openrouter", "together", "deepseek"},
        "custom": {"custom"},
    }


def test_compatible_presets_call_their_own_fixed_endpoint():
    registry = ProviderRegistry()
    assert registry.get("groq", api_key="k" * 10).base_url == "https://api.groq.com/openai/v1"
    assert registry.get("openrouter", api_key="k" * 10).base_url == "https://openrouter.ai/api/v1"
    custom = registry.get("custom", api_key=None, model="m", base_url="http://localhost:1234/v1/")
    assert custom.base_url == "http://localhost:1234/v1" and custom.is_configured() and "Authorization" not in custom._headers()


def test_embedders_exist_only_where_the_provider_has_embeddings_and_a_key():
    registry = ProviderRegistry()
    assert registry.get_embedder("openai", api_key="sk-" + "x" * 10).model_id == "openai:text-embedding-3-small"
    assert registry.get_embedder("mistral", api_key="m" * 10).model_id == "mistral:mistral-embed"
    assert registry.get_embedder("ollama").model_id == "ollama:nomic-embed-text"
    assert registry.get_embedder("openai", api_key=None) is None
    assert registry.get_embedder("groq", api_key="g" * 10) is None


def test_get_returns_the_right_provider_class():
    registry = ProviderRegistry()
    assert isinstance(registry.get("mistral", api_key="k", model="m"), MistralProvider)
    assert isinstance(registry.get("ollama", api_key=None, model="llama3.1"), OllamaProvider)
    assert isinstance(registry.get("openai", api_key="k", model="gpt-4o"), OpenAIProvider)


def test_get_uses_default_model_when_none_given():
    registry = ProviderRegistry()
    provider = registry.get("openai", api_key="k", model=None)
    assert provider.model == registry.get_info("openai").default_model


def test_get_unknown_provider_raises():
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="Unknown provider"):
        registry.get("not-a-real-provider")


def test_get_info_returns_none_for_unknown_provider():
    registry = ProviderRegistry()
    assert registry.get_info("not-a-real-provider") is None


def test_ollama_does_not_require_an_api_key():
    registry = ProviderRegistry()
    info = registry.get_info("ollama")
    assert info.requires_api_key is False


def test_other_providers_require_an_api_key():
    registry = ProviderRegistry()
    for provider_id in ("mistral", "openai"):
        assert registry.get_info(provider_id).requires_api_key is True


def test_is_known():
    registry = ProviderRegistry()
    assert registry.is_known("openai") is True
    assert registry.is_known("not-a-real-provider") is False


def test_ollama_accepts_base_url_kwarg_passthrough():
    registry = ProviderRegistry()
    provider = registry.get("ollama", model="llama3.1", base_url="http://custom:11434")
    assert provider.base_url == "http://custom:11434"
