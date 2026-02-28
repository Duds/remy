"""
JSONL-backed conversation session store.
Each user's daily session is an append-only .jsonl file.
Crash-safe: each turn is a single JSON line, never buffered.

Performance: get_recent_turns() uses reverse file reading to efficiently
retrieve only the last N turns without loading the entire file into memory.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiofiles

from ..bot.session import validate_session_key
from ..models import ConversationTurn

logger = logging.getLogger(__name__)

# Chunk size for reverse file reading (8KB is efficient for most SSDs)
_REVERSE_READ_CHUNK_SIZE = 8192


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
        """
        Return the last `limit` turns from the session file.
        
        Uses reverse file reading for O(limit) performance instead of O(n) where
        n is the total number of turns. This prevents latency degradation as
        sessions grow longer.
        """
        path = self._path(user_id, session_key)
        if path is None or not os.path.exists(path):
            return []
        
        async with self._file_lock(session_key):
            try:
                return await self._read_last_n_turns(path, limit)
            except OSError as e:
                logger.error("Could not read session %s: %s", session_key, e)
                return []

    async def _read_last_n_turns(self, path: str, limit: int) -> list[ConversationTurn]:
        """
        Read the last N turns from a JSONL file using reverse chunked reading.
        
        Reads from the end of the file in chunks, collecting complete lines
        until we have enough turns. Much more efficient than reading the entire
        file for long sessions.
        """
        turns: list[ConversationTurn] = []
        
        async with aiofiles.open(path, mode="rb") as f:
            # Get file size
            await f.seek(0, 2)  # Seek to end
            file_size = await f.tell()
            
            if file_size == 0:
                return []
            
            # For small files, just read the whole thing (simpler and fast enough)
            if file_size <= _REVERSE_READ_CHUNK_SIZE * 2:
                await f.seek(0)
                content = await f.read()
                lines = content.decode("utf-8", errors="replace").strip().split("\n")
                for line in lines[-limit:]:
                    line = line.strip()
                    if line:
                        try:
                            turns.append(ConversationTurn.model_validate_json(line))
                        except Exception as e:
                            logger.warning("Skipping corrupt conversation line: %s", e)
                return turns
            
            # For larger files, read from the end in chunks
            buffer = b""
            position = file_size
            lines_found: list[str] = []
            
            while position > 0 and len(lines_found) < limit + 1:
                # Calculate how much to read
                read_size = min(_REVERSE_READ_CHUNK_SIZE, position)
                position -= read_size
                
                # Read the chunk
                await f.seek(position)
                chunk = await f.read(read_size)
                buffer = chunk + buffer
                
                # Extract complete lines from the buffer
                # Keep the first partial line in the buffer
                while b"\n" in buffer:
                    # Split from the right to get complete lines
                    rest, line = buffer.rsplit(b"\n", 1)
                    if line:  # Non-empty line after the last newline
                        try:
                            lines_found.insert(0, line.decode("utf-8", errors="replace"))
                        except Exception as e:
                            logger.debug("Failed to decode line during reverse read: %s", e)
                    buffer = rest
                    
                    if len(lines_found) >= limit:
                        break
            
            # Don't forget the remaining buffer (first line of file)
            if buffer and len(lines_found) < limit:
                try:
                    lines_found.insert(0, buffer.decode("utf-8", errors="replace"))
                except Exception as e:
                    logger.debug("Failed to decode buffer during reverse read: %s", e)
            
            # Parse the lines into turns (take only the last `limit`)
            for line in lines_found[-limit:]:
                line = line.strip()
                if line:
                    try:
                        turns.append(ConversationTurn.model_validate_json(line))
                    except Exception as e:
                        logger.warning("Skipping corrupt conversation line: %s", e)
        
        return turns

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

    async def get_all_sessions(
        self, user_id: int, thread_id: int | None = None
    ) -> list[str]:
        """
        Return all session keys for a user (sorted chronologically).

        If thread_id is provided, only returns sessions for that specific thread.
        Otherwise returns all sessions (both threaded and non-threaded).
        """
        prefix = f"user_{user_id}_"
        try:
            keys = [
                f[:-6]  # strip .jsonl
                for f in os.listdir(self.sessions_dir)
                if f.startswith(prefix) and f.endswith(".jsonl")
            ]
            # Filter by thread_id if specified
            if thread_id is not None:
                thread_marker = f"_thread_{thread_id}_"
                keys = [k for k in keys if thread_marker in k]
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

    async def get_today_messages(
        self, user_id: int, thread_id: int | None = None
    ) -> list[ConversationTurn]:
        """
        Return all conversation turns from today's sessions for a user.

        Collects turns from all sessions whose timestamps fall within today
        (in UTC). Used for end-of-day memory consolidation.
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sessions = await self.get_all_sessions(user_id, thread_id)

        all_turns: list[ConversationTurn] = []
        for session_key in sessions:
            # Session keys are formatted as user_{id}[_thread_{tid}]_{date}
            # Check if session is from today
            if today_str not in session_key:
                continue

            turns = await self.get_recent_turns(user_id, session_key, limit=500)
            all_turns.extend(turns)

        return all_turns

    async def get_messages_since(
        self, user_id: int, since: datetime, thread_id: int | None = None
    ) -> list[ConversationTurn]:
        """
        Return all conversation turns since a given datetime.

        Filters turns by their timestamp field. Used for memory consolidation
        over custom time ranges.
        """
        sessions = await self.get_all_sessions(user_id, thread_id)
        since_iso = since.isoformat()

        all_turns: list[ConversationTurn] = []
        for session_key in sessions:
            turns = await self.get_recent_turns(user_id, session_key, limit=500)
            for turn in turns:
                if turn.timestamp >= since_iso:
                    all_turns.append(turn)

        return all_turns
