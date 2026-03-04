"""
BackgroundTaskRunner — fire-and-forget async task execution.

Runs a coroutine outside the session lock and delivers the result (or an
error notice) to the user via Telegram when done.

Usage (with job tracking and animated working message)::

    from remy.bot.working_message import WorkingMessage
    from telegram.constants import ChatAction

    wm = WorkingMessage(context.bot, chat_id, thread_id)
    await wm.start()

    job_id = await job_store.create(user_id, "board", topic)
    runner = BackgroundTaskRunner(
        context.bot, update.message.chat_id,
        job_store=job_store, job_id=job_id,
        working_message=wm,
        thread_id=thread_id,
        chat_action=ChatAction.UPLOAD_DOCUMENT,
    )
    asyncio.create_task(runner.run(some_coro(), label="board analysis"))

Usage (without job tracking — legacy)::

    runner = BackgroundTaskRunner(context.bot, update.message.chat_id)
    asyncio.create_task(runner.run(some_coro(), label="board analysis"))
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..utils.telegram_formatting import format_telegram_message

if TYPE_CHECKING:
    from ..bot.working_message import WorkingMessage

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 4000
_CHAT_ACTION_INTERVAL = 4  # seconds — Telegram shows action for ~5s


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
        thread_id: int | None = None,
        chat_action=None,
        run_again_markup=None,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._job_store = job_store
        self._job_id = job_id
        self._working_message = working_message
        self._thread_id = thread_id
        self._chat_action = chat_action
        self._run_again_markup = run_again_markup

    async def _chat_action_heartbeat(self) -> None:
        """Send chat_action every _CHAT_ACTION_INTERVAL until cancelled."""
        if self._chat_action is None:
            return
        try:
            while True:
                try:
                    kwargs = {}
                    if self._thread_id is not None:
                        kwargs["message_thread_id"] = self._thread_id
                    await self._bot.send_chat_action(
                        self._chat_id,
                        self._chat_action,
                        **kwargs,
                    )
                except Exception as e:
                    logger.debug("Chat action heartbeat failed: %s", e)
                await asyncio.sleep(_CHAT_ACTION_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def run(self, coro, *, label: str) -> None:
        """Await *coro* and send its string result to the chat.

        Long results are split into multiple messages at 4 000-character
        boundaries.  Exceptions are logged and a brief failure notice is
        sent to the user so they are never left hanging.

        Job status is updated in the BackgroundJobStore if one was provided.
        If a WorkingMessage was provided, it is stopped before sending results.
        If chat_action is set, a heartbeat sends that action every few seconds
        while the task runs (e.g. UPLOAD_DOCUMENT for long-running reports).
        """
        if self._job_store and self._job_id:
            await self._job_store.set_running(self._job_id)

        heartbeat_task: asyncio.Task | None = None
        if self._chat_action is not None:
            heartbeat_task = asyncio.create_task(self._chat_action_heartbeat())

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
            send_kwargs = {}
            if self._thread_id is not None:
                send_kwargs["message_thread_id"] = self._thread_id
            chunks = [
                result[i : i + _MAX_MESSAGE_LENGTH]
                for i in range(0, len(result), _MAX_MESSAGE_LENGTH)
            ]
            for idx, chunk in enumerate(chunks):
                is_last = idx == len(chunks) - 1
                if is_last and self._run_again_markup is not None:
                    send_kwargs["reply_markup"] = self._run_again_markup
                try:
                    await self._bot.send_message(
                        self._chat_id,
                        format_telegram_message(chunk),
                        parse_mode="MarkdownV2",
                        **send_kwargs,
                    )
                except Exception:
                    await self._bot.send_message(self._chat_id, chunk, **send_kwargs)
                if is_last and self._run_again_markup is not None:
                    send_kwargs.pop("reply_markup", None)
        except Exception:
            logger.exception("Background task %r failed", label)

            # Stop the animated working message on failure too
            if self._working_message:
                await self._working_message.stop()

            if self._job_store and self._job_id:
                await self._job_store.set_failed(
                    self._job_id, "Task failed — see /logs for details"
                )
            send_kwargs = {}
            if self._thread_id is not None:
                send_kwargs["message_thread_id"] = self._thread_id
            await self._bot.send_message(
                self._chat_id,
                f"Sorry, the {label} task failed — check /logs for details.",
                **send_kwargs,
            )
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
