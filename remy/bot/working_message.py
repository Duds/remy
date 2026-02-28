"""
Animated SimCity-style "working" placeholder for long-running operations.

Cycles through entertaining phrases via editMessageText while the bot is
processing Board of Directors, research, or retrospective requests.

Usage::

    wm = WorkingMessage(context.bot, update.effective_chat.id)
    await wm.start()
    try:
        result = await long_operation(...)
    finally:
        await wm.stop()

    await update.message.reply_text(result)
"""

import asyncio
import itertools
import logging
import random

logger = logging.getLogger(__name__)

_PHRASES = [
    "Reticulating splines",
    "Homologating girdles",
    "Consulting the oracle",
    "Polishing the chrome",
    "Herding cats",
    "Aligning the stars",
    "Buffering logic",
    "Generating excuses",
    "Reheating the coffee",
    "Calibrating flux capacitors",
    "Defragmenting the ether",
    "Downloading more RAM",
    "Appeasing the compiler gods",
    "Untangling the time stream",
    "Reversing the polarity",
    "Consulting the runes",
    "Spinning up the hamster wheel",
    "Charging the crystals",
    "Negotiating with the cloud",
    "Warming up the neurons",
    "Bribing the algorithms",
    "Summoning the data spirits",
    "Polishing the pixels",
    "Tuning the quantum harmonics",
    "Feeding the gremlins",
]

_EDIT_INTERVAL = 1.2  # seconds between edits — well under Telegram's rate limit


class WorkingMessage:
    """Animated SimCity-style placeholder that cycles phrases via editMessageText."""

    def __init__(self, bot, chat_id: int, thread_id: int | None = None) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._message_id: int | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Send the initial placeholder and start the animation loop."""
        try:
            msg = await self._bot.send_message(
                self._chat_id,
                "⚙️ …",
                message_thread_id=self._thread_id,
            )
            self._message_id = msg.message_id
            self._task = asyncio.create_task(self._animate())
        except Exception as e:
            logger.debug("WorkingMessage failed to start: %s", e)

    async def stop(self) -> None:
        """Cancel the animation and delete the placeholder message."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._message_id:
            try:
                await self._bot.delete_message(self._chat_id, self._message_id)
            except Exception as e:
                logger.debug("WorkingMessage failed to delete: %s", e)
            self._message_id = None

    async def _animate(self) -> None:
        """Cycle through phrases with a typewriter effect."""
        shuffled = _PHRASES.copy()
        random.shuffle(shuffled)

        for phrase in itertools.cycle(shuffled):
            for suffix in ("▌", "…"):
                try:
                    await self._bot.edit_message_text(
                        f"⚙️ {phrase}{suffix}",
                        self._chat_id,
                        self._message_id,
                    )
                except Exception as e:
                    logger.debug("WorkingMessage edit failed: %s", e)
                await asyncio.sleep(_EDIT_INTERVAL)
