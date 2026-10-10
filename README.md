# Morphie-Bot

> A small, readable AI assistant you can run in five minutes: **chat**, **a basic tool-using agent**, and **document Q&A (RAG)**, built with Flask and plain JavaScript.

Morphie-Bot is the **parent project**. It stays deliberately small so the core ideas are easy to read end to end: how a model calls tools, how documents become searchable, how a chat UI shows an agent working. Its more ambitious descendant, **[Morphie](https://github.com/YOUR-USERNAME/morphie)**, takes the agent idea much further (see [Morphie-Bot → Morphie](#morphie-bot--morphie)).

## What it does

| | |
|---|---|
| 💬 **Chat** | Talk to Mistral, OpenAI, or a local Ollama model. Conversation context is kept for the session; **New chat** clears it. |
| 🛠️ **A bit of agentic AI** | The model decides for itself when to use a tool, reads the result, and carries on, up to a configurable cap per turn. Tools: **calculator**, **clock** (any city or timezone), **web search** (optional, via Tavily), and **document search**. |
| 📄 **Document Q&A (RAG)** | Upload PDF, Word, text, CSV or JSON files. Ask questions and get answers **with the source file named**. Everything is indexed locally, with no embedding API and no model download. |
| 👀 **Live steps** | A small progress line shows what the agent is doing ("🧮 Using the calculator ✓"), delivered over Server-Sent Events. |
| 🔒 **Careful by default** | CSRF protection, a strict Content-Security-Policy, rate limits, validated uploads, per-browser document isolation, and no tracebacks ever shown to users. |

**Deliberately not included** (they live in the child project): long-term memory, a design studio, in-app API-key management, many more providers, autonomous multi-step planning with approvals.

## Quick start

You need **Python 3.10 or newer** (developed and tested on 3.12) and an API key for one provider (or [Ollama](https://ollama.com) installed, which needs no key).

**macOS / Linux**
```bash
git clone https://github.com/YOUR-USERNAME/morphie-bot.git
cd morphie-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env (see below)
python src/app.py
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/YOUR-USERNAME/morphie-bot.git
cd morphie-bot
python -m venv .venv
.venv\Scripts\Activate.ps1     # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
copy .env.example .env         # then edit .env (see below)
python src/app.py
```

Open **http://127.0.0.1:5000**.

### Choosing your model

Edit `.env`:

```ini
# Mistral (default)
LLM_PROVIDER=mistral
MISTRAL_API_KEY=your_key_here

# or OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# or a local model, free and private (run `ollama pull llama3.1` first)
# LLM_PROVIDER=ollama
# LLM_MODEL=llama3.1
```

`LLM_MODEL` is optional; defaults are `mistral-large-latest`, `gpt-4o-mini` and `llama3.1`. The sidebar badge shows which provider/model is active and turns red if its key is missing. A greeting works even before you add a key.

> Not sure the agent is using a tool? Ask *"What's 18% of 74,500?"* (calculator), *"What time is it in Tokyo?"* (clock), or upload a file and ask about it.

## How it works

```
Browser (src/static/app.js)
   │  POST /chat/stream   ──►  live "step" events, then the answer
   ▼
Flask (src/app.py) ── CSRF check · rate limit · input validation
   ▼
MorphieOrchestrator (src/morphie/orchestrator.py)
   ├─ greeting? ───────────────► canned reply (no model call)
   └─ otherwise ───────────────► Agent loop (src/morphie/agent/orchestrator.py)
                                    │   model ⇄ tools, up to MAX_TOOL_CALLS rounds
                                    ├─ calculator · get_current_time · web_search
                                    └─ search_documents ──► RAG (src/morphie/rag/)
                                                              chunk → embed → SQLite → retrieve
   ▼
LLMProvider (src/morphie/providers/)  Mistral · OpenAI · Ollama
```

### The agent loop

1. The orchestrator sends the conversation plus the tool definitions to the model.
2. If the model replies with a **tool call**, the `ToolRouter` validates the arguments, runs the tool, and feeds the result back.
3. Repeat until the model answers in plain text, or `MAX_TOOL_CALLS` (default 5) is reached, at which point it is asked for a final answer without tools. This cap prevents runaway loops.

Tool output is treated as **untrusted data**: document and web results are labelled as such, and the system prompt tells the model never to follow instructions found inside them.

### Document search (RAG)

`upload → extract text → split into ~1000-character chunks (150 overlap) → hash-embed → store in SQLite → at question time, embed the query, rank chunks by cosine similarity, return the top matches with their source file`.

- Types: **PDF, DOCX, TXT, CSV, JSON**. Limits are configurable (default 20 MB per file).
- Each browser only ever sees its own documents; you can ask about *all* documents or only the ones you tick.
- The embedding is a dependency-free hashing embedding. It is fast and works offline, but is **lexical rather than truly semantic** (see [Limitations](#limitations)). The `EmbeddingProvider` interface makes swapping in a neural model straightforward.

### Add your own tool

A tool is a name, a description, a JSON schema for its arguments, and a Python function. Create `src/morphie/agent/tools/word_count.py`:

```python
from .base import Tool


def word_count(text: str) -> str:
    return str(len(text.split()))


word_count_tool = Tool(
    name="word_count",
    description="Count the words in a piece of text.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The text to count"}},
        "required": ["text"],
    },
    handler=word_count,
)
```

Then register it in `src/morphie/agent/tools/__init__.py`:

```python
from .word_count import word_count_tool

def get_default_tools() -> list[Tool]:
    return [calculator_tool, time_tool, web_search_tool, word_count_tool]
```

That's all: the router validates arguments, the agent loop calls it when the model asks, and the UI shows "🔧 Using word_count" automatically.

## Configuration

Everything is read from `.env` in one place (`src/config.py`); see [`.env.example`](.env.example) for the full, commented list. The ones you'll most likely touch:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `mistral` | `mistral`, `openai` or `ollama` |
| `LLM_MODEL` | provider default | Override the model |
| `MISTRAL_API_KEY` / `OPENAI_API_KEY` | – | Key for the provider you chose |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama listens |
| `TAVILY_API_KEY` | – | Enables real web search ([free key](https://tavily.com)) |
| `MAX_TOOL_CALLS` | `5` | Max tool rounds per turn |
| `MAX_CONTEXT_MESSAGES` | `20` | Recent messages sent as context |
| `RAG_MAX_UPLOAD_SIZE_MB` | `20` | Largest accepted upload |
| `FLASK_SECRET_KEY` | auto-generated | Signs the session cookie |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Bind address (localhost by default) |
| `FLASK_DEBUG` | `false` | Werkzeug debugger. **Never** enable on a reachable machine |

A malformed value (for example `MAX_TOOL_CALLS=abc`) fails at startup with a message naming the variable.

## HTTP API

| Method & path | Purpose |
|---|---|
| `GET /` | The chat UI |
| `GET /status` | `{provider, model, configured}`, used by the sidebar badge |
| `POST /chat` | `{message, document_ids?}` → `{content, tool_used, tool_calls, sources}` |
| `POST /chat/stream` | Same input and result as `/chat`, delivered as SSE: `step` → `token` → `message` (or `error`) |
| `POST /chat/reset` | Clear this browser's conversation ("New chat"); documents are kept |
| `POST /documents/upload` | Multipart `file` → `201` (or `200` with `duplicate: true`) |
| `GET /documents` | List your documents |
| `DELETE /documents/<id>` | Delete one |

Errors are always JSON `{error, code}` (chat errors also carry a user-ready `content`), never a stack trace.

## Project structure

```
src/app.py                  Flask app: routes, request guards, wiring
src/config.py               All settings, read from .env in one place
src/morphie/
  orchestrator.py           One entry point: greeting vs. agent
  history.py                Short-term, in-memory conversation history
  routing.py                Greeting detection
  security.py               Rate limiter · CSRF origin check
  agent/
    orchestrator.py         The tool-calling loop
    tool_router.py          Validates arguments, runs tools safely
    tools/                  calculator · clock · web search · document search
  providers/                LLMProvider interface · Mistral · OpenAI · Ollama · registry
                            + EmbeddingProvider (local hashing)
  rag/                      loaders · chunking · pipeline · SQLite vector store · retriever
src/templates/chatbot.html  The page
src/static/app.js, app.css  Vanilla JS and CSS, no build step, no framework
src/worker.py               Cloudflare Workers entry point (not used when running locally)
src/morphie/net.py          HTTP client: `requests` locally, fetch() on Workers
src/morphie/d1.py           D1-backed history and rate limiter (Workers only)
migrations/0001_init.sql    D1 schema
public/                     Generated by scripts/build_public.py; served by Cloudflare
wrangler.jsonc, pyproject.toml   Cloudflare Workers configuration
tests/                      pytest suite (fake providers, no API keys needed)
```

## Deploying to Cloudflare

Runs as a **Python Worker** (Flask via Cloudflare's WSGI support) with one **D1** database. The chat page and its
JS/CSS are served straight from Cloudflare's edge (`public/`).

```bash
python -m pip install uv                       # once
uv sync                                        # installs workers-py (pywrangler)
uv run pywrangler login
uv run pywrangler d1 create morphie-bot        # paste the printed database_id into wrangler.jsonc
uv run pywrangler secret put FLASK_SECRET_KEY  # any long random string; the only secret you must set
uv run pywrangler d1 migrations apply morphie-bot --remote
uv run pywrangler deploy
```

**Bring your own key.** The hosted app has no LLM provider or API key of its own. Each visitor opens the ⚙ badge in the
sidebar, picks Mistral or OpenAI, optionally a model, and pastes their own key. The key stays in their browser
(localStorage if "Remember on this device" is ticked, otherwise sessionStorage), is sent as an `X-LLM-Key` header with
each message, is used for that one request, and is never stored or logged by the Worker (it is also scrubbed from any
error text). Only providers with a fixed endpoint can be chosen; a custom base URL is intentionally not offered, since it
would let a visitor aim the server at arbitrary addresses. Ollama is available only when you run the app locally.
Running it yourself with a `.env` key still works: with no headers the server's own provider is used.

What differs on Cloudflare (same code, chosen automatically):
- **State lives in D1**: chat context, the document index and rate-limit counters (a Worker's memory is not shared or durable). Original uploaded files are not kept, only their extracted text chunks.
- **HTTP goes through `fetch()`** instead of `requests`, and the Mistral provider talks to Mistral's REST API directly instead of the `mistralai` SDK.
- **`/chat/stream` has no background thread** (Python Workers have none): the steps and reply are sent as the same SSE frames, but together once the answer is ready instead of live.
- **Settings are read per request** from the Worker's vars and secrets, not from `.env`. `OLLAMA_BASE_URL` must be a public HTTPS URL (a Worker cannot reach `localhost`).
- Python Workers do real CPU work (the interpreter runs as WebAssembly), so the **Workers Paid plan is recommended**. After editing `src/templates` or `src/static`, run `python scripts/build_public.py` and commit `public/`.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

**383 tests**, no API key or network required: the LLM is replaced by a scripted fake. They cover the agent loop, all three providers' request/response handling, the RAG pipeline end to end (including real generated PDFs and DOCX files), prompt-injection handling, the full HTTP layer (CSRF, CSP, rate limits, validation, one consistent error shape), the SSE stream, and a contract check that `chatbot.html`, `app.js` and the Flask routes agree with each other. GitHub Actions runs them on every push (`.github/workflows/ci.yml`).

## Security notes

- **Secrets stay server-side.** Keys live in `.env` (gitignored); nothing sensitive is sent to the browser. If `FLASK_SECRET_KEY` is unset, a random one is generated once into `data/` (gitignored), never a shared default.
- **No identity beyond a cookie.** There are no accounts: a signed, `HttpOnly`, `SameSite=Lax` cookie identifies a browser and scopes its documents. Don't expose this to untrusted users without adding real authentication.
- **Uploads are untrusted.** Extension allow-list, byte-counted size limits, file-signature checks, a decompression-bomb guard for DOCX, and a cap on chunks per document.
- **Content-Security-Policy** allows scripts only from this origin; the page has no inline JavaScript.
- Model/tool output is rendered as text, never as HTML.

## Limitations

Stated plainly, since this is a learning-sized project:

- **Streaming is partly simulated.** The *steps* (thinking, tool call, tool result) are live, but the reply text is a finished answer revealed progressively, not token-by-token from the provider.
- **Retrieval is lexical.** The offline hashing embedding matches on shared words more than on meaning, so paraphrased questions may miss relevant passages. Replace it with a neural embedding model for better recall.
- **Single process, in-memory state.** Conversation history and rate-limit counters live in memory, so they reset on restart and are not shared between workers. Run a single worker if you deploy it.
- **Web search needs a key** (`TAVILY_API_KEY`); without one the tool reports that it isn't configured.
- **No authentication**, as noted above.
- Built and tested with Python 3.12. The browser UI was verified against the real server in a simulated DOM (jsdom), not in each real browser, so glance at it in yours.

## Morphie-Bot → Morphie

Morphie-Bot is the foundation; **[Morphie](https://github.com/YOUR-USERNAME/morphie)** is the child project that grows its agent idea into a complete product, rebuilt in **Next.js + React + TypeScript** with the backend built in.

| | **Morphie-Bot** (this repo) | **Morphie** |
|---|---|---|
| Stack | Flask + vanilla JS | Next.js, React, TypeScript |
| Agent | Tool-calling loop, capped per turn | Autonomous plan → act → observe with a live step timeline, step limit, **approval prompts** for risky actions, loop guards, Stop |
| Tools | Calculator, clock, web search, document search | + web page reader, sandboxed workspace files, plan checklist, memory, design generation |
| Providers | Mistral, OpenAI, Ollama (set in `.env`) | 15+ built in plus a fully UI-configured **OpenAI-compatible** option (base URL, key, headers, auth style…) |
| Keys | `.env` | Entered in the UI, stored encrypted |
| Documents | Basic RAG (local index, cited sources) | Same local-index approach, with multi-file upload and use by the agent as a tool |
| Extras | – | Long-term memory, Design studio (HTML/React export), searchable chat history |

Start here to understand the fundamentals; move to Morphie for the complete experience.
