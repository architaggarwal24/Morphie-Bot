"""Where is this code running?

Morphie-Bot runs in two places with the same source:

  * locally / on any server: normal CPython, `python src/app.py` (or gunicorn). Threads, files and the
    `requests` library all work, and state lives in a SQLite file.
  * on Cloudflare Workers (Python Workers): CPython compiled to WebAssembly (Pyodide) inside a V8 isolate.
    There are no threads, no writable disk that outlives a request, and no raw sockets, so HTTP goes through
    the platform's `fetch`, and state lives in D1 (Cloudflare's SQLite database).

Everything that has to behave differently asks `IS_WORKERS` here, so the rest of the code stays ordinary Python.
"""

import sys

IS_WORKERS = sys.platform == "emscripten"
