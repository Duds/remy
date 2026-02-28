"""
BackgroundTaskRunner — fire-and-forget async task execution.

Runs a coroutine outside the session lock and delivers the result (or an
error notice) to the user via Telegram when done.

Usage (with job tracking and animated working message)::

    from remy.bot.working_message import WorkingMessage

    wm = WorkingMessage(context.bot, chat_id, thread_id)
    await wm.start()

    job_id = await job_store.create(user_id, "board", topic)
    runner = BackgroundTaskRunner(
        context.bot, update.message.chat_id,
        job_store=job_store, job_id=job_id,
        working_message=wm,
    )
    asyncio.create_task(runner.run(some_coro(), label="board analysis"))

Usage (without job tracking — legacy)::

    runner = BackgroundTaskRunner(context.bot, update.message.chat_id)
    asyncio.create_task(runner.run(some_coro(), label="board analysis"))
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bot.working_message import WorkingMessage

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 4000


class BackgroundTaskRunner:
    """Run a coroutine in the background and send its result to a Telegram chat."""

    def __init__(
        self,
        bot,
        chat_id: int,
        *,
        job_store=None,
        job_id: int | None = None,
        working_message: "WorkingMessage | None" = None,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._job_store = job_store
        self._job_id = job_id
        self._working_message = working_message

    async def run(self, coro, *, label: str) -> None:
        """Await *coro* and send its string result to the chat.

        Long results are split into multiple messages at 4 000-character
        boundaries.  Exceptions are logged and a brief failure notice is
        sent to the user so they are never left hanging.

        Job status is updated in the BackgroundJobStore if one was provided.
        If a WorkingMessage was provided, it is stopped before sending results.
        """
        if self._job_store and self._job_id:
            await self._job_store.set_running(self._job_id)
        try:
            result = await coro

            # Stop the animated working message before sending results
            if self._working_message:
                await self._working_message.stop()

            if self._job_store and self._job_id:
                await self._job_store.set_done(self._job_id, result or "")
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

            # Stop the animated working message on failure too
            if self._working_message:
                await self._working_message.stop()

            if self._job_store and self._job_id:
                await self._job_store.set_failed(
                    self._job_id, f"Task failed — see /logs for details"
                )
            await self._bot.send_message(
                self._chat_id,
                f"Sorry, the {label} task failed — check /logs for details.",
            )
