"""Write-ahead queue for outbound Telegram messages.

Inspired by OpenClaw's crash-recovery delivery pattern. Messages are persisted
to SQLite before sending, ensuring no message loss during crashes or network
failures.

State machine:
    pending -> sending -> sent (success)
                       -> pending (retry, if retry_count < max_retries)
                       -> failed (max retries exceeded)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from telegram import Bot

logger = logging.getLogger(__name__)


class QueueStatus(str, Enum):
    """Status of a queued message."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


@dataclass
class QueuedMessage:
    """A message in the outbound queue."""

    id: int
    chat_id: str
    message_text: str
    message_type: str
    reply_to_message_id: int | None
    parse_mode: str | None
    status: QueueStatus
    retry_count: int
    max_retries: int
    created_at: datetime
    sent_at: datetime | None
    error_message: str | None


@dataclass
class QueueStats:
    """Statistics for the outbound queue."""

    pending: int = 0
    sending: int = 0
    sent_24h: int = 0
    failed: int = 0


class OutboundQueue:
    """Write-ahead queue for crash-safe message delivery.

    Usage:
        queue = OutboundQueue(db_path, bot)
        await queue.replay_on_startup()  # Replay pending messages from previous run

        # In message handler:
        queue_id = await queue.enqueue(chat_id, "Hello!")
        # Queue processor handles actual sending in background
    """

    def __init__(
        self,
        db_path: str,
        bot: Bot | None = None,
        process_interval: float = 1.0,
    ) -> None:
        self.db_path = db_path
        self.bot = bot
        self.process_interval = process_interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def enqueue(
        self,
        chat_id: str | int,
        message_text: str,
        message_type: str = "text",
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
        max_retries: int = 3,
    ) -> int:
        """Persist a message to the queue before sending.

        Returns:
            The queue entry ID.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO outbound_queue
                    (chat_id, message_text, message_type, reply_to_message_id,
                     parse_mode, status, max_retries, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(chat_id),
                    message_text,
                    message_type,
                    reply_to_message_id,
                    parse_mode,
                    QueueStatus.PENDING.value,
                    max_retries,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
            queue_id = cursor.lastrowid
            logger.debug("Enqueued message %d for chat %s", queue_id, chat_id)
            return queue_id

    async def get_pending(self, limit: int = 10) -> list[QueuedMessage]:
        """Retrieve pending messages for processing."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM outbound_queue
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (QueueStatus.PENDING.value, limit),
            )
            rows = await cursor.fetchall()
            return [self._row_to_message(row) for row in rows]

    async def mark_sending(self, queue_id: int) -> None:
        """Mark a message as currently being sent."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE outbound_queue SET status = ? WHERE id = ?",
                (QueueStatus.SENDING.value, queue_id),
            )
            await db.commit()

    async def mark_sent(self, queue_id: int) -> None:
        """Mark a message as successfully sent."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE outbound_queue
                SET status = ?, sent_at = ?
                WHERE id = ?
                """,
                (
                    QueueStatus.SENT.value,
                    datetime.now(timezone.utc).isoformat(),
                    queue_id,
                ),
            )
            await db.commit()
            logger.debug("Message %d marked as sent", queue_id)

    async def mark_failed(
        self,
        queue_id: int,
        error_message: str,
        retry: bool = True,
    ) -> None:
        """Mark a message as failed, optionally scheduling a retry."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get current retry count and max retries
            cursor = await db.execute(
                "SELECT retry_count, max_retries FROM outbound_queue WHERE id = ?",
                (queue_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return

            retry_count, max_retries = row
            new_retry_count = retry_count + 1

            if retry and new_retry_count < max_retries:
                # Schedule retry
                await db.execute(
                    """
                    UPDATE outbound_queue
                    SET status = ?, retry_count = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (
                        QueueStatus.PENDING.value,
                        new_retry_count,
                        error_message,
                        queue_id,
                    ),
                )
                logger.warning(
                    "Message %d failed (attempt %d/%d): %s",
                    queue_id,
                    new_retry_count,
                    max_retries,
                    error_message,
                )
            else:
                # Max retries exceeded
                await db.execute(
                    """
                    UPDATE outbound_queue
                    SET status = ?, retry_count = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (
                        QueueStatus.FAILED.value,
                        new_retry_count,
                        error_message,
                        queue_id,
                    ),
                )
                logger.error(
                    "Message %d permanently failed after %d attempts: %s",
                    queue_id,
                    new_retry_count,
                    error_message,
                )
            await db.commit()

    async def process_pending(self) -> int:
        """Process pending messages in the queue.

        Returns:
            Number of messages processed.
        """
        if self.bot is None:
            logger.warning("Cannot process queue: bot not configured")
            return 0

        messages = await self.get_pending(limit=5)
        processed = 0

        for msg in messages:
            await self.mark_sending(msg.id)

            try:
                if msg.message_type == "text":
                    await self.bot.send_message(
                        chat_id=int(msg.chat_id),
                        text=msg.message_text,
                        reply_to_message_id=msg.reply_to_message_id,
                        parse_mode=msg.parse_mode,
                    )
                else:
                    logger.warning(
                        "Unsupported message type %s for queue %d",
                        msg.message_type,
                        msg.id,
                    )
                    await self.mark_failed(msg.id, f"Unsupported type: {msg.message_type}", retry=False)
                    continue

                await self.mark_sent(msg.id)
                processed += 1

            except Exception as e:
                await self.mark_failed(msg.id, str(e))

        return processed

    async def replay_on_startup(self) -> int:
        """Replay pending and sending messages after a crash/restart.

        Messages stuck in 'sending' state are reset to 'pending' for retry.

        Returns:
            Number of messages reset for replay.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Reset 'sending' messages back to 'pending'
            cursor = await db.execute(
                """
                UPDATE outbound_queue
                SET status = ?
                WHERE status = ?
                """,
                (QueueStatus.PENDING.value, QueueStatus.SENDING.value),
            )
            await db.commit()
            reset_count = cursor.rowcount

            if reset_count > 0:
                logger.info("Reset %d messages from 'sending' to 'pending' on startup", reset_count)

            # Count pending messages
            cursor = await db.execute(
                "SELECT COUNT(*) FROM outbound_queue WHERE status = ?",
                (QueueStatus.PENDING.value,),
            )
            row = await cursor.fetchone()
            pending_count = row[0] if row else 0

            if pending_count > 0:
                logger.info("Found %d pending messages to replay", pending_count)

            return reset_count

    async def get_stats(self) -> QueueStats:
        """Get queue statistics for diagnostics."""
        async with aiosqlite.connect(self.db_path) as db:
            stats = QueueStats()

            # Pending count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM outbound_queue WHERE status = ?",
                (QueueStatus.PENDING.value,),
            )
            row = await cursor.fetchone()
            stats.pending = row[0] if row else 0

            # Sending count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM outbound_queue WHERE status = ?",
                (QueueStatus.SENDING.value,),
            )
            row = await cursor.fetchone()
            stats.sending = row[0] if row else 0

            # Failed count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM outbound_queue WHERE status = ?",
                (QueueStatus.FAILED.value,),
            )
            row = await cursor.fetchone()
            stats.failed = row[0] if row else 0

            # Sent in last 24 hours
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM outbound_queue
                WHERE status = ? AND sent_at > datetime('now', '-1 day')
                """,
                (QueueStatus.SENT.value,),
            )
            row = await cursor.fetchone()
            stats.sent_24h = row[0] if row else 0

            return stats

    async def cleanup_old_messages(self, days: int = 7) -> int:
        """Remove sent/failed messages older than specified days.

        Returns:
            Number of messages deleted.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM outbound_queue
                WHERE status IN (?, ?)
                AND created_at < datetime('now', ?)
                """,
                (QueueStatus.SENT.value, QueueStatus.FAILED.value, f"-{days} days"),
            )
            await db.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Cleaned up %d old queue messages", deleted)
            return deleted

    def start_processor(self) -> None:
        """Start the background queue processor."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._processor_loop())
        logger.info("Started outbound queue processor")

    async def stop_processor(self) -> None:
        """Stop the background queue processor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Stopped outbound queue processor")

    async def _processor_loop(self) -> None:
        """Background loop that processes pending messages."""
        while self._running:
            try:
                await self.process_pending()
            except Exception:
                logger.exception("Error in queue processor loop")
            await asyncio.sleep(self.process_interval)

    def _row_to_message(self, row: aiosqlite.Row) -> QueuedMessage:
        """Convert a database row to a QueuedMessage."""
        return QueuedMessage(
            id=row["id"],
            chat_id=row["chat_id"],
            message_text=row["message_text"],
            message_type=row["message_type"],
            reply_to_message_id=row["reply_to_message_id"],
            parse_mode=row["parse_mode"],
            status=QueueStatus(row["status"]),
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            created_at=datetime.fromisoformat(row["created_at"]),
            sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
            error_message=row["error_message"],
        )
