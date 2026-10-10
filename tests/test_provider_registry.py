import pytest

from morphie.providers.mistral_provider import MistralProvider
from morphie.providers.ollama import OllamaProvider
from morphie.providers.openai import OpenAIProvider
from morphie.providers.registry import ProviderRegistry


def test_lists_all_three_providers():
    registry = ProviderRegistry()
    ids = {p.id for p in registry.list_providers()}
    assert ids == {"mistral", "ollama", "openai"}


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
