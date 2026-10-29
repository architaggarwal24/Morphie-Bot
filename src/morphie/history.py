"""
Short-term conversation history.

Morphie-Bot keeps the last few turns of each browser's conversation in
memory so follow-up questions ("and what about 2025?") make sense. It is
deliberately simple: per-process, never written to disk, and cleared by the
"New chat" button or a server restart.

The window is bounded in two ways so a long-running server can't grow
without limit: each conversation keeps only the most recent
`max_messages`, and only the `max_users` most recently active
conversations are retained.

What the model remembers is exactly what the page shows: `transcript()` is the
same window `get()` hands the model, with ids, so the page can restore it after
a reload and the person can never be surprised by context they can't see.

Turns (a question and its answer) are written together, at the end, under a
client-chosen `turn_id`. That makes two corrections possible:

  cancel_turn(turn_id)   the person pressed Stop: the turn is dropped, and a
                         tombstone makes sure a turn that is still finishing
                         (in another thread or Worker isolate) is never written.
  rewind(before_id)      Regenerate / Edit & resend: forget a message and
                         everything after it.
"""

from __future__ import annotations

import itertools
import threading
from collections import OrderedDict, deque

MAX_TOMBSTONES_PER_USER = 50


class ConversationHistory:
    def __init__(self, max_messages: int = 20, max_users: int = 1000):
        self.max_messages = max(1, max_messages)
        self.max_users = max(1, max_users)
        self._conversations: "OrderedDict[str, list[dict]]" = OrderedDict()
        self._cancelled: "OrderedDict[str, deque]" = OrderedDict()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ---- what the model sees ----

    def get(self, user_id: str) -> list[dict]:
        """This user's recent messages, oldest first, as {"role", "content"}."""
        with self._lock:
            return [{"role": m["role"], "content": m["content"]} for m in self._conversations.get(user_id, [])]

    # ---- what the page shows ----

    def transcript(self, user_id: str) -> list[dict]:
        """The same window as get(), with each message's id and display metadata."""
        with self._lock:
            return [
                {"id": m["id"], "role": m["role"], "content": m["content"], "meta": dict(m.get("meta") or {})}
                for m in self._conversations.get(user_id, [])
            ]

    # ---- writing ----

    def append(self, user_id: str, role: str, content: str, *, turn_id: str | None = None, meta: dict | None = None) -> int:
        with self._lock:
            return self._append_locked(user_id, role, content, turn_id, meta)

    def append_turn(
        self, user_id: str, turn_id: str | None, user_text: str, assistant_text: str, meta: dict | None = None,
    ) -> tuple[int, int] | None:
        """Write a question and its answer together. Returns their ids, or None if the turn was cancelled."""
        with self._lock:
            if turn_id and turn_id in self._cancelled.get(user_id, ()):
                return None
            user_msg = self._append_locked(user_id, "user", user_text, turn_id, None)
            bot_msg = self._append_locked(user_id, "assistant", assistant_text, turn_id, meta)
            return user_msg, bot_msg

    def _append_locked(self, user_id: str, role: str, content: str, turn_id: str | None, meta: dict | None) -> int:
        message_id = next(self._ids)
        messages = self._conversations.setdefault(user_id, [])
        messages.append({"id": message_id, "role": role, "content": content, "turn_id": turn_id, "meta": meta or {}})
        del messages[: max(0, len(messages) - self.max_messages)]
        self._conversations.move_to_end(user_id)
        while len(self._conversations) > self.max_users:
            evicted, _ = self._conversations.popitem(last=False)
            self._cancelled.pop(evicted, None)
        return message_id

    # ---- corrections ----

    def is_cancelled(self, user_id: str, turn_id: str | None) -> bool:
        with self._lock:
            return bool(turn_id) and turn_id in self._cancelled.get(user_id, ())

    def cancel_turn(self, user_id: str, turn_id: str) -> None:
        with self._lock:
            self._cancelled.setdefault(user_id, deque(maxlen=MAX_TOMBSTONES_PER_USER)).append(turn_id)
            self._cancelled.move_to_end(user_id)
            while len(self._cancelled) > self.max_users:  # bounded even for clients that never keep a cookie
                self._cancelled.popitem(last=False)
            if user_id in self._conversations:
                self._conversations[user_id] = [m for m in self._conversations[user_id] if m.get("turn_id") != turn_id]

    def rewind(self, user_id: str, before_id: int) -> int:
        """Forget message `before_id` and everything after it. Returns how many messages were removed."""
        with self._lock:
            messages = self._conversations.get(user_id, [])
            keep = [m for m in messages if m["id"] < before_id]
            removed = len(messages) - len(keep)
            if user_id in self._conversations:
                self._conversations[user_id] = keep
            return removed

    def reset(self, user_id: str) -> None:
        with self._lock:
            self._conversations.pop(user_id, None)
