from unittest.mock import MagicMock, patch

import pytest
import requests

from morphie.providers.base import ProviderModelNotFoundError, ProviderTimeoutError, ProviderUnavailableError
from morphie.providers.ollama import OllamaProvider


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def test_ollama_is_configured_without_an_api_key():
    # Local Ollama needs no key at all.
    provider = OllamaProvider(api_key=None, model="llama3.1")
    assert provider.is_configured() is True


@patch("morphie.providers.ollama.requests.post")
def test_ollama_simple_chat_no_auth_header_without_key(mock_post):
    mock_post.return_value = _mock_response(200, {"message": {"role": "assistant", "content": "Hello!"}, "done": True})
    provider = OllamaProvider(api_key=None, model="llama3.1")
    result = provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "Hello!"
    sent_headers = mock_post.call_args.kwargs["headers"]
    assert "Authorization" not in sent_headers

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["stream"] is False
    assert sent_payload["model"] == "llama3.1"


@patch("morphie.providers.ollama.requests.post")
def test_ollama_sends_bearer_token_when_api_key_present(mock_post):
    mock_post.return_value = _mock_response(200, {"message": {"content": "Hello!"}})
    provider = OllamaProvider(api_key="cloud-key", model="gemma4:31b-cloud")
    provider.chat([{"role": "user", "content": "hi"}])

    sent_headers = mock_post.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == "Bearer cloud-key"


@patch("morphie.providers.ollama.requests.post")
def test_ollama_synthesizes_missing_tool_call_id(mock_post):
    mock_post.return_value = _mock_response(200, {
        "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "calculator", "arguments": {"expression": "2+2"}}}  # no "id" at all
        ]}
    })
    provider = OllamaProvider(api_key=None, model="llama3.1")
    result = provider.chat([{"role": "user", "content": "what is 2+2"}], tools=[{"type": "function", "function": {"name": "calculator"}}])

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id  # synthesized, non-empty
    assert result.tool_calls[0].name == "calculator"
    assert result.tool_calls[0].arguments == {"expression": "2+2"}


@patch("morphie.providers.ollama.requests.post")
def test_ollama_arguments_dict_is_normalized_to_json_string_in_raw_message(mock_post):
    mock_post.return_value = _mock_response(200, {
        "message": {"content": "", "tool_calls": [
            {"id": "abc", "function": {"name": "calculator", "arguments": {"expression": "2+2"}}}
        ]}
    })
    provider = OllamaProvider(api_key=None, model="llama3.1")
    result = provider.chat([{"role": "user", "content": "2+2"}])

    raw_args = result.raw_assistant_message["tool_calls"][0]["arguments"]
    assert isinstance(raw_args, str)
    import json
    assert json.loads(raw_args) == {"expression": "2+2"}


@patch("morphie.providers.ollama.requests.post")
def test_ollama_model_not_pulled_gives_friendly_error(mock_post):
    mock_post.return_value = _mock_response(404, {"error": "model 'made-up-model' not found"})
    provider = OllamaProvider(api_key=None, model="made-up-model")
    with pytest.raises(ProviderModelNotFoundError, match="pull"):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.ollama.requests.post", side_effect=requests.ConnectionError())
def test_ollama_connection_refused_gives_friendly_unavailable_error(mock_post):
    provider = OllamaProvider(api_key=None, model="llama3.1")
    with pytest.raises(ProviderUnavailableError, match="running"):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.ollama.requests.post", side_effect=requests.Timeout())
def test_ollama_timeout(mock_post):
    provider = OllamaProvider(api_key=None, model="llama3.1")
    with pytest.raises(ProviderTimeoutError):
        provider.chat([{"role": "user", "content": "hi"}])


def test_ollama_uses_configurable_base_url():
    provider = OllamaProvider(api_key=None, model="llama3.1", base_url="http://my-server:11434/")
    assert provider.base_url == "http://my-server:11434"  # trailing slash stripped


def test_ollama_capabilities():
    provider = OllamaProvider(api_key=None, model="llama3.1")
    caps = provider.capabilities().to_dict()
    assert caps["tools"] is True
