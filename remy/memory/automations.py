"""
AutomationStore — CRUD for user-defined scheduled reminders.

Automations are simple cron-based reminders stored in the database.
When a job fires, the scheduler sends the label as a Telegram message.
"""

import logging
from typing import Any

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class AutomationStore:
    """Persistent store for user-defined scheduled automations."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def add(
        self, user_id: int, label: str, cron: str = "", fire_at: str | None = None
    ) -> int:
        """Insert a new automation. Returns the new row ID.

        Pass *fire_at* (ISO 8601 datetime string) for one-time reminders; leave
        *cron* empty in that case.  Pass a 5-field *cron* string for recurring
        reminders and leave *fire_at* as None.
        """
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO automations (user_id, label, cron, fire_at) VALUES (?, ?, ?, ?)",
                (user_id, label, cron, fire_at),
            )
            await conn.commit()
            return cursor.lastrowid

    async def delete(self, automation_id: int) -> None:
        """Delete an automation row unconditionally (used after one-time reminders fire)."""
        async with self._db.get_connection() as conn:
            await conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
            await conn.commit()

    async def get_all(self, user_id: int) -> list[dict[str, Any]]:
        """Return all automations for a user, ordered by creation time."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id, label, cron, fire_at, last_run_at, created_at "
                "FROM automations WHERE user_id = ? ORDER BY id",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def remove(self, user_id: int, automation_id: int) -> bool:
        """Delete an automation. Returns True if a row was deleted."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM automations WHERE id = ? AND user_id = ?",
                (automation_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def get_all_for_scheduler(self) -> list[dict[str, Any]]:
        """Return all automations across all users (for scheduler startup load)."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, label, cron, fire_at FROM automations ORDER BY id",
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def update_last_run(self, automation_id: int) -> None:
        """Stamp the last_run_at timestamp on an automation."""
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE automations SET last_run_at = datetime('now') WHERE id = ?",
                (automation_id,),
            )
            await conn.commit()
