import json
import queue
import re
import threading
import time
import uuid
from datetime import timedelta

from flask import Flask, Response, request, render_template, jsonify, session, stream_with_context
from werkzeug.exceptions import HTTPException

from config import Config
from morphie.agent.orchestrator import AgentOrchestrator
from morphie.agent.tool_router import ToolRouter
from morphie.history import ConversationHistory
from morphie.orchestrator import MorphieOrchestrator
from morphie.providers.base import LLMProvider, ProviderError, ProviderNotConfiguredError
from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.providers.registry import registry
from morphie.rag.pipeline import RAGIngestionError, RAGPipeline
from morphie.rag.vector_store import LocalVectorStore
from morphie.security import RateLimiter, is_trusted_origin

app = Flask(__name__)
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
# JSON endpoints carry short messages; only the upload route needs a large body.
MAX_JSON_BODY_BYTES = 256 * 1024


# ---- The LLM provider -------------------------------------------------------
# One provider, chosen in .env (LLM_PROVIDER=mistral|openai|ollama). Everything
# downstream talks to the LLMProvider interface, never to a vendor SDK directly.

_PROVIDER_API_KEYS = {"mistral": Config.MISTRAL_API_KEY, "openai": Config.OPENAI_API_KEY, "ollama": None}
_PROVIDER_KEY_ENV = {"mistral": "MISTRAL_API_KEY", "openai": "OPENAI_API_KEY"}


def build_provider() -> LLMProvider:
    kwargs = {"base_url": Config.OLLAMA_BASE_URL} if Config.LLM_PROVIDER == "ollama" else {}
    return registry.get(
        Config.LLM_PROVIDER, api_key=_PROVIDER_API_KEYS[Config.LLM_PROVIDER], model=Config.LLM_MODEL, **kwargs,
    )


provider = build_provider()

# ---- The agent, short-term history, and document RAG ------------------------

tool_router = ToolRouter()
agent = AgentOrchestrator(provider, tool_router, max_tool_calls=Config.MAX_TOOL_CALLS)
history = ConversationHistory(max_messages=Config.MAX_CONTEXT_MESSAGES)

# Document RAG with a dependency-free, offline embedding - works with zero extra setup.
rag_pipeline = RAGPipeline(
    embedding_provider=LocalEmbeddingProvider(dim=Config.RAG_LOCAL_EMBEDDING_DIM),
    vector_store=LocalVectorStore(db_path=Config.RAG_VECTOR_STORE_PATH),
    upload_dir=Config.RAG_UPLOAD_DIR,
    max_upload_size_mb=Config.RAG_MAX_UPLOAD_SIZE_MB,
    chunk_size=Config.RAG_CHUNK_SIZE,
    chunk_overlap=Config.RAG_CHUNK_OVERLAP,
    top_k=Config.RAG_TOP_K,
    min_score=Config.RAG_MIN_SCORE,
    max_chunks_per_document=Config.RAG_MAX_CHUNKS_PER_DOCUMENT,
)


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
    """The provider to use for this turn, or a friendly 'how to fix it' error."""
    if not provider.is_configured():
        key_env = _PROVIDER_KEY_ENV.get(Config.LLM_PROVIDER)
        hint = f"Set {key_env} in your .env file and restart." if key_env else "Check your .env file and restart."
        raise ProviderNotConfiguredError(
            f"{provider_display_name()} is not configured. {hint}", provider=provider_display_name(),
        )
    return provider


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

def _build_limiters(chat_per_minute: int, upload_per_minute: int, enabled: bool = True) -> dict:
    """(per-user, per-IP) limiters for the endpoints that cost money or CPU.
    The per-IP cap is looser (5x) so one shared address isn't punished for
    several users, while still bounding someone who keeps discarding cookies."""
    def pair(limit: int):
        limit = limit if enabled else 0
        return RateLimiter(limit, 60.0), RateLimiter(limit * 5, 60.0)
    return {"/chat": pair(chat_per_minute), "/documents/upload": pair(upload_per_minute)}


# /chat/stream costs exactly what /chat costs (one model call); without this
# alias a client could double its effective rate by alternating endpoints.
_RATE_LIMIT_ALIASES = {"/chat/stream": "/chat"}

_rate_limiters = _build_limiters(
    Config.RATE_LIMIT_CHAT_PER_MINUTE, Config.RATE_LIMIT_UPLOAD_PER_MINUTE, Config.RATE_LIMIT_ENABLED,
)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.before_request
def guard_request():
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
            for limiter, key in ((user_limiter, identity), (ip_limiter, request.remote_addr or "?")):
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
    # Scripts may only load from this origin: the UI is one static JS file with
    # no inline <script>, inline handlers, eval, or CDN (tests/test_app_security.py
    # guards that, since a violation would be silently blocked by browsers).
    # No 'unsafe-inline' for scripts, so an injected <script> or onclick= cannot
    # run even if escaping ever failed. Styles are deliberately not restricted:
    # the shell uses a few inline style attributes.
    response.headers.setdefault(
        "Content-Security-Policy",
        "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
    )
    if response.mimetype == "application/json":
        response.headers["Cache-Control"] = "no-store"  # personal data: documents
    return response


