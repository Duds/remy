"""
SMS ingestion store and webhook handling (US-sms-ingestion).

Stores incoming SMS from Android SMS Gateway webhook and supports
natural-language queries via get_sms_messages tool.
"""

from __future__ import annotations

import logging
from typing import Any

from ..memory.database import DatabaseManager

logger = logging.getLogger(__name__)


class SMSStore:
    """SQLite-backed store for sms_messages table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, sender: str, body: str, received_at: str) -> None:
        """Persist one SMS message."""
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO sms_messages (sender, body, received_at)
                VALUES (?, ?, ?)
                """,
                (sender, body, received_at),
            )
            await conn.commit()

    async def recent(self, hours: int = 24) -> list[dict[str, Any]]:
        """Return recent SMS messages within the last *hours*."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, sender, body, received_at
                FROM sms_messages
                WHERE datetime(received_at) >= datetime('now', ? || ' hours')
                ORDER BY received_at DESC
                LIMIT 100
                """,
                (f"-{hours}",),
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "sender": row[1],
                "body": row[2],
                "received_at": row[3],
            }
            for row in rows
        ]
