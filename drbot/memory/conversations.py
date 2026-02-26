"""
JSONL-backed conversation session store.
Each user's daily session is an append-only .jsonl file.
Crash-safe: each turn is a single JSON line, never buffered.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import aiofiles

from ..bot.session import validate_session_key
from ..models import ConversationTurn

logger = logging.getLogger(__name__)


class ConversationStore:
    """Manages per-user JSONL session files."""

    def __init__(self, sessions_dir: str) -> None:
        self.sessions_dir = sessions_dir
        os.makedirs(sessions_dir, exist_ok=True)
        # Per-session-file locks to prevent concurrent writes to same file
        self._file_locks: dict[str, asyncio.Lock] = {}

    def _file_lock(self, session_key: str) -> asyncio.Lock:
        if session_key not in self._file_locks:
            self._file_locks[session_key] = asyncio.Lock()
        return self._file_locks[session_key]

    def _path(self, user_id: int, session_key: str) -> Optional[str]:
        if not validate_session_key(session_key):
            logger.error("Invalid session key: %r", session_key)
            return None
        return os.path.join(self.sessions_dir, f"{session_key}.jsonl")

    async def append_turn(
        self, user_id: int, session_key: str, turn: ConversationTurn
    ) -> None:
        """Append a single conversation turn to the JSONL file."""
        path = self._path(user_id, session_key)
        if path is None:
            return
        line = turn.model_dump_json() + "\n"
        async with self._file_lock(session_key):
            async with aiofiles.open(path, mode="a", encoding="utf-8") as f:
                await f.write(line)

    async def get_recent_turns(
        self, user_id: int, session_key: str, limit: int = 20
    ) -> list[ConversationTurn]:
        """Return the last `limit` turns from the session file."""
        path = self._path(user_id, session_key)
        if path is None or not os.path.exists(path):
            return []
        turns: list[ConversationTurn] = []
        async with self._file_lock(session_key):
            try:
                async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
                    async for line in f:
                        line = line.strip()
                        if line:
                            try:
                                turns.append(ConversationTurn.model_validate_json(line))
                            except Exception:
                                pass  # skip corrupt lines
            except OSError as e:
                logger.error("Could not read session %s: %s", session_key, e)
        return turns[-limit:]

    async def compact(
        self, user_id: int, session_key: str, summary: str
    ) -> None:
        """Replace the session file with a single summary turn."""
        path = self._path(user_id, session_key)
        if path is None:
            return
        summary_turn = ConversationTurn(
            role="assistant",
            content=f"[COMPACTED SUMMARY]\n{summary}",
            model_used="compact",
        )
        async with self._file_lock(session_key):
            async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
                await f.write(summary_turn.model_dump_json() + "\n")
        logger.info("Compacted session %s", session_key)

    async def get_all_sessions(self, user_id: int) -> list[str]:
        """Return all session keys for a user (sorted chronologically)."""
        prefix = f"user_{user_id}_"
        try:
            keys = [
                f[:-6]  # strip .jsonl
                for f in os.listdir(self.sessions_dir)
                if f.startswith(prefix) and f.endswith(".jsonl")
            ]
            return sorted(keys)
        except OSError:
            return []

    async def delete_session(self, user_id: int, session_key: str) -> None:
        """Delete a conversation session file for privacy."""
        path = self._path(user_id, session_key)
        if path is None:
            return
        async with self._file_lock(session_key):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logger.info("Deleted session %s for user %d", session_key, user_id)
            except OSError as e:
                logger.error("Could not delete session %s: %s", session_key, e)
                raise