# ---- Input validation ----

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_DOCUMENT_IDS = 100


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
    return render_template("chatbot.html")


@app.route("/status", methods=["GET"])
def status():
    """Which provider/model answers, and whether it is ready - so the UI can
    show a clear 'add your key' hint instead of failing on the first message."""
    return jsonify({
        "provider": provider_display_name(),
        "model": provider.model,
        "configured": provider.is_configured(),
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


@app.route("/chat", methods=["POST"])
def chat():
    """One user message -> one reply. Body: {"message": str, "document_ids": [str] | null}.
    For live progress (tool calls) as the reply is produced, use POST /chat/stream
    instead - the two share validation and return the same JSON."""
    user_id = get_user_id()
    body = json_object()
    message = _validate_chat_input(body)

    try:
        payload = _orchestrator().handle_chat(
            user_id=user_id, text=message,
            document_ids=clean_document_ids(body.get("document_ids")),
            provider=resolve_provider,
        )
        return jsonify(payload)
    except Exception as exc:  # noqa: BLE001 - every case is mapped to a safe message below
        friendly_message, status, code = resolve_orchestrator_error(exc)
        return error_response(friendly_message, status, code)


_STREAM_CHUNK_WORDS = 3
_STREAM_CHUNK_DELAY_SECONDS = 0.02


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _typewriter_chunks(text: str):
    """`text` split into a few-word pieces that, concatenated, reproduce it
    exactly (whitespace included). Used to reveal a finished reply
    progressively - see chat_stream()'s docstring for what this is and
    is not."""
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
    blank wait. Three kinds of frame, in order:

      event: step     {"type": "thinking" | "tool_call" | "tool_result", ...}
                       - emitted the instant each one actually happens (see
                       MorphieOrchestrator.handle_chat's on_step).
      event: token     {"text": "..."}  - the finished reply's `content`,
                       revealed a few words at a time.
      event: message   the exact JSON body POST /chat would return for the
                       same input - always sent exactly once, last.
      event: error     {"message", "code"} in place of `message` if the
                       turn failed (see resolve_orchestrator_error).

    "Streaming" here means the *steps* are genuinely live; the reply text
    itself is a finished response revealed progressively (a typewriter
    effect), not per-token network streaming from the AI provider - see
    README: Known limitations.

    Input is validated up front exactly like /chat (shares
    _validate_chat_input), so bad input still gets a normal 4xx/413 JSON
    response before any stream starts. Once streaming has begun, HTTP
    status is fixed at 200 (headers are already sent as text/event-stream),
    so a failure becomes an `error` event rather than a different status.
    """
    user_id = get_user_id()
    body = json_object()
    message = _validate_chat_input(body)
    document_ids = clean_document_ids(body.get("document_ids"))

    def generate():
        events: "queue.Queue[tuple[str, object]]" = queue.Queue()

        def on_step(event: dict) -> None:
            events.put(("step", event))

        def worker() -> None:
            try:
                payload = _orchestrator().handle_chat(
                    user_id=user_id, text=message, document_ids=document_ids,
                    provider=resolve_provider, on_step=on_step,
                )
                events.put(("done", payload))
            except Exception as exc:  # noqa: BLE001 - reported as an SSE error event, never raised here
                events.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            kind, value = events.get()
            if kind == "step":
                yield _sse("step", value)
            elif kind == "done":
                for chunk in _typewriter_chunks(value.get("content") or ""):
                    yield _sse("token", {"text": chunk})
                    time.sleep(_STREAM_CHUNK_DELAY_SECONDS)
                yield _sse("message", value)
                return
            else:
                friendly_message, _status, code = resolve_orchestrator_error(value)
                yield _sse("error", {"message": friendly_message, "code": code})
                return

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx) so events arrive live
    return response


@app.route("/chat/reset", methods=["POST"])
def chat_reset():
    """Clears this user's short-term conversation (the recent turns the model
    sees as context) - the "New chat" action. Uploaded documents are
    untouched; delete those from the Documents panel."""
    if not request.is_json:
        return error_response("Requests to this endpoint must be JSON.", 415, "unsupported_media_type")
    history.reset(get_user_id())
    return jsonify({"cleared": True})


# ---- Document RAG API ----

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
        document, created = rag_pipeline.ingest_with_status(user_id, file_storage.filename, file_bytes)
        # Identical content is not indexed twice: the existing document comes
        # back (200, duplicate=true) instead of a new one (201).
        return jsonify({"document": document.to_dict(), "duplicate": not created}), (201 if created else 200)
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
