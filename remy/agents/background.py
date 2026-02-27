"""
BackgroundTaskRunner — fire-and-forget async task execution.

Runs a coroutine outside the session lock and delivers the result (or an
error notice) to the user via Telegram when done.

Usage::

    runner = BackgroundTaskRunner(context.bot, update.message.chat_id)
    asyncio.create_task(runner.run(some_coro(), label="board analysis"))
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 4000


class BackgroundTaskRunner:
    """Run a coroutine in the background and send its result to a Telegram chat."""

    def __init__(self, bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def run(self, coro, *, label: str) -> None:
        """Await *coro* and send its string result to the chat.

        Long results are split into multiple messages at 4 000-character
        boundaries.  Exceptions are logged and a brief failure notice is
        sent to the user so they are never left hanging.
        """
        try:
            result = await coro
            if not result:
                return
            # Split long results into multiple messages
            for i in range(0, len(result), _MAX_MESSAGE_LENGTH):
                await self._bot.send_message(
                    self._chat_id,
                    result[i : i + _MAX_MESSAGE_LENGTH],
                    parse_mode="Markdown",
                )
        except Exception:
            logger.exception("Background task %r failed", label)
            await self._bot.send_message(
                self._chat_id,
                f"Sorry, the {label} task failed — check /logs for details.",
            )
