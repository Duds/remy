"""
Google Wallet notification handling (US-google-wallet-monitoring).

Stores transaction notifications from Tasker/Android and supports
natural-language queries via get_wallet_transactions tool.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from ..memory.database import DatabaseManager

logger = logging.getLogger(__name__)

# Wallet notification text often contains amounts like $4.27 or $29.99
AMOUNT_RE = re.compile(r"\$[\d,]+\.\d{2}")


class WalletStore:
    """SQLite-backed store for wallet_transactions table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(
        self,
        merchant: str | None,
        amount: str | None,
        raw_title: str,
        raw_text: str,
        occurred_at: str,
    ) -> None:
        """Persist one wallet transaction record."""
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO wallet_transactions (merchant, amount, raw_title, raw_text, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (merchant, amount, raw_title, raw_text, occurred_at),
            )
            await conn.commit()

    async def recent(
        self,
        hours: int = 24,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent wallet transactions within the last *hours*."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, merchant, amount, raw_title, raw_text, occurred_at
                FROM wallet_transactions
                WHERE datetime(occurred_at) >= datetime('now', ? || ' hours')
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                (f"-{hours}", limit),
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "merchant": row[1],
                "amount": row[2],
                "raw_title": row[3],
                "raw_text": row[4],
                "occurred_at": row[5],
            }
            for row in rows
        ]


class WalletHandler:
    """Handles incoming Google Wallet webhook payloads: parse, store, alert."""

    def __init__(
        self,
        store: WalletStore,
        bot: Any,
        chat_id: int,
    ) -> None:
        self._store = store
        self._bot = bot
        self._chat_id = chat_id

    async def handle(
        self,
        title: str,
        text: str,
        subtext: str,
        ts: str,
    ) -> None:
        """Process one Wallet notification: extract amount/merchant, store, send Telegram alert."""
        amount_match = AMOUNT_RE.search(text) or AMOUNT_RE.search(title)
        amount = amount_match.group(0) if amount_match else None
        merchant = title.strip() or "Unknown"

        await self._store.save(
            merchant=merchant,
            amount=amount,
            raw_title=title,
            raw_text=text,
            occurred_at=ts,
        )

        alert = f"💳 Google Wallet\n{title}"
        if text:
            alert += f"\n{text}"
        if subtext:
            alert += f"\n{subtext}"
        try:
            await self._bot.send_message(self._chat_id, alert)
        except Exception as e:
            logger.warning("Wallet alert send failed: %s", e)
