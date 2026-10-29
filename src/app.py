import json
import queue
import re
import threading
import time
import uuid
from datetime import timedelta

from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, request, jsonify, send_from_directory, session, stream_with_context
from werkzeug.exceptions import HTTPException

from config import Config, apply_worker_env
from morphie.agent.orchestrator import AgentOrchestrator, TurnCancelled
from morphie.agent.tool_router import ToolRouter
from morphie.d1 import D1, D1ConversationHistory, D1RateLimiter
from morphie.history import ConversationHistory
from morphie.orchestrator import MorphieOrchestrator
from morphie.providers.base import LLMProvider, ProviderError, ProviderNotConfiguredError
from morphie.providers.embeddings import EmbeddingProvider
from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.providers.registry import registry
from morphie.rag.d1_store import D1VectorStore
from morphie.rag.pipeline import RAGIngestionError, RAGPipeline
from morphie.rag.vector_store import LocalVectorStore
from morphie.runtime import IS_WORKERS
from morphie.security import RateLimiter, is_trusted_origin

# The web UI is a React app built by Vite (web/) into public/. Cloudflare serves public/ straight from the edge;
# locally Flask serves the very same files, so there is one UI and one build for both.
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

app = Flask(__name__, static_folder=None)
# JSON endpoints carry short messages; only the upload route needs a large body.
MAX_JSON_BODY_BYTES = 256 * 1024

_PROVIDER_KEY_ENV = {"mistral": "MISTRAL_API_KEY", "openai": "OPENAI_API_KEY"}


# ---- The LLM provider -------------------------------------------------------
# One provider, chosen in .env (LLM_PROVIDER=mistral|openai|ollama). Everything
# downstream talks to the LLMProvider interface, never to a vendor SDK directly.

def build_provider() -> LLMProvider:
    api_keys = {"mistral": Config.MISTRAL_API_KEY, "openai": Config.OPENAI_API_KEY, "ollama": None}
    kwargs = {"base_url": Config.OLLAMA_BASE_URL} if Config.LLM_PROVIDER == "ollama" else {}
    return registry.get(Config.LLM_PROVIDER, api_key=api_keys[Config.LLM_PROVIDER], model=Config.LLM_MODEL, **kwargs)


# ---- Request guards: rate limits --------------------------------------------

def _build_limiters(chat_per_minute: int, upload_per_minute: int, enabled: bool = True, factory=None) -> dict:
    """(per-user, per-IP) limiters for the endpoints that cost money or CPU.
    The per-IP cap is looser (5x) so one shared address isn't punished for
    several users, while still bounding someone who keeps discarding cookies.

    `factory(scope, limit)` builds a limiter; the default is the in-memory one. On Cloudflare Workers the
    D1-backed limiter is passed instead, because an isolate's memory is not shared or durable."""
    make = factory or (lambda scope, limit: RateLimiter(limit, 60.0))

    def pair(name: str, limit: int):
        limit = limit if enabled else 0
        return make(f"{name}:user", limit), make(f"{name}:ip", limit * 5)
    return {
        "/chat": pair("chat", chat_per_minute),
        "/chat/followups": pair("followups", chat_per_minute),
        "/chat/cancel": pair("cancel", chat_per_minute * 2),
        "/chat/rewind": pair("rewind", chat_per_minute * 2),
        "/documents/upload": pair("upload", upload_per_minute),
    }


# ---- The runtime: provider, agent, history, document RAG, limiters ----------
# Built once at import on a normal server. On Cloudflare Workers settings and bindings only exist per request,
# so the same function is run from _WorkersBootstrap with the request's env and a D1 database.

tool_router = ToolRouter()
provider = agent = history = rag_pipeline = _rate_limiters = None


