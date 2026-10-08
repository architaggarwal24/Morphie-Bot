"""
Small, dependency-free security primitives used by the Flask layer.

  RateLimiter          sliding-window limiter with bounded memory
  is_trusted_origin    CSRF defence: reject cross-site browser requests

They are deliberately framework-agnostic (plain headers / plain strings)
so they can be unit-tested without a Flask app.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from urllib.parse import urlsplit

# --------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------- #


class RateLimiter:
    """At most `limit` events per `window_seconds` per key.

    In-memory and per-process: enough to stop a runaway client or a
    script hammering an LLM-backed endpoint (which costs real money), not
    a distributed-abuse defence. Memory is bounded: once `max_keys`
    distinct keys are tracked, the least recently seen one is dropped.
    A `limit` of 0 (or less) disables limiting.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 10_000, clock=time.monotonic):
        self.limit = int(limit)
        self.window = float(window_seconds)
        self.max_keys = max(1, int(max_keys))
        self._clock = clock
        self._events: "OrderedDict[str, deque]" = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, retry_after_seconds)."""
        if self.limit <= 0:
            return True, 0
        now = self._clock()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                events = self._events[key] = deque()
                while len(self._events) > self.max_keys:
                    self._events.popitem(last=False)
            else:
                self._events.move_to_end(key)
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False, max(1, math.ceil(events[0] + self.window - now))
            events.append(now)
            return True, 0

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._events)


# --------------------------------------------------------------------- #
# CSRF: origin checking
# --------------------------------------------------------------------- #


def is_trusted_origin(headers, host: str, trusted=()) -> bool:
    """Should this (state-changing) request be accepted?

    Browsers attach `Origin` (and `Sec-Fetch-Site`) to cross-site POSTs and
    users' scripts cannot forge them, so a mismatch means another website
    is driving the user's browser. Requests with neither header (curl,
    server-to-server, tests) are allowed: CSRF is a browser-only attack.
    """
    h = {str(k).lower(): v for k, v in headers.items()}
    allowed = {t.rstrip("/").lower() for t in trusted if t}
    origin = h.get("origin")
    if origin is not None:
        origin = str(origin).strip()
        if origin.rstrip("/").lower() in allowed:
            return True
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False  # "null" (sandboxed/opaque origins) or garbage
        return parts.netloc.lower() == str(host).lower()
    return str(h.get("sec-fetch-site", "")).lower() not in ("cross-site", "same-site")
