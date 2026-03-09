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


def _get_db_path(data_dir: str, db_path: str | Path | None = None) -> Path:
    """Return path to relay DB. If db_path is set (e.g. remy.db), use it; else data_dir/relay.db."""
    if db_path is not None:
        return Path(db_path)
    return Path(data_dir) / "relay.db"


async def _ensure_db(path: Path) -> bool:
    """Ensure relay DB exists with full schema (messages, tasks, shared_notes). Returns True if usable."""
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
                CREATE TABLE IF NOT EXISTS tasks (
                    id          TEXT PRIMARY KEY,
                    from_agent  TEXT NOT NULL,
                    to_agent    TEXT NOT NULL,
                    task_type   TEXT NOT NULL,
                    description TEXT NOT NULL,
                    params      TEXT NOT NULL DEFAULT '{}',
                    status      TEXT NOT NULL DEFAULT 'pending',
                    result      TEXT,
                    notes       TEXT,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_to ON tasks(to_agent, status);
                CREATE INDEX IF NOT EXISTS idx_tasks_from ON tasks(from_agent);
                CREATE TABLE IF NOT EXISTS shared_notes (
                    id          TEXT PRIMARY KEY,
                    from_agent  TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    tags        TEXT NOT NULL DEFAULT '[]',
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notes_tags ON shared_notes(tags);
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
    thread_id: str | None = None,
    data_dir: str | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """
    Post a message from Remy to cowork. Returns dict with message_id, thread_id, status on success; None on failure.
    """
    if not content or not content.strip():
        return None

    content = content.strip()[:_MAX_CONTENT_LEN]

    if data_dir is None and db_path is None:
        from ..config import settings

        data_dir = settings.data_dir

    path = _get_db_path(data_dir or "", db_path)
    if not path.exists() and db_path is None:
        if not await _ensure_db(path):
            return None

    try:
        async with aiosqlite.connect(str(path)) as conn:
            msg_id = str(uuid.uuid4())[:8]
            tid = thread_id if thread_id is not None else msg_id
            now = datetime.now(timezone.utc).isoformat()

            await conn.execute(
                "INSERT INTO messages (id, from_agent, to_agent, content, thread_id, read, created_at) VALUES (?,?,?,?,?,0,?)",
                (msg_id, from_agent, to_agent, content, tid, now),
            )
            await conn.commit()
        logger.info("Relay: posted message to %s (id=%s)", to_agent, msg_id)
        return {"message_id": msg_id, "thread_id": tid, "status": "sent"}
    except Exception as e:
        logger.warning("Relay post_message failed: %s", e)
        return None


async def get_messages_for_remy(
    *,
    agent: str = "remy",
    unread_only: bool = True,
    mark_read: bool = True,
    limit: int = 20,
    data_dir: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[list[dict], int]:
    """Read messages for *agent*. Returns (messages, unread_count). Marks read if mark_read."""
    if data_dir is None and db_path is None:
        from ..config import settings

        data_dir = settings.data_dir

    path = _get_db_path(data_dir or "", db_path)
    if not path.exists():
        return [], 0

    try:
        async with aiosqlite.connect(str(path)) as conn:
            conn.row_factory = aiosqlite.Row
            where = "to_agent = ?"
            args: list = [agent]
            if unread_only:
                where += " AND read = 0"
            cursor = await conn.execute(
                f"SELECT id, from_agent, content, thread_id, read, created_at "
                f"FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
                args + [min(max(1, limit), 100)],
            )
            rows = await cursor.fetchall()
            messages = []
            for r in rows:
                m = dict(r)
                m["read"] = bool(m["read"])
                messages.append(m)
            if mark_read and messages:
                ids = [m["id"] for m in messages]
                placeholders = ",".join("?" * len(ids))
                await conn.execute(
                    f"UPDATE messages SET read=1 WHERE id IN ({placeholders})",
                    ids,
                )
                await conn.commit()
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read = 0",
                (agent,),
            )
            row = await cursor.fetchone()
            unread_count = int(row[0]) if row is not None else 0
        logger.debug("Relay: fetched %d message(s) for %s", len(messages), agent)
        return messages, unread_count
    except Exception as e:
        logger.warning("Relay get_messages_for_remy failed: %s", e)
        return [], 0


TASK_STATUSES = {"pending", "in_progress", "done", "failed", "needs_clarification"}


async def get_tasks_for_remy(
    *,
    agent: str = "remy",
    status: str | None = "pending",
    limit: int = 20,
    data_dir: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[list[dict], int]:
    """Read tasks for *agent* (optional status filter). Returns (tasks, pending_count)."""
    if data_dir is None and db_path is None:
        from ..config import settings

        data_dir = settings.data_dir

    path = _get_db_path(data_dir or "", db_path)
    if not path.exists():
        return [], 0

    try:
        async with aiosqlite.connect(str(path)) as conn:
            conn.row_factory = aiosqlite.Row
            where = "to_agent = ?"
            args: list = [agent]
            if status and status != "all":
                where += " AND status = ?"
                args.append(status)
            cursor = await conn.execute(
                f"SELECT id, from_agent, task_type, description, params, status, result, notes, created_at, updated_at "
                f"FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT ?",
                args + [min(max(1, limit), 100)],
            )
            rows = await cursor.fetchall()
            tasks = []
            for r in rows:
                t = dict(r)
                t["params"] = json.loads(t.get("params") or "{}")
                tasks.append(t)
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE to_agent = ? AND status = 'pending'",
                (agent,),
            )
            row = await cursor.fetchone()
            pending_count = int(row[0]) if row is not None else 0
        logger.debug(
            "Relay: fetched %d task(s) for %s (status=%s)", len(tasks), agent, status
        )
        return tasks, pending_count
    except Exception as e:
        logger.warning("Relay get_tasks_for_remy failed: %s", e)
        return [], 0


async def update_task(
    task_id: str,
    status: str,
    *,
    result: str | None = None,
    notes: str | None = None,
    data_dir: str | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """Update a task. Returns dict with task_id, status, updated or None if not found/invalid."""
    if status not in TASK_STATUSES:
        return None

    if data_dir is None and db_path is None:
        from ..config import settings

        data_dir = settings.data_dir

    path = _get_db_path(data_dir or "", db_path)
    if not path.exists():
        return None

    try:
        async with aiosqlite.connect(str(path)) as conn:
            cursor = await conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if (await cursor.fetchone()) is None:
                return None
            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                "UPDATE tasks SET status = ?, result = ?, notes = ?, updated_at = ? WHERE id = ?",
                (status, result, notes, now, task_id),
            )
            await conn.commit()
        logger.info("Relay: updated task %s -> %s", task_id, status)
        return {"task_id": task_id, "status": status, "updated": True}
    except Exception as e:
        logger.warning("Relay update_task failed: %s", e)
        return None


async def create_task(
    task_type: str,
    description: str,
    *,
    from_agent: str = "remy",
    to_agent: str = "cowork",
    params: dict | None = None,
    data_dir: str | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """Create a new relay task addressed to *to_agent*.

    Returns dict with task_id, status on success; None on failure.
    Caller must check ``settings.relay_can_create_tasks`` before calling.
    """
    if not task_type or not description:
        return None

    if data_dir is None and db_path is None:
        from ..config import settings

        data_dir = settings.data_dir

    path = _get_db_path(data_dir or "", db_path)
    if not path.exists() and db_path is None:
        if not await _ensure_db(path):
            return None

    params_json = json.dumps(params or {})

    try:
        async with aiosqlite.connect(str(path)) as conn:
            task_id = str(uuid.uuid4())[:8]
            now = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                """
                INSERT INTO tasks (id, from_agent, to_agent, task_type, description, params, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (task_id, from_agent, to_agent, task_type, description[:2000], params_json, now, now),
            )
            await conn.commit()
        logger.info("Relay: created task %s → %s (type=%s)", from_agent, to_agent, task_type)
        return {"task_id": task_id, "status": "pending"}
    except Exception as e:
        logger.warning("Relay create_task failed: %s", e)
        return None


async def post_note(
    content: str,
    *,
    from_agent: str = "remy",
    tags: list[str] | None = None,
    data_dir: str | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """Post a shared note. Returns dict with note_id, status on success; None on failure."""
    if not content or not content.strip():
        return None

    content = content.strip()[:_MAX_CONTENT_LEN]
    tags = tags or []
    tags_json = json.dumps(tags)

    if data_dir is None and db_path is None:
        from ..config import settings

        data_dir = settings.data_dir

    path = _get_db_path(data_dir or "", db_path)
    if not path.exists() and db_path is None:
        if not await _ensure_db(path):
            return None

    try:
        async with aiosqlite.connect(str(path)) as conn:
            if db_path is None:
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
        return {"note_id": note_id, "status": "posted"}
    except Exception as e:
        logger.warning("Relay post_note failed: %s", e)
        return None