def _build_runtime(db: "D1 | None" = None) -> None:
    global provider, agent, history, rag_pipeline, _rate_limiters

    app.secret_key = Config.FLASK_SECRET_KEY
    # Documents are tied to this session cookie identifying "this browser" -
    # keep it alive across restarts so uploaded documents stay yours.
    app.permanent_session_lifetime = timedelta(days=365)
    # Defense in depth on top of RAGPipeline's own byte-count check: reject
    # oversized request bodies at the Werkzeug level before they're even
    # fully read into memory. A little headroom over the configured limit
    # accounts for multipart form overhead (boundaries, field headers).
    app.config["MAX_CONTENT_LENGTH"] = Config.RAG_MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 64 * 1024
    # The session cookie *is* the user's identity: never readable by page scripts,
    # not sent on cross-site requests, and (when serving HTTPS) never over HTTP.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=Config.SESSION_COOKIE_SECURE,
    )

    provider = build_provider()
    agent = AgentOrchestrator(provider, tool_router, max_tool_calls=Config.MAX_TOOL_CALLS)

    # Document RAG with a dependency-free, offline embedding - works with zero extra setup.
    embeddings = LocalEmbeddingProvider(dim=Config.RAG_LOCAL_EMBEDDING_DIM)
    if db is None:
        history = ConversationHistory(max_messages=Config.MAX_CONTEXT_MESSAGES)
        store, upload_dir, limiter_factory = LocalVectorStore(db_path=Config.RAG_VECTOR_STORE_PATH), Config.RAG_UPLOAD_DIR, None
    else:
        history = D1ConversationHistory(db, max_messages=Config.MAX_CONTEXT_MESSAGES)
        store, upload_dir = D1VectorStore(db), None  # no disk: only the extracted chunks are kept
        limiter_factory = lambda scope, limit: D1RateLimiter(db, scope, limit)  # noqa: E731
    rag_pipeline = RAGPipeline(
        embedding_provider=embeddings,
        vector_store=store,
        upload_dir=upload_dir,
        max_upload_size_mb=Config.RAG_MAX_UPLOAD_SIZE_MB,
        chunk_size=Config.RAG_CHUNK_SIZE,
        chunk_overlap=Config.RAG_CHUNK_OVERLAP,
        top_k=Config.RAG_TOP_K,
        min_score=Config.RAG_MIN_SCORE,
        max_chunks_per_document=Config.RAG_MAX_CHUNKS_PER_DOCUMENT,
    )
    _rate_limiters = _build_limiters(
        Config.RATE_LIMIT_CHAT_PER_MINUTE, Config.RATE_LIMIT_UPLOAD_PER_MINUTE, Config.RATE_LIMIT_ENABLED, limiter_factory,
    )


def _make_d1(binding) -> D1:
    """Wrap the Worker's D1 binding. A function so tests can swap in a fake binding without Pyodide."""
    return D1(binding)


class _WorkersBootstrap:
    """WSGI middleware used only on Cloudflare Workers. Before Flask touches the request it applies that request's
    `env` (vars, secrets) to the configuration and points the app at the D1 database, so the secret key exists
    before the session cookie is read. A failure is recorded and reported as a clean JSON error by guard_request."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        try:
            env = environ["workers.env"]
            apply_worker_env(env)
            _build_runtime(_make_d1(env.DB))
        except Exception:  # noqa: BLE001 - reported per request below; never leak details to the browser
            app.logger.exception("Could not initialise the Worker runtime")
            environ["morphie.boot_error"] = True
        return self.wsgi_app(environ, start_response)


if IS_WORKERS:
    app.wsgi_app = _WorkersBootstrap(app.wsgi_app)
else:
    _build_runtime()


def get_user_id() -> str:
    """Stable identity for 'this browser', used to scope short-term
    conversation history and uploaded documents. Not real authentication -
    Morphie-Bot has none - just enough identity to keep one browser's
    documents from ever being visible to another."""
    session.permanent = True
    if "user_id" not in session:
        session["user_id"] = uuid.uuid4().hex
    return session["user_id"]


def provider_display_name() -> str:
    info = registry.get_info(Config.LLM_PROVIDER)
    return info.display_name if info else Config.LLM_PROVIDER


def resolve_provider() -> LLMProvider:
    """The server's own provider (from .env / Worker settings), or a friendly 'how to fix it' error."""
    if not provider.is_configured():
        key_env = _PROVIDER_KEY_ENV.get(Config.LLM_PROVIDER)
        hint = (
            f"Add your API key in Settings, or set {key_env} in .env and restart."
            if key_env else "Pick a provider in Settings, or check your .env file and restart."
        )
        raise ProviderNotConfiguredError(
            f"{provider_display_name()} is not configured. {hint}", provider=provider_display_name(),
        )
    return provider


# ---- Bring your own key (BYOK) -----------------------------------------------
# A visitor can choose the provider, model and API key in the page's Settings. The browser keeps them and sends
# them as headers with each request; the server uses them for that request only and never stores or logs them.
# With no headers the server's own provider is used (a self-hoster's .env), so nothing changes for them.
# Providers have fixed, known endpoints. The one exception, "Custom URL", lets the visitor name the server to
# call, which would let anyone aim this server at arbitrary addresses (SSRF) - so it only exists when the owner
# turns it on (ALLOW_CUSTOM_LLM_URL) for a deployment only they use.

HEADER_PROVIDER, HEADER_MODEL, HEADER_KEY = "X-LLM-Provider", "X-LLM-Model", "X-LLM-Key"
HEADER_BASE_URL = "X-LLM-Base-URL"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,119}$")
_API_KEY_RE = re.compile(r"^[\x21-\x7e]{8,400}$")  # printable ASCII, no spaces, no control characters
_BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?(/[A-Za-z0-9._~/-]*)?$")


