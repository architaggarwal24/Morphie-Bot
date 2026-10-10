import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from morphie.providers.base import (
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from morphie.providers.openai import OpenAIProvider


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def test_openai_not_configured_without_api_key():
    provider = OpenAIProvider(api_key=None, model="gpt-4o-mini")
    assert provider.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.openai.requests.post")
def test_openai_simple_chat(mock_post):
    mock_post.return_value = _mock_response(200, {
        "choices": [{"message": {"role": "assistant", "content": "Hello there!"}}]
    })
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    result = provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "Hello there!"
    assert result.tool_calls == []

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["model"] == "gpt-4o-mini"
    assert sent_payload["messages"][0]["content"] == "hi"

    sent_headers = mock_post.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == "Bearer sk-test"


@patch("morphie.providers.openai.requests.post")
def test_openai_tool_call_round_trip(mock_post):
    mock_post.return_value = _mock_response(200, {
        "choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}}],
        }}]
    })
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    result = provider.chat([{"role": "user", "content": "what is 2+2"}], tools=[{"type": "function", "function": {"name": "calculator"}}])

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "calculator"
    assert result.tool_calls[0].arguments == {"expression": "2+2"}
    # raw_assistant_message is normalized (flat), not the wrapped wire shape
    assert result.raw_assistant_message["tool_calls"][0] == {
        "id": "call_1", "name": "calculator", "arguments": '{"expression": "2+2"}'
    }


@patch("morphie.providers.openai.requests.post")
def test_openai_re_wraps_normalized_tool_calls_when_sending_history(mock_post):
    mock_post.return_value = _mock_response(200, {"choices": [{"message": {"content": "done"}}]})
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")

    history = [
        {"role": "user", "content": "what is 2+2"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "calculator", "arguments": '{"expression": "2+2"}'}]},
        {"role": "tool", "tool_call_id": "call_1", "name": "calculator", "content": "4"},
    ]
    provider.chat(history)

    sent_messages = mock_post.call_args.kwargs["json"]["messages"]
    assistant_msg = sent_messages[1]
    assert assistant_msg["tool_calls"][0]["type"] == "function"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calculator"
    assert sent_messages[2] == {"role": "tool", "tool_call_id": "call_1", "name": "calculator", "content": "4"}


@patch("morphie.providers.openai.requests.post")
def test_openai_invalid_key_maps_to_auth_error(mock_post):
    mock_post.return_value = _mock_response(401, {"error": {"message": "Incorrect API key provided"}})
    provider = OpenAIProvider(api_key="sk-bad", model="gpt-4o-mini")
    with pytest.raises(ProviderAuthError):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.openai.requests.post")
def test_openai_rate_limit_maps_to_rate_limit_error(mock_post):
    mock_post.return_value = _mock_response(429, {"error": {"message": "Rate limit exceeded"}})
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    with pytest.raises(ProviderRateLimitError) as excinfo:
        provider.chat([{"role": "user", "content": "hi"}])
    assert excinfo.value.retryable is True


@patch("morphie.providers.openai.requests.post")
def test_openai_model_not_found(mock_post):
    mock_post.return_value = _mock_response(404, {"error": {"message": "model not found"}})
    provider = OpenAIProvider(api_key="sk-test", model="gpt-nonexistent")
    with pytest.raises(ProviderModelNotFoundError):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.openai.requests.post")
def test_openai_server_error_maps_to_unavailable(mock_post):
    mock_post.return_value = _mock_response(503, {"error": {"message": "server overloaded"}})
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    with pytest.raises(ProviderUnavailableError):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.openai.requests.post", side_effect=requests.Timeout())
def test_openai_timeout(mock_post):
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    with pytest.raises(ProviderTimeoutError):
        provider.chat([{"role": "user", "content": "hi"}])


@patch("morphie.providers.openai.requests.post", side_effect=requests.ConnectionError())
def test_openai_connection_error_maps_to_unavailable(mock_post):
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    with pytest.raises(ProviderUnavailableError):
        provider.chat([{"role": "user", "content": "hi"}])


def test_error_never_includes_the_api_key_value():
    """Morphie's own error-construction code must never interpolate the
    API key into a message. (What a vendor's own error body echoes back
    is outside Morphie's control - this tests what Morphie itself does.)"""
    secret_key = "sk-thisisasecretkeyvalue12345"
    with patch("morphie.providers.openai.requests.post") as mock_post:
        mock_post.return_value = _mock_response(401, {"error": {"message": "Incorrect API key provided"}})
        provider = OpenAIProvider(api_key=secret_key, model="gpt-4o-mini")
        with pytest.raises(ProviderAuthError) as excinfo:
            provider.chat([{"role": "user", "content": "hi"}])
        assert secret_key not in str(excinfo.value)
        assert secret_key not in excinfo.value.friendly_message


def test_openai_capabilities():
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    caps = provider.capabilities().to_dict()
    assert caps == {"tools": True, "vision": False, "streaming": True}
