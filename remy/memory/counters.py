"""
Named counters per user (e.g. sobriety streak in days).

CounterStore provides get/set/increment/reset for use by tools and the
heartbeat; memory injector can include counter values in context.

Counters in AUTO_INCREMENT_DAILY_COUNTERS are auto-incremented once per
calendar day at midnight (user timezone) so the user does not need to
say "add a day"; last_increment_date prevents double-counting.
"""

import logging
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from ..config import settings
from .database import DatabaseManager

logger = logging.getLogger(__name__)

# Counter names to include in memory/heartbeat context when present
INJECT_COUNTER_NAMES = ("sobriety_streak",)

# Counter names that are auto-incremented at midnight (user TZ) each day when value > 0
AUTO_INCREMENT_DAILY_COUNTERS = ("sobriety_streak",)


class CounterStore:
    """Persists and retrieves named integer counters per user."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get(self, user_id: int, name: str) -> dict[str, Any] | None:
        """Return counter row as dict (value, unit, updated_at) or None if not set."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT value, unit, updated_at FROM counters
                WHERE user_id = ? AND name = ?
                """,
                (user_id, name),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {"value": row[0], "unit": row[1] or "days", "updated_at": row[2]}

    def _today_user_tz(self) -> str:
        """Return today's date as YYYY-MM-DD in the scheduler timezone."""
        tz = ZoneInfo(getattr(settings, "scheduler_timezone", "UTC"))
        return datetime.now(tz).strftime("%Y-%m-%d")

    async def set(
        self,
        user_id: int,
        name: str,
        value: int,
        unit: str = "days",
    ) -> None:
        """Set counter; insert or replace. Value must be >= 0. Sets last_increment_date to today (user TZ) to avoid double-count with midnight job."""
        if value < 0:
            raise ValueError("Counter value must be non-negative")
        today = self._today_user_tz()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO counters (user_id, name, value, unit, updated_at, last_increment_date)
                VALUES (?, ?, ?, ?, datetime('now'), ?)
                ON CONFLICT(user_id, name) DO UPDATE SET
                    value = excluded.value,
                    unit = excluded.unit,
                    updated_at = datetime('now'),
                    last_increment_date = excluded.last_increment_date
                """,
                (user_id, name, value, unit, today),
            )
            await conn.commit()

    async def increment(self, user_id: int, name: str, by: int = 1) -> int:
        """Increment counter by `by` (default 1). Creates at 0 if missing. Sets last_increment_date to today (user TZ). Returns new value."""
        today = self._today_user_tz()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO counters (user_id, name, value, unit, updated_at, last_increment_date)
                VALUES (?, ?, ?, 'days', datetime('now'), ?)
                ON CONFLICT(user_id, name) DO UPDATE SET
                    value = value + ?,
                    updated_at = datetime('now'),
                    last_increment_date = ?
                """,
                (user_id, name, by, today, by, today),
            )
            await conn.commit()
            cursor = await conn.execute(
                "SELECT value FROM counters WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            row = await cursor.fetchone()
        return row[0] if row is not None else 0

    async def reset(self, user_id: int, name: str) -> None:
        """Set counter to 0. Sets last_increment_date to today so midnight job does not immediately bump to 1."""
        today = self._today_user_tz()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO counters (user_id, name, value, unit, updated_at, last_increment_date)
                VALUES (?, ?, 0, 'days', datetime('now'), ?)
                ON CONFLICT(user_id, name) DO UPDATE SET
                    value = 0,
                    updated_at = datetime('now'),
                    last_increment_date = ?
                """,
                (user_id, name, today, today),
            )
            await conn.commit()

    async def increment_daily_if_new_day(
        self, user_id: int, name: str, tz: ZoneInfo | None = None
    ) -> bool:
        """
        If the counter exists, has value > 0, and last_increment_date is before today
        (in the given timezone), increment by 1 and set last_increment_date = today.
        Returns True if we incremented, False otherwise. Used by the midnight daily job.
        """
        tz = tz or ZoneInfo(getattr(settings, "scheduler_timezone", "UTC"))
        today = datetime.now(tz).strftime("%Y-%m-%d")
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE counters
                SET value = value + 1, last_increment_date = ?, updated_at = datetime('now')
                WHERE user_id = ? AND name = ? AND value > 0
                  AND (last_increment_date IS NULL OR last_increment_date < ?)
                """,
                (today, user_id, name, today),
            )
            updated = cursor.rowcount
            await conn.commit()
        if updated:
            logger.info(
                "Counter %s auto-incremented at midnight for user %s", name, user_id
            )
        return updated > 0

    async def get_all_for_inject(
        self, user_id: int, names: tuple[str, ...] = INJECT_COUNTER_NAMES
    ) -> list[dict[str, Any]]:
        """Return list of {name, value, unit} for given names that exist. For memory/heartbeat inject."""
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT name, value, unit FROM counters
                WHERE user_id = ? AND name IN ({placeholders}) AND value > 0
                """,
                (user_id, *names),
            )
            rows = await cursor.fetchall()
        return [{"name": r[0], "value": r[1], "unit": r[2] or "days"} for r in rows]