def _blocked_host(url: str) -> bool:
    """Addresses a Custom URL may never point at even when the owner allows Custom URLs: cloud metadata services
    (link-local 169.254.x.x and friends), the unspecified address, and bare-number IPs (2130706433 = 127.0.0.1),
    which exist mainly to slip past checks like this one."""
    host = (urlparse(url).hostname or "").lower()
    return (
        not host
        or host.isdigit()
        or host.startswith("169.254.")
        or host in {"0.0.0.0", "metadata.google.internal", "metadata", "100.100.100.200"}
        or host.endswith(".internal")
    )


def byok_providers() -> list:
    """Providers a visitor may use. Ollama needs no key and lives on the server's own network, so it is only
    offered when the app runs on your machine, never on a hosted deployment. Custom URL needs the owner's opt-in."""
    offered = []
    for info in registry.list_providers():
        if info.id == "custom":
            if Config.ALLOW_CUSTOM_LLM_URL:
                offered.append(info)
        elif info.requires_api_key or not IS_WORKERS:
            offered.append(info)
    return offered


def _provider_choice() -> dict | None:
    """The visitor's choice from the request headers, validated, or None to use the server's provider.
    Never echoes the key back in an error."""
    provider_id = request.headers.get(HEADER_PROVIDER, "").strip().lower()
    if not provider_id:
        return None
    info = next((i for i in byok_providers() if i.id == provider_id), None)
    if info is None:
        raise ApiError("That model provider isn't available here.", 400, "invalid_provider")
    model = request.headers.get(HEADER_MODEL, "").strip() or None
    if model and not _MODEL_RE.match(model):
        raise ApiError("That model name isn't valid.", 400, "invalid_model")
    key = request.headers.get(HEADER_KEY, "").strip() or None
    if key and not _API_KEY_RE.match(key):
        raise ApiError("That API key doesn't look valid. Re-copy it from your provider's dashboard.", 400, "invalid_api_key")
    base_url = None
    if info.id == "custom":
        base_url = request.headers.get(HEADER_BASE_URL, "").strip().rstrip("/") or None
        if not base_url or len(base_url) > 200 or not _BASE_URL_RE.match(base_url) or _blocked_host(base_url):
            raise ApiError("Enter the server's URL, like http://localhost:1234/v1.", 400, "invalid_base_url")
    keep_key = info.requires_api_key or info.id == "custom"
    return {"info": info, "model": model or info.default_model, "key": key if keep_key else None, "base_url": base_url}


def request_provider_resolver():
    """The provider for this request, as a zero-argument callable (the orchestrator calls it only when the model
    is actually needed, so a greeting works with no key). Must be called inside the request: the streaming
    thread can't see the request's headers, so the choice is captured here."""
    choice = _provider_choice()
    if choice is None:
        return resolve_provider
    info = choice["info"]

    def resolve() -> LLMProvider:
        if info.requires_api_key and not choice["key"]:
            raise ProviderNotConfiguredError(
                f"{info.display_name} needs an API key. Open Settings and add yours.", provider=info.display_name,
            )
        kwargs = {}
        if info.id == "ollama":
            kwargs = {"base_url": Config.OLLAMA_BASE_URL}
        elif info.id == "custom":
            kwargs = {"base_url": choice["base_url"]}
        return registry.get(info.id, api_key=choice["key"], model=choice["model"], **kwargs)

    return resolve


def request_embedder() -> EmbeddingProvider | None:
    """Meaning-based embeddings for document search, from the same provider and key that answer this request
    (or the server's own .env provider). None = keyword search only."""
    if not Config.RAG_SEMANTIC_SEARCH:
        return None
    choice = _provider_choice()
    if choice is not None:
        provider_id, key = choice["info"].id, choice["key"]
    else:
        provider_id = Config.LLM_PROVIDER
        key = {"mistral": Config.MISTRAL_API_KEY, "openai": Config.OPENAI_API_KEY}.get(provider_id)
    return registry.get_embedder(provider_id, api_key=key, base_url=Config.OLLAMA_BASE_URL)


def _orchestrator() -> MorphieOrchestrator:
    """Built from the module's current collaborators on each call (cheap), so
    swapping one - e.g. a test installing a fake provider - takes effect."""
    return MorphieOrchestrator(agent=agent, tool_router=tool_router, history=history, rag=rag_pipeline)


