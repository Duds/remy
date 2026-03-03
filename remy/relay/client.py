"""
Relay client — direct SQLite writes to relay.db.

The relay_mcp server and Remy share the same relay.db (via Docker volume
or local data_dir). This module writes directly to the database so Remy
can post messages/notes to cowork without requiring an HTTP client or
MCP invocation.

Schema matches relay_mcp/server.py.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# Max content length (matches relay PostMessageInput)
_MAX_CONTENT_LEN = 8000


def _get_db_path(data_dir: str) -> Path:
    """Return path to relay.db (shared with relay_mcp)."""
    return Path(data_dir) / "relay.db"


async def _ensure_db(path: Path) -> bool:
    """Ensure relay.db exists and has schema. Returns True if usable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(path)) as conn:
            await conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          TEXT PRIMARY KEY,
                    from_agent  TEXT NOT NULL,
                    to_agent    TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    thread_id   TEXT,
                    read        INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_agent, read);
            """)
            await conn.commit()
        return True
    except Exception as e:
        logger.warning("Relay DB init failed: %s", e)
        return False


async def post_message_to_cowork(
    content: str,
    *,
    from_agent: str = "remy",
    to_agent: str = "cowork",
    data_dir: str | None = None,
) -> bool:
    """
    Post a message from Remy to cowork.

    Writes directly to relay.db. Returns True on success, False on failure.
    """
    if not content or not content.strip():
        return False

    content = content.strip()[:_MAX_CONTENT_LEN]

    if data_dir is None:
        from ..config import settings
        data_dir = settings.data_dir

    path = _get_db_path(data_dir)
    if not path.exists():
        if not await _ensure_db(path):
            return False

    try:
        async with aiosqlite.connect(str(path)) as conn:
            msg_id = str(uuid.uuid4())[:8]
            thread_id = msg_id
            now = datetime.now(timezone.utc).isoformat()

            await conn.execute(
                "INSERT INTO messages (id, from_agent, to_agent, content, thread_id, read, created_at) VALUES (?,?,?,?,?,0,?)",
                (msg_id, from_agent, to_agent, content, thread_id, now),
            )
            await conn.commit()
        logger.info("Relay: posted message to %s (id=%s)", to_agent, msg_id)
        return True
    except Exception as e:
        logger.warning("Relay post_message failed: %s", e)
        return False


async def get_messages_for_remy(
    *,
    agent: str = "remy",
    mark_read: bool = True,
    data_dir: str | None = None,
) -> list[dict]:
    """Read unread messages addressed to *agent* from relay.db.

    Returns a list of message dicts (keys: id, from_agent, content,
    thread_id, created_at) ordered oldest-first.  Marks them read
    unless mark_read=False.  Returns [] when the DB doesn't exist.
    """
    if data_dir is None:
        from ..config import settings
        data_dir = settings.data_dir

    path = _get_db_path(data_dir)
    if not path.exists():
        return []

    try:
        async with aiosqlite.connect(str(path)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT id, from_agent, content, thread_id, created_at "
                "FROM messages WHERE to_agent=? AND read=0 ORDER BY created_at ASC",
                (agent,),
            )
            rows = await cursor.fetchall()
            messages = [dict(row) for row in rows]
            if mark_read and messages:
                ids = [m["id"] for m in messages]
                placeholders = ",".join("?" * len(ids))
                await conn.execute(
                    f"UPDATE messages SET read=1 WHERE id IN ({placeholders})",
                    ids,
                )
                await conn.commit()
        logger.debug("Relay: fetched %d message(s) for %s", len(messages), agent)
        return messages
    except Exception as e:
        logger.warning("Relay get_messages_for_remy failed: %s", e)
        return []


async def get_tasks_for_remy(
    *,
    agent: str = "remy",
    status: str = "pending",
    data_dir: str | None = None,
) -> list[dict]:
    """Read tasks with *status* addressed to *agent* from relay.db.

    Returns a list of task dicts (keys: id, from_agent, task_type,
    description, params, created_at) ordered oldest-first.
    Returns [] when the DB doesn't exist.
    """
    if data_dir is None:
        from ..config import settings
        data_dir = settings.data_dir

    path = _get_db_path(data_dir)
    if not path.exists():
        return []

    try:
        async with aiosqlite.connect(str(path)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT id, from_agent, task_type, description, params, created_at "
                "FROM tasks WHERE to_agent=? AND status=? ORDER BY created_at ASC",
                (agent, status),
            )
            rows = await cursor.fetchall()
            tasks = [dict(row) for row in rows]
        logger.debug("Relay: fetched %d task(s) for %s (status=%s)", len(tasks), agent, status)
        return tasks
    except Exception as e:
        logger.warning("Relay get_tasks_for_remy failed: %s", e)
        return []


async def post_note(
    content: str,
    *,
    from_agent: str = "remy",
    tags: list[str] | None = None,
    data_dir: str | None = None,
) -> bool:
    """
    Post a shared note to the relay.

    Notes are visible to all agents via relay_get_notes.
    Returns True on success, False on failure.
    """
    if not content or not content.strip():
        return False

    content = content.strip()[:_MAX_CONTENT_LEN]
    tags = tags or []
    tags_json = json.dumps(tags)

    if data_dir is None:
        from ..config import settings
        data_dir = settings.data_dir

    path = _get_db_path(data_dir)
    if not path.exists():
        if not await _ensure_db(path):
            return False

    try:
        async with aiosqlite.connect(str(path)) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS shared_notes (id TEXT PRIMARY KEY, from_agent TEXT NOT NULL, content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_tags ON shared_notes(tags)"
            )
            note_id = str(uuid.uuid4())[:8]
            now = datetime.now(timezone.utc).isoformat()

            await conn.execute(
                "INSERT INTO shared_notes (id, from_agent, content, tags, created_at) VALUES (?,?,?,?,?)",
                (note_id, from_agent, content, tags_json, now),
            )
            await conn.commit()
        logger.info("Relay: posted note (id=%s, tags=%s)", note_id, tags)
        return True
    except Exception as e:
        logger.warning("Relay post_note failed: %s", e)
        return False
