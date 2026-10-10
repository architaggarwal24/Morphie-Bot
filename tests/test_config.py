import logging
import os
import stat
import sys

import pytest

import config as config_mod
from config import SUPPORTED_PROVIDERS, ConfigError, _env_bool, _env_float, _env_int, _env_list, _env_provider, resolve_secret_key

# A well-known placeholder secret that must never be accepted as a real one.
INSECURE_DEFAULT_SECRET = "dev-only-change-me"


# ---- typed environment parsing ----

def test_env_int_uses_the_default_when_unset_or_blank(monkeypatch):
    monkeypatch.delenv("X_TEST", raising=False)
    assert _env_int("X_TEST", 7) == 7
    monkeypatch.setenv("X_TEST", "   ")
    assert _env_int("X_TEST", 7) == 7


def test_env_int_parses_and_enforces_a_minimum(monkeypatch):
    monkeypatch.setenv("X_TEST", " 42 ")
    assert _env_int("X_TEST", 7) == 42
    monkeypatch.setenv("X_TEST", "0")
    with pytest.raises(ConfigError) as exc:
        _env_int("X_TEST", 7, minimum=1)
    assert "X_TEST" in str(exc.value) and "at least 1" in str(exc.value)


@pytest.mark.parametrize("bad", ["abc", "1.5", "10MB", "--3"])
def test_env_int_rejects_garbage_with_a_message_naming_the_variable(monkeypatch, bad):
    monkeypatch.setenv("MAX_TOOL_CALLS", bad)
    with pytest.raises(ConfigError) as exc:
        _env_int("MAX_TOOL_CALLS", 5)
    message = str(exc.value)
    assert "MAX_TOOL_CALLS" in message and repr(bad) in message and ".env" in message


def test_env_float_and_bool_and_list(monkeypatch):
    monkeypatch.setenv("X_TEST", "0.25")
    assert _env_float("X_TEST", 1.0) == 0.25
    monkeypatch.setenv("X_TEST", "nope")
    with pytest.raises(ConfigError):
        _env_float("X_TEST", 1.0)

    for truthy in ("1", "true", "YES", "On"):
        monkeypatch.setenv("X_TEST", truthy)
        assert _env_bool("X_TEST", False) is True
    for falsy in ("0", "false", "No", "off"):
        monkeypatch.setenv("X_TEST", falsy)
        assert _env_bool("X_TEST", True) is False
    monkeypatch.setenv("X_TEST", "maybe")
    with pytest.raises(ConfigError):
        _env_bool("X_TEST", True)

    monkeypatch.setenv("X_TEST", " https://a.example , ,https://b.example ")
    assert _env_list("X_TEST") == ["https://a.example", "https://b.example"]
    monkeypatch.delenv("X_TEST")
    assert _env_list("X_TEST") == []


# ---- the session-signing secret ----

def test_a_strong_configured_secret_is_used_as_is(tmp_path):
    assert resolve_secret_key("x" * 40, str(tmp_path / "secret")) == "x" * 40
    assert not (tmp_path / "secret").exists()


def test_without_a_secret_one_is_generated_persisted_and_reused(tmp_path, caplog):
    path = tmp_path / "data" / ".flask_secret"
    with caplog.at_level(logging.WARNING):
        first = resolve_secret_key(None, str(path))
    assert len(first) >= 32 and first != INSECURE_DEFAULT_SECRET
    assert path.read_text().strip() == first
    assert "FLASK_SECRET_KEY" in caplog.text
    assert resolve_secret_key("", str(path)) == first             # stable across restarts (sessions survive)
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600        # owner-only