# ---- Errors: one shape, no internals ----
#
# Every failure is JSON {"error": <message>, "code": <machine-readable>}. On
# /chat the chat UI also gets {"type": "text", "content": "⚠️ <message>"} so
# an error can never render as "undefined". Tracebacks go to the server log
# and never to the browser.

class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", content: str | None = None):
        super().__init__(message)
        self.message, self.status, self.code, self.content = message, status, code, content


def error_response(message: str, status: int, code: str = "error", content: str | None = None, **headers):
    body = {"error": message, "code": code}
    if request.path in ("/chat", "/chat/stream"):
        body.update({"type": "text", "content": content if content is not None else f"⚠️ {message}"})
    response = jsonify(body)
    response.status_code = status
    for name, value in headers.items():
        response.headers[name.replace("_", "-")] = str(value)
    return response


@app.errorhandler(ApiError)
def handle_api_error(exc: ApiError):
    return error_response(exc.message, exc.status, exc.code, exc.content)


@app.errorhandler(413)
def handle_request_too_large(_error):
    return error_response(f"File is too large - the limit is {Config.RAG_MAX_UPLOAD_SIZE_MB} MB.", 413, "too_large")


_HTTP_MESSAGES = {
    400: "That request wasn't valid.",
    404: "That doesn't exist.",
    405: "That action isn't allowed here.",
    415: "Requests to this endpoint must be JSON.",
}


@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    return error_response(_HTTP_MESSAGES.get(exc.code, "The request couldn't be completed."), exc.code or 500, "http_error")


@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    return error_response("Something went wrong on our side. Please try again.", 500, "internal_error")


# ---- Request guards: CSRF, body size, rate limits ----

# /chat/stream costs exactly what /chat costs (one model call); without this
# alias a client could double its effective rate by alternating endpoints.
_RATE_LIMIT_ALIASES = {"/chat/stream": "/chat"}

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.before_request
def guard_request():
    if request.environ.get("morphie.boot_error") or not app.secret_key:
        return error_response(
            "The server isn't configured yet (a required secret or the database binding is missing).",
            500, "not_configured",
        )
    if request.method in _UNSAFE_METHODS:
        # CSRF: a page on another site can make the browser send our cookie,
        # but it cannot forge the Origin header.
        if not is_trusted_origin(request.headers, request.host, Config.TRUSTED_ORIGINS):
            return error_response("This request came from another website and was blocked.", 403, "cross_site")
        if request.mimetype == "application/json" and (request.content_length or 0) > MAX_JSON_BODY_BYTES:
            return error_response("That request is too large.", 413, "too_large")

        limiters = _rate_limiters.get(_RATE_LIMIT_ALIASES.get(request.path, request.path))
        if limiters:
            user_limiter, ip_limiter = limiters
            # Establish the identity first: counting a browser's very first request
            # under a different key than its later ones would let one request slip
            # through. Clients that never keep cookies get a fresh identity each
            # time, so for them the (looser) per-IP limit is what applies.
            identity = get_user_id()
            for limiter, key in ((user_limiter, identity), (ip_limiter, client_ip())):
                allowed, retry_after = limiter.check(key)
                if not allowed:
                    return error_response(
                        f"You're sending requests too quickly. Please wait {retry_after} seconds and try again.",
                        429, "rate_limited", Retry_After=retry_after,
                    )
    return None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # Scripts may only load from this origin: the UI is a Vite-built bundle with
    # no inline <script>, inline handlers, eval, or CDN (tests/test_app_security.py
    # guards that, since a violation would be silently blocked by browsers).
    # No 'unsafe-inline' for scripts, so an injected <script> or onclick= cannot
    # run even if escaping ever failed. Styles are deliberately not restricted:
    # the animation library writes inline style attributes.
    response.headers.setdefault(
        "Content-Security-Policy",
        "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
    )
    if response.mimetype == "application/json":
        response.headers["Cache-Control"] = "no-store"  # personal data: documents
    return response


# ---- Input validation ----

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_DOCUMENT_IDS = 99  # D1 allows 100 bound parameters per statement; the workspace id is one of them


def client_ip() -> str:
    """The caller's address. Behind Cloudflare the TCP peer is Cloudflare itself, so the real client is in
    CF-Connecting-IP (set by Cloudflare and not forgeable from outside). Elsewhere it's the socket address."""
    if IS_WORKERS:
        return request.headers.get("CF-Connecting-IP") or "?"
    return request.remote_addr or "?"


def json_object() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def clean_document_ids(value) -> list[str] | None:
    """`None` (or anything that isn't a list) means "ask about all documents"."""
    if not isinstance(value, list):
        return None
    return [d for d in value[:MAX_DOCUMENT_IDS] if isinstance(d, str) and 0 < len(d) <= 64]


