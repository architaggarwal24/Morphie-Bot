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
"""

from __future__ import annotations

import threading
from collections import OrderedDict


class ConversationHistory:
    def __init__(self, max_messages: int = 20, max_users: int = 1000):
        self.max_messages = max(1, max_messages)
        self.max_users = max(1, max_users)
        self._conversations: "OrderedDict[str, list[dict]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, user_id: str) -> list[dict]:
        """A copy of this user's recent messages, oldest first."""
        with self._lock:
            return [dict(message) for message in self._conversations.get(user_id, [])]

    def append(self, user_id: str, role: str, content: str) -> None:
        with self._lock:
            messages = self._conversations.setdefault(user_id, [])
            messages.append({"role": role, "content": content})
            del messages[: max(0, len(messages) - self.max_messages)]
            self._conversations.move_to_end(user_id)
            while len(self._conversations) > self.max_users:
                self._conversations.popitem(last=False)

    def reset(self, user_id: str) -> None:
        with self._lock:
            self._conversations.pop(user_id, None)
