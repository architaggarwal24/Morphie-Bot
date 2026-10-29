# Morphie-Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-8b5cf6.svg)](LICENSE)

> A small, readable AI assistant you can run in five minutes: **chat**, **a basic tool-using agent**, and **document Q&A (RAG)**, built with Flask and a React + Motion web UI.

Morphie-Bot is the **parent project**. It stays deliberately small so the core ideas are easy to read end to end: how a model calls tools, how documents become searchable, how a chat UI shows an agent working. Its more ambitious descendant, **[Morphie](https://github.com/architaggarwal24/morphie)**, takes the agent idea much further (see [Morphie-Bot → Morphie](#morphie-bot--morphie)).

## What it does

| | |
|---|---|
| 💬 **Chat** | Talk to Mistral, OpenAI, a local Ollama model, or an OpenAI-compatible service (Groq, OpenRouter, Together AI, DeepSeek). Answers **stream in word by word** straight from the provider. The conversation survives a page reload (the page shows exactly what the model remembers); **New chat** clears it. |
| ✏️ **Steer the conversation** | **Stop** really stops (the server drops the half answer, so it never haunts the next question), **Regenerate** an answer, **Edit & resend** a question, pick a **suggested follow-up**, and **export** the chat as Markdown, to the clipboard, or as a PDF. |
| 🛠️ **A bit of agentic AI** | The model decides for itself when to use a tool, reads the result, and carries on, up to a configurable cap per turn. Tools: **calculator**, **clock** (any city or timezone), **web search** (optional, via Tavily), and **document search**. Type **`/calc`, `/time`, `/web` or `/docs`** to make it use one. |
| 📄 **Document Q&A (RAG)** | Upload PDF, Word, text, CSV or JSON files (several at once, with progress). Answers cite their sources as **[1]**, **[2]**: click one to see the exact passage. Search is **hybrid**: keyword matching that works offline, plus **meaning-based search** with your provider's embeddings (OpenAI, Mistral, Ollama). Type **`@file`** to ask about one document. |
| 👀 **Live steps** | An animated timeline shows what the agent is doing; expand a step to see its input, output, timing and (for web search) the result links. Delivered over Server-Sent Events. |
| 🔒 **Careful by default** | CSRF protection, a strict Content-Security-Policy, rate limits, validated uploads, per-browser document isolation, and no tracebacks ever shown to users. |

**Deliberately not included** (they live in the child project): a list of saved conversations, long-term memory, a design studio, encrypted key storage, autonomous multi-step planning with approvals.

## Quick start

You need **Python 3.10 or newer** (developed and tested on 3.12) and an API key for one provider (or [Ollama](https://ollama.com) installed, which needs no key).

**macOS / Linux**
```bash
git clone https://github.com/architaggarwal24/morphie-bot.git
cd morphie-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env          # then edit .env (see below)
python src/app.py
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/architaggarwal24/morphie-bot.git
cd morphie-bot
python -m venv .venv
.venv\Scripts\Activate.ps1     # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements-local.txt
copy .env.example .env         # then edit .env (see below)
python src/app.py
```

Open **http://127.0.0.1:5000**. The built web UI is committed in `public/`, so Node is only needed if you change it (see [Working on the web UI](#working-on-the-web-ui)).

### Upgrading an existing Cloudflare deployment to v2

One new D1 migration adds the columns v2 needs (turn ids, Stop tombstones, meaning-based search). Apply it, then deploy:

```bash
uv run pywrangler d1 migrations apply morphie-bot --remote
uv run pywrangler deploy
```

No new secrets or vars are required. Optional vars: `FOLLOWUP_SUGGESTIONS`, `RAG_SEMANTIC_SEARCH` (both default `true`).

### Working on the web UI

The UI lives in `web/` (Vite · React · TypeScript · Tailwind CSS v4 · Motion · Lucide icons) and builds into `public/`, which Flask serves locally and Cloudflare serves at the edge. You need **Node 20+**.

```bash
cd web
npm install
npm run dev       # http://localhost:5173 with hot reload; API calls are proxied to Flask on :5000 (run python src/app.py too)
npm test          # Vitest + Testing Library
npm run build     # type-check, then write the production build to ../public  (or: python scripts/build_public.py)
```

Commit `public/` after a build. The page keeps the strict CSP (`script-src 'self'`): no inline scripts, no CDNs, fonts are self-hosted.

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
Browser (web/ → built into public/)
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
| `ALLOW_CUSTOM_LLM_URL` | `false` | Offer "Custom URL" in Settings (LM Studio, vLLM, llama.cpp...). Only for a deployment you alone use: it lets visitors make the server call an address they type |
| `RAG_SEMANTIC_SEARCH` | `true` | Also index documents by meaning with the answering provider's embeddings; `false` = keywords only |
| `FOLLOWUP_SUGGESTIONS` | `true` | Suggest three follow-up questions after each answer (one small extra model call) |
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
| `GET /providers` | What Settings can offer (and whether follow-ups are on) |
| `POST /chat` | `{message, document_ids?, turn_id?, tool?}` → `{content, tool_used, tool_calls, sources, turn}` |
| `POST /chat/stream` | Same input and result as `/chat`, delivered as SSE: `step` → `token` → `message` (or `error`) |
| `GET /chat/history` | What the model remembers of this browser's conversation, with message ids |
| `POST /chat/cancel` | `{turn_id}`: Stop. Ends the turn and makes sure it is never saved |
| `POST /chat/rewind` | `{before_id}`: forget that message and everything after it (Regenerate, Edit & resend) |
| `POST /chat/followups` | Three suggested next questions for the latest answer |
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
web/                        The web UI (React + Vite); `npm run build` writes public/
  src/App.tsx               Shell: sidebar, chat, documents panel, dialogs, shortcuts
  src/hooks/                useChat (SSE stream) · useDocuments · useStatus · useTheme · useShortcuts
  src/components/           chat/ · docs/ · dialogs/ · layout/ · fx/ (aurora, orb, magnetic…) · ui/
  src/lib/                  api (fetch + SSE) · llm (bring your own key) · shortcuts · tools
  src/test/                 Vitest tests
src/worker.py               Cloudflare Workers entry point (not used when running locally)
src/morphie/net.py          HTTP client: `requests` locally, fetch() on Workers
src/morphie/d1.py           D1-backed history and rate limiter (Workers only)
migrations/0001_init.sql    D1 schema
public/                     The built web UI (committed); served by Flask locally and by Cloudflare
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
sidebar, picks a provider (Mistral, OpenAI, Groq, OpenRouter, Together AI, DeepSeek), optionally a model, and pastes their own key. The key stays in their browser
(localStorage if "Remember on this device" is ticked, otherwise sessionStorage), is sent as an `X-LLM-Key` header with
each message, is used for that one request, and is never stored or logged by the Worker (it is also scrubbed from any
error text). Only providers with a fixed endpoint can be chosen; "Custom URL" stays off unless you set
`ALLOW_CUSTOM_LLM_URL=true`, since it would let a visitor aim the server at arbitrary addresses (even then, cloud
metadata addresses and redirects are refused). Ollama is available only when you run the app locally.
Running it yourself with a `.env` key still works: with no headers the server's own provider is used.

What differs on Cloudflare (same code, chosen automatically):
- **State lives in D1**: chat context, the document index and rate-limit counters (a Worker's memory is not shared or durable). Original uploaded files are not kept, only their extracted text chunks.
- **HTTP goes through `fetch()`** instead of `requests`, and the Mistral provider talks to Mistral's REST API directly instead of the `mistralai` SDK.
- **`/chat/stream` has no background thread** (Python Workers have none) and the WSGI adapter sends a response whole: the steps and reply are the same SSE frames, but they arrive together once the answer is ready instead of word by word. Stop still works: it leaves a tombstone in D1, the running turn checks it before every model and tool call, and the stopped turn is never saved.
- **Meaning-based search** makes one embedding call per 32 chunks at upload. A very large document can exceed the Workers Free plan's 50 outgoing requests per invocation; it is then indexed for keyword search only (the upload says so).
- **Settings are read per request** from the Worker's vars and secrets, not from `.env`. `OLLAMA_BASE_URL` must be a public HTTPS URL (a Worker cannot reach `localhost`).
- Python Workers do real CPU work (the interpreter runs as WebAssembly), so the **Workers Paid plan is recommended**. After editing `web/`, run `npm --prefix web run build` (or `python scripts/build_public.py`) and commit `public/`.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
cd web && npm test     # the web UI
```

**516 Python tests** (plus 51 Vitest tests for the web UI), no API key or network required: the LLM is replaced by a scripted fake. They cover the agent loop, all three providers' request/response handling, the RAG pipeline end to end (including real generated PDFs and DOCX files), prompt-injection handling, the full HTTP layer (CSRF, CSP, rate limits, validation, one consistent error shape), the SSE stream, and contract checks that the web UI and the Flask routes agree with each other. The web UI has its own Vitest suite (`web/src/test`): SSE parsing and streaming, the bring-your-own-key rules (the key travels only in headers, is never rendered or logged), optimistic delete with Undo and rollback, the 300 ms skeleton delay, and keyboard access to the command menu and shortcuts. GitHub Actions runs them on every push (`.github/workflows/ci.yml`).

## Security notes

- **Secrets stay server-side.** Keys live in `.env` (gitignored); nothing sensitive is sent to the browser. If `FLASK_SECRET_KEY` is unset, a random one is generated once into `data/` (gitignored), never a shared default.
- **No identity beyond a cookie.** There are no accounts: a signed, `HttpOnly`, `SameSite=Lax` cookie identifies a browser and scopes its documents. Don't expose this to untrusted users without adding real authentication.
- **Uploads are untrusted.** Extension allow-list, byte-counted size limits, file-signature checks, a decompression-bomb guard for DOCX, and a cap on chunks per document.
- **Content-Security-Policy** allows scripts only from this origin; the page has no inline JavaScript.
- Model/tool output is rendered as text, never as HTML.

## Limitations

Stated plainly, since this is a learning-sized project:

- **Streaming on Cloudflare is not live.** Locally the reply streams token by token from the provider; on Workers the frames arrive together when the answer is ready (see Deploying to Cloudflare).
- **Meaning-based search needs embeddings.** Documents uploaded while using a provider without an embeddings API (Groq, OpenRouter, Together AI, DeepSeek, Custom URL) are searched by keywords only, and a document is only compared by meaning with the model it was indexed with. Re-upload it to re-index.
- **Single process, in-memory state.** Locally, conversation history and rate-limit counters live in memory, so they reset on restart and are not shared between workers. Run a single worker if you deploy it.
- **One conversation per browser.** There is no list of saved chats (that lives in the child project, Morphie).
- **Web search needs a key** (`TAVILY_API_KEY`); without one the tool reports that it isn't configured.
- **No authentication**, as noted above.
- Built and tested with Python 3.12. The browser UI was verified against the real server in a simulated DOM (jsdom), not in each real browser, so glance at it in yours.

## Morphie-Bot → Morphie

Morphie-Bot is the foundation; **[Morphie](https://github.com/architaggarwal24/morphie)** is the child project that grows its agent idea into a complete product, rebuilt in **Next.js + React + TypeScript** with the backend built in.

| | **Morphie-Bot** (this repo) | **Morphie** |
|---|---|---|
| Stack | Flask + a React/Vite UI | Next.js, React, TypeScript |
| Agent | Tool-calling loop, capped per turn | Autonomous plan → act → observe with a live step timeline, step limit, **approval prompts** for risky actions, loop guards, Stop |
| Tools | Calculator, clock, web search, document search | + web page reader, sandboxed workspace files, plan checklist, memory, design generation |
| Providers | Mistral, OpenAI, Ollama + 4 OpenAI-compatible presets (bring your own key) | 15+ built in plus a fully UI-configured **OpenAI-compatible** option (base URL, key, headers, auth style…) |
| Keys | `.env`, or each visitor's own key kept in their browser | Entered in the UI, stored encrypted |
| Documents | Hybrid keyword + meaning search, multi-file upload, clickable [n] citations | Same local-index approach, with multi-file upload and use by the agent as a tool |
| Extras | – | Long-term memory, Design studio (HTML/React export), searchable chat history |

Start here to understand the fundamentals; move to Morphie for the complete experience.

## License

[MIT](LICENSE) © 2026 Archit Aggarwal. Use it, change it, ship it; keep the copyright and license notice.
