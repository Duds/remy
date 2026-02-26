"""
Per-user session management.
Provides asyncio locks (to serialize message processing) and cancel events.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Validate session keys to prevent path traversal
_SESSION_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_session_key(key: str) -> bool:
    return bool(key) and len(key) <= 64 and bool(_SESSION_KEY_RE.match(key))


class SessionManager:
    """Thread-safe, per-user state manager for the Telegram bot."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._cancel_events: dict[int, asyncio.Event] = {}

    def get_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def request_cancel(self, user_id: int) -> None:
        """Signal that the user wants to cancel their in-progress task."""
        event = self._cancel_events.setdefault(user_id, asyncio.Event())
        event.set()
        logger.info("Cancel requested for user %d", user_id)

    def clear_cancel(self, user_id: int) -> None:
        """Clear the cancel signal (called at the start of each new task)."""
        if user_id in self._cancel_events:
            self._cancel_events[user_id].clear()

    def is_cancelled(self, user_id: int) -> bool:
        """Return True if the user has requested cancellation."""
        event = self._cancel_events.get(user_id)
        return event is not None and event.is_set()

    @staticmethod
    def get_session_key(user_id: int) -> str:
        """Return a daily session key: user_<id>_<YYYYMMDD>."""
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"user_{user_id}_{date}"