@app.route("/")
def home():
    get_user_id()
    if not (PUBLIC_DIR / "index.html").is_file():
        return error_response(
            "The web UI hasn't been built yet. Run: npm --prefix web install && npm --prefix web run build",
            503, "ui_not_built",
        )
    response = send_from_directory(PUBLIC_DIR, "index.html", max_age=0)
    response.headers["Cache-Control"] = "no-cache"  # always revalidate: it names the current hashed bundle
    return response


@app.route("/assets/<path:filename>")
def assets(filename):
    # Vite puts a content hash in every asset name, so these can be cached forever.
    return send_from_directory(PUBLIC_DIR / "assets", filename, max_age=31536000)


@app.route("/favicon.svg")
def favicon():
    return send_from_directory(PUBLIC_DIR, "favicon.svg", max_age=86400)


@app.route("/status", methods=["GET"])
def status():
    """Which provider/model answers, and whether it is ready - so the UI can
    show a clear 'add your key' hint instead of failing on the first message."""
    choice = _provider_choice()
    if choice is not None:
        return jsonify({
            "provider": choice["info"].display_name,
            "model": choice["model"],
            "configured": bool(choice["key"]) or not choice["info"].requires_api_key,
        })
    return jsonify({
        "provider": provider_display_name(),
        "model": provider.model,
        "configured": provider.is_configured(),
    })


@app.route("/providers", methods=["GET"])
def providers():
    """What the Settings dialog can offer, plus whether the server has a provider of its own."""
    return jsonify({
        "providers": [
            {
                "id": i.id, "name": i.display_name, "default_model": i.default_model,
                "models": i.example_models, "requires_key": i.requires_api_key,
                "group": i.group, "semantic_search": bool(i.embedding_model) and Config.RAG_SEMANTIC_SEARCH,
                "needs_base_url": i.id == "custom",
            }
            for i in byok_providers()
        ],
        "server_default": {"provider": Config.LLM_PROVIDER, "configured": provider.is_configured()},
        "features": {"followups": Config.FOLLOWUP_SUGGESTIONS},
    })


def _validate_chat_input(body: dict) -> str:
    """The checks /chat and /chat/stream share, so both reject bad input
    identically and before either one starts a response. Returns the
    message or raises ApiError."""
    message = body.get("message")
    if message is not None and not isinstance(message, str):
        raise ApiError("'message' must be text.", 400, "invalid_field")
    message = (message or "").strip()
    if not message:
        raise ApiError("Please enter a message.", 400, "empty_message", content="Please enter a message.")
    if len(message) > Config.MAX_MESSAGE_CHARS:
        raise ApiError(
            f"That message is too long (the limit is {Config.MAX_MESSAGE_CHARS:,} characters).", 413, "message_too_long",
        )
    return message


def resolve_orchestrator_error(exc: Exception) -> tuple[str, int, str]:
    """Map an exception from MorphieOrchestrator.handle_chat to (message,
    status, code) - the message is always safe to show the user. Logs at an
    appropriate level as a side effect. Shared by /chat (an ordinary HTTP
    error response) and /chat/stream (an `error` SSE event instead, since an
    SSE response's status can't change once streaming has started)."""
    if isinstance(exc, ProviderNotConfiguredError):
        return exc.friendly_message, 500, "provider_not_configured"
    if isinstance(exc, ProviderError):
        # Friendly and provider-agnostic; never the raw exception (which could
        # echo request/response details) or the API key.
        app.logger.warning("Provider error (%s): %s", exc.provider or "unknown", exc.friendly_message)
        return exc.friendly_message, 502, "provider_error"
    # exc_info=exc (not the bare .exception() shortcut): /chat/stream catches
    # this in a background thread and maps it here from the main thread's
    # generator, with no active `except` block - .exception() would log
    # nothing useful there. Passing the exception object explicitly renders
    # its real traceback in both cases.
    app.logger.error("Morphie request failed", exc_info=exc)
    return "Morphie could not complete that request. Please try again.", 502, "request_failed"


_TURN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# "/calc", "/web"... in the composer name a tool the visitor wants used; anything else is ignored.
_TOOL_HINTS = {"calculator", "get_current_time", "web_search", "search_documents"}


def _turn_options(body: dict) -> tuple[str, str | None]:
    """The page's id for this question-and-answer pair (made up here if missing) and an optional forced tool."""
    turn_id = body.get("turn_id")
    if turn_id is not None and (not isinstance(turn_id, str) or not _TURN_ID_RE.match(turn_id)):
        raise ApiError("That turn id isn't valid.", 400, "invalid_field")
    tool_hint = body.get("tool")
    if tool_hint is not None and tool_hint not in _TOOL_HINTS:
        raise ApiError("That tool doesn't exist.", 400, "invalid_field")
    return turn_id or uuid.uuid4().hex, tool_hint


