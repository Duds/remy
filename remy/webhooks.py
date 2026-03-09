"""Outgoing webhook system (paperclip-ideas §L).

Supports subscribing external URLs to internal events and firing them
with retries when those events occur.

Subscriptions are stored in SQLite (webhook_subscriptions table).
Each subscription has an event name and a target URL.

Supported events:
  - relay_task_done          fired when a relay task transitions to 'done'
  - relay_task_needs_clarification  fired when a relay task transitions to 'needs_clarification'
  - plan_step_complete       fired when a plan step status becomes 'done'

Usage:
    from remy.webhooks import WebhookManager
    wm = WebhookManager(db)
    await wm.subscribe("relay_task_done", "https://example.com/hook")
    await wm.fire("relay_task_done", {"task_id": "abc", "result": "..."})
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds


class WebhookManager:
    """Stores subscriptions in SQLite and fires them with exponential-backoff retries."""

    def __init__(self, db) -> None:  # db: DatabaseManager
        self._db = db

    # ── Subscription management ─────────────────────────────────────────────

    async def subscribe(self, event: str, url: str) -> dict:
        """Register a webhook URL for an event. Returns the subscription record."""
        event = event.strip()
        url = url.strip()
        if not event or not url:
            raise ValueError("event and url are required")

        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO webhook_subscriptions (event, url, created_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(event, url) DO UPDATE SET created_at = datetime('now')
                """,
                (event, url),
            )
            await conn.commit()
            cursor = await conn.execute(
                "SELECT id, event, url, created_at FROM webhook_subscriptions WHERE event=? AND url=?",
                (event, url),
            )
            row = await cursor.fetchone()
        return dict(row) if row else {"event": event, "url": url}

    async def unsubscribe(self, event: str, url: str) -> bool:
        """Remove a subscription. Returns True if a row was deleted."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM webhook_subscriptions WHERE event=? AND url=?",
                (event, url),
            )
            await conn.commit()
            return (cursor.rowcount or 0) > 0

    async def list_subscriptions(self, event: str | None = None) -> list[dict]:
        """List all subscriptions, optionally filtered by event."""
        async with self._db.get_connection() as conn:
            if event:
                rows = await conn.execute_fetchall(
                    "SELECT id, event, url, created_at FROM webhook_subscriptions WHERE event=? ORDER BY created_at",
                    (event,),
                )
            else:
                rows = await conn.execute_fetchall(
                    "SELECT id, event, url, created_at FROM webhook_subscriptions ORDER BY event, created_at"
                )
        return [dict(r) for r in rows]

    # ── Firing ──────────────────────────────────────────────────────────────

    async def fire(self, event: str, payload: dict[str, Any]) -> None:
        """Fire all subscriptions for an event. Runs asynchronously without blocking the caller."""
        subs = await self.list_subscriptions(event)
        if not subs:
            return
        body = json.dumps({"event": event, "payload": payload, "fired_at": time.time()})
        for sub in subs:
            asyncio.create_task(
                self._fire_with_retry(sub["url"], body, event),
                name=f"webhook:{event}:{sub['id']}",
            )

    async def _fire_with_retry(self, url: str, body: str, event: str) -> None:
        """POST body to url with up to _MAX_RETRIES attempts using exponential backoff."""
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not installed — webhooks disabled")
            return

        headers = {"Content-Type": "application/json", "X-Remy-Event": event}
        for attempt in range(_MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status < 400:
                            logger.debug("Webhook fired: %s → %s (status %d)", event, url, resp.status)
                            return
                        logger.warning("Webhook %s returned %d (attempt %d)", url, resp.status, attempt + 1)
            except Exception as e:
                logger.warning("Webhook %s failed (attempt %d): %s", url, attempt + 1, e)

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_BACKOFF_BASE ** (attempt + 1))

        logger.error("Webhook %s failed after %d retries for event %s", url, _MAX_RETRIES, event)
