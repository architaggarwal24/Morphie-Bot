"""
Central configuration for Morphie-Bot.

All environment variables are read in exactly one place so the rest of
the codebase never calls os.getenv() directly. This keeps secrets out of
the frontend and makes it obvious what needs to be set in .env.

A malformed value (e.g. MAX_TOOL_CALLS=abc) raises ConfigError naming the
variable, instead of a bare "invalid literal for int()" traceback.
"""

import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("morphie.config")

# Values people copy from examples and forget to change. Being public, none of
# them may ever act as the real secret; they are treated exactly like "unset".
_PLACEHOLDER_SECRETS = {
    "dev-only-change-me", "replace_with_a_random_secret", "your_secret_key_here",
    "changeme", "change-me", "change_me", "secret", "secret-key", "secretkey", "password",
}

# The LLM providers this project supports (see morphie/providers/registry.py).
SUPPORTED_PROVIDERS = ("mistral", "openai", "ollama")


class ConfigError(ValueError):
    """A setting in the environment / .env file is invalid. The message
    says which one and how to fix it."""


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, but it is {raw!r}. Fix it in your .env file.") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be at least {minimum} (got {value}). Fix it in your .env file.")
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} must be a number, but it is {raw!r}. Fix it in your .env file.") from None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false, but it is {raw!r}. Fix it in your .env file.")


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def resolve_secret_key(env_value: str | None, key_file: str) -> str:
    """The key that signs session cookies (and therefore *is* a user's identity).

    Never falls back to a well-known default: if FLASK_SECRET_KEY is unset, a
    random one is generated once and saved (owner-readable only) so sessions,
    and the documents tied to them, survive restarts.
    """
    env_value = (env_value or "").strip()
    if env_value.lower() in _PLACEHOLDER_SECRETS:
        logger.warning("FLASK_SECRET_KEY is a publicly known placeholder; ignoring it and generating a secret.")
        env_value = ""

    if env_value:
        if len(env_value) < 16:
            logger.warning(
                "FLASK_SECRET_KEY is shorter than 16 characters. Use a long random value: "
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return env_value

    path = Path(key_file)
    try:
        if path.exists():
            existing = path.read_text().strip()
            if len(existing) >= 32:
                return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secret)
        logger.warning(
            "FLASK_SECRET_KEY is not set; generated one and saved it to %s. Set FLASK_SECRET_KEY in .env "
            "to manage it yourself.", path,
        )
        return secret
    except OSError:
        logger.warning(
            "FLASK_SECRET_KEY is not set and %s is not writable; using a temporary secret. "
            "Sessions will be lost on restart - set FLASK_SECRET_KEY in .env.", path,
        )
        return secrets.token_hex(32)


def _env_provider(name: str, default: str) -> str:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"{name} must be one of {', '.join(SUPPORTED_PROVIDERS)}, but it is {raw!r}. Fix it in your .env file."
        )
    return raw


class Config:
    # ---- Flask ----
    # Signs the session cookie, which is what identifies a browser (and so
    # its documents). If unset, a random key is generated once and stored in
    # SECRET_KEY_FILE - never a shared default.
    SECRET_KEY_FILE = os.getenv("SECRET_KEY_FILE", "data/.flask_secret")
    FLASK_SECRET_KEY = resolve_secret_key(os.getenv("FLASK_SECRET_KEY"), SECRET_KEY_FILE)

    # ---- Server (used by `python app.py`) ----
    # Debug mode exposes Werkzeug's interactive debugger (arbitrary code
    # execution for anyone who can reach it) - off unless you ask for it,
    # and bound to localhost by default.
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = _env_int("PORT", 5000, minimum=1)
    FLASK_DEBUG = _env_bool("FLASK_DEBUG", False)
    # Set true when serving over HTTPS so the session cookie is never sent over HTTP.
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    # Extra origins allowed to make state-changing requests (e.g. behind a
    # reverse proxy that changes the Host header). Comma-separated.
    TRUSTED_ORIGINS = _env_list("TRUSTED_ORIGINS")

    # ---- Request limits ----
    MAX_MESSAGE_CHARS = _env_int("MAX_MESSAGE_CHARS", 8000, minimum=1)
    # Per-user (and, more loosely, per-IP) limits on the endpoints that cost
    # money or CPU. 0 disables a limit; RATE_LIMIT_ENABLED=false disables all.
    RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
    RATE_LIMIT_CHAT_PER_MINUTE = _env_int("RATE_LIMIT_CHAT_PER_MINUTE", 30, minimum=0)
    RATE_LIMIT_UPLOAD_PER_MINUTE = _env_int("RATE_LIMIT_UPLOAD_PER_MINUTE", 10, minimum=0)

    # ---- LLM provider ----
    # Which model backend answers: "mistral" (default), "openai" or "ollama".
    # Only that provider's settings below are needed.
    LLM_PROVIDER = _env_provider("LLM_PROVIDER", "mistral")
    # Optional: override the provider's default model.
    LLM_MODEL = (os.getenv("LLM_MODEL") or "").strip() or None
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    # Ollama runs locally and needs no API key.
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # ---- Agent / tool calling ----
    # Hard cap on tool round-trips the agent takes in a single turn, to
    # prevent an infinite tool-call loop. If reached, the agent stops
    # calling tools and asks the LLM for one last plain-text answer.
    MAX_TOOL_CALLS = _env_int("MAX_TOOL_CALLS", 5, minimum=1)

    # ---- Optional tools ----
    # Enables the web_search tool's real provider (Tavily). If unset, the
    # tool is still registered but returns a safe "not configured"
    # message instead of hitting an unreliable/unofficial free service.
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

    # ---- Conversation ----
    # How many recent {role, content} messages are kept (in memory, per
    # browser) as conversation context and sent to the LLM on each turn.
    MAX_CONTEXT_MESSAGES = _env_int("MAX_CONTEXT_MESSAGES", 20, minimum=1)

    # ---- Document RAG ----
    # Where uploaded documents and the vector store are persisted, kept
    # out of application code and never committed (see .gitignore).
    RAG_UPLOAD_DIR = os.getenv("RAG_UPLOAD_DIR", "data/documents")
    RAG_VECTOR_STORE_PATH = os.getenv("RAG_VECTOR_STORE_PATH", "data/vector_store/rag.sqlite3")

    # Reject uploads larger than this (checked against real bytes read,
    # not just the Content-Length header).
    RAG_MAX_UPLOAD_SIZE_MB = _env_int("RAG_MAX_UPLOAD_SIZE_MB", 20, minimum=1)
    # A document that would need more chunks than this is rejected, so a
    # single huge file can't monopolise the embedder and the vector store.
    RAG_MAX_CHUNKS_PER_DOCUMENT = _env_int("RAG_MAX_CHUNKS_PER_DOCUMENT", 2000, minimum=1)

    # Chunking: character-based, word-boundary-respecting.
    RAG_CHUNK_SIZE = _env_int("RAG_CHUNK_SIZE", 1000)
    RAG_CHUNK_OVERLAP = _env_int("RAG_CHUNK_OVERLAP", 150)

    # Retrieval.
    RAG_TOP_K = _env_int("RAG_TOP_K", 5)
    RAG_MIN_SCORE = _env_float("RAG_MIN_SCORE", 0.15)

    # Embeddings are a dependency-free, offline hashing-based embedding:
    # no API calls, no model download, works everywhere.
    RAG_LOCAL_EMBEDDING_DIM = _env_int("RAG_LOCAL_EMBEDDING_DIM", 384)