# Turns in flight on this server: (user, turn) -> Event. Set by Stop (POST /chat/cancel) or when the page goes
# away mid-stream, and checked by the agent before every model and tool call.
_active_turns: dict[tuple[str, str], threading.Event] = {}
_active_lock = threading.Lock()


def _begin_turn(user_id: str, turn_id: str) -> threading.Event:
    event = threading.Event()
    with _active_lock:
        _active_turns[(user_id, turn_id)] = event
    return event


def _end_turn(user_id: str, turn_id: str, event: threading.Event) -> None:
    with _active_lock:
        if _active_turns.get((user_id, turn_id)) is event:  # a reused turn id must not end another stream's turn
            del _active_turns[(user_id, turn_id)]


@app.route("/chat", methods=["POST"])
def chat():
    """One user message -> one reply. Body: {"message": str, "document_ids": [str] | null, "turn_id"?: str,
    "tool"?: str}. For live progress (tool calls, streamed text), use POST /chat/stream instead - the two share
    validation and return the same JSON."""
    user_id = get_user_id()
    body = json_object()
    message = _validate_chat_input(body)
    turn_id, tool_hint = _turn_options(body)
    resolver = request_provider_resolver()
    semantic = request_embedder

    try:
        payload = _orchestrator().handle_chat(
            user_id=user_id, text=message,
            document_ids=clean_document_ids(body.get("document_ids")),
            provider=resolver, turn_id=turn_id, tool_hint=tool_hint, semantic=semantic,
        )
        return jsonify(payload)
    except TurnCancelled:
        return error_response("That answer was stopped.", 409, "cancelled")
    except Exception as exc:  # noqa: BLE001 - every case is mapped to a safe message below
        friendly_message, status, code = resolve_orchestrator_error(exc)
        return error_response(friendly_message, status, code)