def test_the_old_public_default_is_never_accepted_as_a_secret(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        secret = resolve_secret_key(INSECURE_DEFAULT_SECRET, str(tmp_path / "s"))
    assert secret != INSECURE_DEFAULT_SECRET and len(secret) >= 32
    assert "publicly known" in caplog.text or "default" in caplog.text


def test_a_short_secret_still_works_but_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert resolve_secret_key("short", str(tmp_path / "s")) == "short"
    assert "short" in caplog.text.lower() or "16" in caplog.text


def test_two_fresh_installs_never_share_a_secret(tmp_path):
    a = resolve_secret_key(None, str(tmp_path / "a"))
    b = resolve_secret_key(None, str(tmp_path / "b"))
    assert a != b


def test_an_unwritable_location_falls_back_to_a_per_process_secret_instead_of_crashing(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    secret = resolve_secret_key(None, str(blocker / "nested" / "secret"))   # parent is a file: cannot create
    assert len(secret) >= 32


def test_the_running_config_never_uses_the_public_default_secret():
    assert config_mod.Config.FLASK_SECRET_KEY != INSECURE_DEFAULT_SECRET
    assert len(config_mod.Config.FLASK_SECRET_KEY) >= 16


def test_new_operational_settings_have_safe_defaults():
    c = config_mod.Config
    assert c.FLASK_DEBUG is False
    assert c.HOST == "127.0.0.1"
    assert c.RATE_LIMIT_CHAT_PER_MINUTE > 0 and c.RATE_LIMIT_UPLOAD_PER_MINUTE > 0
    assert c.MAX_MESSAGE_CHARS >= 1000
    assert isinstance(c.TRUSTED_ORIGINS, list)


@pytest.mark.parametrize("placeholder", [
    "replace_with_a_random_secret",       # what .env.example used to tell people to copy
    "changeme", "change-me", "CHANGE_ME", "your_secret_key_here", "secret", "  dev-only-change-me  ",
])
def test_copied_placeholder_secrets_are_treated_as_unset(tmp_path, placeholder):
    generated = resolve_secret_key(placeholder, str(tmp_path / "s"))
    assert generated != placeholder.strip() and len(generated) >= 32


def test_the_shipped_env_example_does_not_set_a_usable_secret():
    """Anyone who copies .env.example to .env without editing it must not end up with a public secret."""
    from pathlib import Path

    line = next(l for l in Path(".env.example").read_text().splitlines() if l.startswith("FLASK_SECRET_KEY="))
    value = line.split("=", 1)[1].strip()
    assert value == "" or value in config_mod._PLACEHOLDER_SECRETS


# ---- choosing the LLM provider ----

def test_the_provider_defaults_to_mistral_when_unset_or_blank(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert _env_provider("LLM_PROVIDER", "mistral") == "mistral"
    monkeypatch.setenv("LLM_PROVIDER", "   ")
    assert _env_provider("LLM_PROVIDER", "mistral") == "mistral"


@pytest.mark.parametrize("value", ["openai", "OPENAI", "  Ollama  ", "mistral"])
def test_supported_providers_are_accepted_case_insensitively(monkeypatch, value):
    monkeypatch.setenv("LLM_PROVIDER", value)
    assert _env_provider("LLM_PROVIDER", "mistral") == value.strip().lower()


@pytest.mark.parametrize("value", ["gemini", "claude", "gpt", "local"])
def test_an_unsupported_provider_is_a_clear_error_that_lists_the_options(monkeypatch, value):
    monkeypatch.setenv("LLM_PROVIDER", value)
    with pytest.raises(ConfigError) as exc:
        _env_provider("LLM_PROVIDER", "mistral")
    message = str(exc.value)
    assert "LLM_PROVIDER" in message and repr(value) in message
    assert all(name in message for name in SUPPORTED_PROVIDERS)


def test_the_running_config_has_a_supported_provider_and_sane_agent_limits():
    c = config_mod.Config
    assert c.LLM_PROVIDER in SUPPORTED_PROVIDERS
    assert c.MAX_TOOL_CALLS >= 1 and c.MAX_CONTEXT_MESSAGES >= 1


def test_the_env_example_documents_every_setting_the_app_reads():
    """If someone adds a setting to config.py but forgets .env.example, the README's promise breaks."""
    from pathlib import Path
    import re

    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", Path(".env.example").read_text(), flags=re.M))
    source = Path("src/config.py").read_text()
    read_by_config = set(re.findall(r'(?:os\.getenv|_env_\w+|_env_provider)\(\s*"([A-Z][A-Z0-9_]+)"', source))
    assert read_by_config, "expected to find settings in config.py"
    assert read_by_config <= documented, f"missing from .env.example: {sorted(read_by_config - documented)}"
