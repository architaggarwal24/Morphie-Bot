"""Cloudflare D1 access for a synchronous Flask app, plus the three small stores that live in it.

D1 is Cloudflare's SQLite database. From a Python Worker it is reached through an async JavaScript binding, so
`D1` wraps it with synchronous `query / execute / batch` using `pyodide.ffi.run_sync`. The three hooks
(`run_sync`, `to_python`, `to_js`, `null`) are injectable so the same code is unit-tested against a fake binding
backed by sqlite3 (tests/test_d1.py).

Stores built on it (each has the same interface as its in-memory/local twin, so the rest of the app is unchanged):

  D1ConversationHistory  morphie.history.ConversationHistory   (per-browser chat context)
  D1RateLimiter          morphie.security.RateLimiter          (fixed-window counters)
  D1VectorStore          morphie.rag.vector_store.LocalVectorStore (see rag/d1_store.py)

The schema lives in migrations/0001_init.sql (applied with `pywrangler d1 migrations apply`).
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Callable, Iterable

_UNSET = object()


class D1:
    def __init__(
        self,
        binding: Any,
        *,
        run_sync: Callable[[Any], Any] | None = None,
        to_python: Callable[[Any], Any] | None = None,
        to_js: Callable[[Any], Any] | None = None,
        null: Any = _UNSET,
    ):
        self._binding = binding
        if run_sync is None:
            from pyodide.ffi import run_sync as _run_sync  # noqa: PLC0415 - only inside Pyodide
            run_sync = _run_sync
        if to_python is None:
            import js  # noqa: PLC0415

            def to_python(value):  # JSON round-trip: unambiguous, no dict-converter subtleties
                return json.loads(js.JSON.stringify(value))
        if to_js is None:
            from pyodide.ffi import to_js as _to_js  # noqa: PLC0415
            to_js = _to_js
        if null is _UNSET:
            import js  # noqa: PLC0415
            null = js.null
        self._run = run_sync
        self._to_python = to_python
        self._to_js = to_js
        self._null = null

    def _prepare(self, sql: str, params: Iterable[Any] = ()):
        statement = self._binding.prepare(sql)
        values = [self._null if p is None else p for p in params]
        return statement.bind(*values) if values else statement

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        result = self._to_python(self._run(self._prepare(sql, params).all()))
        return list(result.get("results") or [])

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run one statement; returns the number of rows changed."""
        result = self._to_python(self._run(self._prepare(sql, params).run()))
        return int((result.get("meta") or {}).get("changes") or 0)

    def batch(self, statements: list[tuple[str, Iterable[Any]]]) -> None:
        """Several statements in one round trip, applied atomically."""
        if not statements:
            return
        prepared = [self._prepare(sql, params) for sql, params in statements]
        self._run(self._binding.batch(self._to_js(prepared)))


# --------------------------------------------------------------------------- #
# Conversation history
# --------------------------------------------------------------------------- #

class D1ConversationHistory:
    """Short-term chat context, kept in D1 because a Worker has no memory that outlives a request.

    Same interface as morphie.history.ConversationHistory. Each browser keeps its newest `max_messages`;
    rows older than `ttl_days` are swept occasionally so abandoned sessions don't pile up.
    """

    def __init__(self, db: D1, max_messages: int = 20, ttl_days: int = 30, sweep_probability: float = 0.02):
        self.db = db
        self.max_messages = max(1, max_messages)
        self.ttl_seconds = max(1, ttl_days) * 86400
        self.sweep_probability = sweep_probability

    def get(self, user_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT role, content FROM ("
            "  SELECT id, role, content FROM conversation_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (user_id, self.max_messages),
        )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def append(self, user_id: str, role: str, content: str) -> None:
        statements: list[tuple[str, Iterable[Any]]] = [
            (
                "INSERT INTO conversation_messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (user_id, role, content, int(time.time())),
            ),
            (
                "DELETE FROM conversation_messages WHERE user_id = ? AND id <= ("
                "  SELECT id FROM conversation_messages WHERE user_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
                (user_id, user_id, self.max_messages),
            ),
        ]
        if random.random() < self.sweep_probability:
            statements.append(("DELETE FROM conversation_messages WHERE created_at < ?", (int(time.time()) - self.ttl_seconds,)))
        self.db.batch(statements)

    def reset(self, user_id: str) -> None:
        self.db.execute("DELETE FROM conversation_messages WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #

class D1RateLimiter:
    """At most `limit` events per `window_seconds` per key, shared by every isolate (fixed window).

    One upsert per check. Same interface as morphie.security.RateLimiter: check(key) -> (allowed, retry_after).
    `limit <= 0` disables it. A fixed window is coarser than the in-memory sliding window (a burst straddling a
    window boundary can briefly reach 2x), which is fine for protecting a paid LLM endpoint.
    """

    def __init__(self, db: D1, scope: str, limit: int, window_seconds: float = 60.0, clock=time.time, sweep_probability: float = 0.01):
        self.db = db
        self.scope = scope
        self.limit = int(limit)
        self.window = max(1, int(window_seconds))
        self._clock = clock
        self.sweep_probability = sweep_probability

    def check(self, key: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0
        now = self._clock()
        window = int(now // self.window)
        rows = self.db.query(
            "INSERT INTO rate_buckets (bucket, window, n) VALUES (?, ?, 1) "
            "ON CONFLICT(bucket, window) DO UPDATE SET n = n + 1 RETURNING n",
            (f"{self.scope}:{key}", window),
        )
        count = int(rows[0]["n"]) if rows else 1
        if random.random() < self.sweep_probability:
            self.db.execute("DELETE FROM rate_buckets WHERE window < ?", (window - 5,))
        if count > self.limit:
            return False, max(1, int((window + 1) * self.window - now))
        return True, 0