_STREAM_CHUNK_WORDS = 3
_STREAM_CHUNK_DELAY_SECONDS = 0.02
_HEARTBEAT_SECONDS = 1.0


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _typewriter_chunks(text: str):
    """`text` split into a few-word pieces that, concatenated, reproduce it
    exactly (whitespace included). Used to reveal a finished reply
    progressively when the provider could not stream it."""
    words = text.split(" ")
    if words == [""]:
        return
    for i in range(0, len(words), _STREAM_CHUNK_WORDS):
        piece = " ".join(words[i:i + _STREAM_CHUNK_WORDS])
        yield piece + " " if i + _STREAM_CHUNK_WORDS < len(words) else piece


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """Same input and the same result as POST /chat, delivered as
    Server-Sent Events so the UI can show the agent working instead of a
    blank wait. Frames, in order:

      event: step     {"type": "thinking" | "tool_call" | "tool_result" | "discard_text", ...}
                       - emitted the instant each one actually happens (see
                       AgentOrchestrator.run for the details they carry).
      event: token     {"text": "..."}  - the reply. Streamed from the provider
                       as it writes when it can (OpenAI, Mistral, Ollama and the
                       compatible ones); otherwise the finished reply revealed a
                       few words at a time.
      event: message   the exact JSON body POST /chat would return for the
                       same input - always sent exactly once, last.
      event: error     {"message", "code"} in place of `message` if the
                       turn failed (see resolve_orchestrator_error).

    Lines starting with ":" are heartbeats; they are how the server notices that
    the page went away (Stop, closed tab) and stops the turn without saving it.

    Input is validated up front exactly like /chat (shares
    _validate_chat_input), so bad input still gets a normal 4xx/413 JSON
    response before any stream starts. Once streaming has begun, HTTP
    status is fixed at 200 (headers are already sent as text/event-stream),
    so a failure becomes an `error` event rather than a different status.
    """
    user_id = get_user_id()
    body = json_object()
    message = _validate_chat_input(body)
    turn_id, tool_hint = _turn_options(body)
    document_ids = clean_document_ids(body.get("document_ids"))
    resolver = request_provider_resolver()  # captured here: the streaming thread can't see request headers
    semantic = request_embedder()
    orchestrator = _orchestrator()

    def generate():
        if IS_WORKERS:
            # Pyodide has no threads, and the WSGI adapter sends the response whole: run the turn to completion,
            # then replay its steps and reply as the same SSE events. The client sees identical frames; they just
            # arrive together instead of live.
            frames: list[str] = []
            streamed: list[str] = []
            try:
                payload = orchestrator.handle_chat(
                    user_id=user_id, text=message, document_ids=document_ids, provider=resolver,
                    on_step=lambda e: frames.append(_sse("step", e)), on_token=streamed.append,
                    turn_id=turn_id, tool_hint=tool_hint, semantic=semantic,
                    # no threads here: a Stop arrives as POST /chat/cancel (another isolate) and leaves a tombstone
                    should_cancel=lambda: history.is_cancelled(user_id, turn_id),
                )
            except TurnCancelled:
                yield from frames
                yield _sse("error", {"message": "That answer was stopped.", "code": "cancelled"})
                return
            except Exception as exc:  # noqa: BLE001 - reported as an SSE error event, never raised here
                yield from frames
                friendly_message, _status, code = resolve_orchestrator_error(exc)
                yield _sse("error", {"message": friendly_message, "code": code})
                return
            yield from frames
            for chunk in _typewriter_chunks(payload.get("content") or ""):
                yield _sse("token", {"text": chunk})
            yield _sse("message", payload)
            return

        events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        cancel = _begin_turn(user_id, turn_id)

        def worker() -> None:
            try:
                payload = orchestrator.handle_chat(
                    user_id=user_id, text=message, document_ids=document_ids, provider=resolver,
                    on_step=lambda e: events.put(("step", e)), on_token=lambda t: events.put(("token", t)),
                    turn_id=turn_id, should_cancel=cancel.is_set, tool_hint=tool_hint, semantic=semantic,
                )
                events.put(("done", payload))
            except TurnCancelled:
                events.put(("cancelled", None))
            except Exception as exc:  # noqa: BLE001 - reported as an SSE error event, never raised here
                events.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()
        finished = False

        try:
            while True:
                try:
                    kind, value = events.get(timeout=_HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ": keep-alive\n\n"  # a write to a closed connection ends this generator (see finally)
                    continue
                if kind == "step":
                    yield _sse("step", value)
                elif kind == "token":
                    yield _sse("token", {"text": value})
                elif kind == "done":
                    if not value.get("streamed"):
                        for chunk in _typewriter_chunks(value.get("content") or ""):
                            yield _sse("token", {"text": chunk})
                            time.sleep(_STREAM_CHUNK_DELAY_SECONDS)
                    finished = True
                    yield _sse("message", value)
                    return
                elif kind == "cancelled":
                    yield _sse("error", {"message": "That answer was stopped.", "code": "cancelled"})
                    return
                else:
                    finished = True  # nothing is saved for a failed turn anyway
                    friendly_message, _status, code = resolve_orchestrator_error(value)
                    yield _sse("error", {"message": friendly_message, "code": code})
                    return
        finally:
            # Normal end, or the page went away (Stop, closed tab): either way nothing more should run, and an
            # unfinished turn must not be saved - the tombstone covers a worker that is just about to write it.
            cancel.set()
            if not finished:
                history.cancel_turn(user_id, turn_id)
            _end_turn(user_id, turn_id, cancel)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx) so events arrive live
    return response


@app.route("/chat/cancel", methods=["POST"])
def chat_cancel():
    """Stop: {"turn_id"}. Ends that turn if it is still running here, removes it from the history if it was
    already saved, and leaves a tombstone so it is never saved later (a Worker may still be finishing it)."""
    user_id = get_user_id()
    turn_id = json_object().get("turn_id")
    if not isinstance(turn_id, str) or not _TURN_ID_RE.match(turn_id):
        raise ApiError("That turn id isn't valid.", 400, "invalid_field")
    with _active_lock:
        event = _active_turns.get((user_id, turn_id))
    if event is not None:
        event.set()
    history.cancel_turn(user_id, turn_id)
    return jsonify({"cancelled": True})


@app.route("/chat/history", methods=["GET"])
def chat_history():
    """Exactly what the model remembers of this browser's conversation, so the page can show it after a reload."""
    return jsonify({"messages": history.transcript(get_user_id())})


@app.route("/chat/rewind", methods=["POST"])
def chat_rewind():
    """Regenerate / Edit & resend: {"before_id": <message id>} forgets that message and everything after it."""
    before_id = json_object().get("before_id")
    if not isinstance(before_id, int) or isinstance(before_id, bool) or before_id < 0:
        raise ApiError("'before_id' must be a message id.", 400, "invalid_field")
    removed = history.rewind(get_user_id(), before_id)
    return jsonify({"removed": removed})


_FOLLOWUP_PROMPT = (
    "Suggest three short follow-up questions the user might ask next, based on the conversation below. "
    "Each under 70 characters, phrased as the user would type them, no numbering. "
    "Reply with only a JSON array of three strings."
)
_MAX_FOLLOWUP_CHARS = 90


