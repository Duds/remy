"""Delivery helper: send via write-ahead queue when available, else bot directly.

SAD v7: proactive and heartbeat messages use the queue for crash recovery.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Bot

    from .queue import OutboundQueue

logger = logging.getLogger(__name__)


async def send_via_queue_or_bot(
    *,
    queue: "OutboundQueue | None",
    bot: "Bot | None",
    chat_id: int | str,
    text: str,
    parse_mode: str | None = None,
) -> bool:
    """Send a text message: enqueue if queue is available, else send via bot.

    When queue is not None and has a processor running, the message is persisted
    and the background processor will send it (crash-safe). When queue is None
    or bot is None, only the direct send path is used.

    Returns:
        True if the message was enqueued or sent successfully, False otherwise.
    """
    if queue is not None and bot is not None:
        try:
            await queue.enqueue(
                chat_id=chat_id,
                message_text=text,
                message_type="text",
                parse_mode=parse_mode,
            )
            logger.debug("Enqueued message for chat %s (%d chars)", chat_id, len(text))
            return True
        except Exception as e:
            logger.warning("Enqueue failed, falling back to direct send: %s", e)

    if bot is not None:
        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except Exception as e:
            logger.warning("Direct send failed (chat %s): %s", chat_id, e)
            return False

    logger.warning("No queue and no bot — message not sent to chat %s", chat_id)
    return False