def _parse_followups(text: str) -> list[str]:
    """Three suggestions from the model's reply: a JSON array if it sent one, else its non-empty lines."""
    text = (text or "").strip()
    items: list = []
    match = re.search(r"\[.*\]", text, re.S)
    if match:
        try:
            items = json.loads(match.group(0))
        except ValueError:
            items = []
    if not isinstance(items, list) or not items:
        items = [line for line in text.splitlines() if line.strip()]
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        clean = re.sub(r"^[\s\-*\d.)\"']+|[\s\"']+$", "", item).strip()
        if 3 <= len(clean) <= _MAX_FOLLOWUP_CHARS and clean not in out:
            out.append(clean)
    return out[:3]


@app.route("/chat/followups", methods=["POST"])
def chat_followups():
    """Three suggested next questions for the latest answer (one small model call, no tools)."""
    if not Config.FOLLOWUP_SUGGESTIONS:
        return jsonify({"suggestions": []})
    user_id = get_user_id()
    recent = history.get(user_id)[-4:]
    if not recent or recent[-1]["role"] != "assistant":
        return jsonify({"suggestions": []})
    resolver = request_provider_resolver()
    transcript = "\n\n".join(f"{m['role'].upper()}: {m['content'][:1500]}" for m in recent)
    try:
        result = resolver().chat([
            {"role": "system", "content": _FOLLOWUP_PROMPT},
            {"role": "user", "content": transcript},
        ])
    except Exception as exc:  # noqa: BLE001 - suggestions are optional; never an error the person has to see
        app.logger.info("Follow-up suggestions skipped (%s).", type(exc).__name__)
        return jsonify({"suggestions": []})
    return jsonify({"suggestions": _parse_followups(result.content or "")})


@app.route("/chat/reset", methods=["POST"])
def chat_reset():
    """Clears this user's short-term conversation (the recent turns the model
    sees as context) - the "New chat" action. Uploaded documents are
    untouched; delete those from the Documents panel."""
    if not request.is_json:
        return error_response("Requests to this endpoint must be JSON.", 415, "unsupported_media_type")
    history.reset(get_user_id())
    return jsonify({"cleared": True})


@app.route("/documents/upload", methods=["POST"])
def upload_document():
    user_id = get_user_id()
    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        raise ApiError("No file provided. Send multipart/form-data with a 'file' field.", 400, "no_file")

    # Read the real bytes rather than trusting any client-supplied size -
    # a forged Content-Length must not be able to bypass the limit. Read
    # one byte past the limit so an oversized file is detected without
    # loading the entire (potentially huge) file into memory.
    file_bytes = file_storage.stream.read(rag_pipeline.max_upload_bytes + 1)
    if len(file_bytes) > rag_pipeline.max_upload_bytes:
        max_mb = rag_pipeline.max_upload_bytes // (1024 * 1024)
        raise ApiError(f"File is too large - the limit is {max_mb} MB.", 413, "too_large")

    try:
        semantic = request_embedder()
        document, created = rag_pipeline.ingest_with_status(user_id, file_storage.filename, file_bytes, semantic=semantic)
        # Identical content is not indexed twice: the existing document comes
        # back (200, duplicate=true) instead of a new one (201).
        body = {"document": document.to_dict(), "duplicate": not created}
        if created and semantic is not None and not document.semantic_model:
            body["notice"] = "Indexed for keyword search only (meaning-based search wasn't available)."
        return jsonify(body), (201 if created else 200)
    except RAGIngestionError as exc:
        raise ApiError(str(exc), 400, "upload_rejected") from None
    except Exception:  # noqa: BLE001
        app.logger.exception("Document upload failed")
        raise ApiError("Could not process that file. Please try again.", 500, "upload_failed") from None


@app.route("/documents", methods=["GET"])
def list_documents():
    user_id = get_user_id()
    try:
        documents = rag_pipeline.list_documents(user_id)
        return jsonify({"documents": [d.to_dict() for d in documents]})
    except Exception:
        app.logger.exception("Could not list documents")
        return error_response("Could not load documents.", 500)


@app.route("/documents/<document_id>", methods=["DELETE"])
def delete_document(document_id):
    user_id = get_user_id()
    try:
        deleted = rag_pipeline.delete_document(user_id, document_id)
        return jsonify({"deleted": deleted}), (200 if deleted else 404)
    except Exception:
        app.logger.exception("Could not delete document %s", document_id)
        return error_response("Could not delete that document.", 500)


if __name__ == "__main__":
    if Config.FLASK_DEBUG:
        app.logger.warning(
            "FLASK_DEBUG is on: Werkzeug's interactive debugger allows code execution and shows tracebacks. "
            "Never enable it on a machine other people can reach."
        )
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.FLASK_DEBUG)
