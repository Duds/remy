"""
Live streaming to Telegram via message edits.

Buffers incoming text chunks and edits the bot message every 0.5s or
every 200 chars to stay under Telegram's rate limit (30 edits/min).
Appends '…' suffix while streaming; removes it on completion.
Splits into new messages at the 4096-char Telegram limit.
"""

import asyncio
import logging
from typing import AsyncIterator

from telegram import Message
from telegram.error import BadRequest

from ..bot.session import SessionManager

logger = logging.getLogger(__name__)

_TELEGRAM_MAX_LEN = 4000  # leave buffer below 4096 hard limit
_FLUSH_INTERVAL = 0.5     # seconds between Telegram edits
_FLUSH_CHARS = 200         # also flush after this many new chars


class StreamingReply:
    """
    Manages a live-updating Telegram message during a streamed response.

    Usage:
        streamer = StreamingReply(sent_message, session_manager, user_id)
        async for chunk in router.stream(...):
            await streamer.feed(chunk)
        await streamer.finalize()
    """

    def __init__(
        self,
        message: Message,
        session_manager: SessionManager,
        user_id: int,
        thread_id: int | None = None,
    ) -> None:
        self._message = message
        self._session = session_manager
        self._user_id = user_id
        self._thread_id = thread_id

        self._accumulated = ""   # all text received so far for current message
        self._last_sent = ""     # last text successfully sent to Telegram
        self._pending_chars = 0  # chars accumulated since last flush
        self._last_flush = asyncio.get_event_loop().time()
        self._messages: list[Message] = [message]  # overflow messages

    async def feed(self, chunk: str) -> None:
        """Receive a new text chunk and flush to Telegram if needed."""
        if self._session.is_cancelled(self._user_id):
            return

        self._accumulated += chunk
        self._pending_chars += len(chunk)

        now = asyncio.get_event_loop().time()
        time_elapsed = now - self._last_flush >= _FLUSH_INTERVAL
        chars_elapsed = self._pending_chars >= _FLUSH_CHARS

        if time_elapsed or chars_elapsed:
            await self._flush(in_progress=True)

    async def finalize(self) -> None:
        """Send the final accumulated text without the '…' suffix."""
        await self._flush(in_progress=False)

    async def _flush(self, in_progress: bool) -> None:
        """Edit the current Telegram message with accumulated text."""
        text = self._accumulated
        if not text:
            return

        suffix = " …" if in_progress else ""
        display = text + suffix

        # Handle overflow: split at _TELEGRAM_MAX_LEN
        while len(display) > _TELEGRAM_MAX_LEN:
            split_at = display.rfind(" ", 0, _TELEGRAM_MAX_LEN)
            if split_at < 0:
                split_at = _TELEGRAM_MAX_LEN
            part = display[:split_at]
            display = display[split_at:].lstrip()

            await self._edit_or_skip(part)
            # Start a new Telegram message for overflow (preserve thread context)
            try:
                new_msg = await self._message.chat.send_message(
                    "…", message_thread_id=self._thread_id
                )
                self._messages.append(new_msg)
                self._message = new_msg
                self._last_sent = ""
            except Exception as e:
                logger.warning("Could not create overflow message: %s", e)

        if display == self._last_sent:
            return  # no change — Telegram would reject identical edit

        await self._edit_or_skip(display)
        self._pending_chars = 0
        self._last_flush = asyncio.get_event_loop().time()

    async def _edit_or_skip(self, text: str) -> None:
        """Edit the current message with MarkdownV2 formatting."""
        from ..utils.telegram_formatting import format_telegram_message
        
        formatted = format_telegram_message(text)
        try:
            await self._message.edit_text(formatted, parse_mode="MarkdownV2")
            self._last_sent = text
        except BadRequest as e:
            err = str(e).lower()
            if "message is not modified" in err:
                return
            # If MarkdownV2 fails (e.g. unbalanced), fallback to plain text escaping
            try:
                await self._message.edit_text(text)
                self._last_sent = text
            except BadRequest:
                pass
            else:
                logger.debug("Telegram BadRequest on edit: %s", e)
        except Exception as e:
            logger.debug("Could not edit message: %s", e)

    @property
    def full_text(self) -> str:
        """The complete accumulated response text."""
        return self._accumulated


async def stream_to_telegram(
    chunks: AsyncIterator[str],
    initial_message: Message,
    session_manager: SessionManager,
    user_id: int,
    thread_id: int | None = None,
) -> str:
    """
    Helper that streams all chunks to Telegram and returns the full response.
    """
    streamer = StreamingReply(initial_message, session_manager, user_id, thread_id)
    async for chunk in chunks:
        await streamer.feed(chunk)
        if session_manager.is_cancelled(user_id):
            await streamer.finalize()
            return streamer.full_text + "\n\n[Cancelled]"
    await streamer.finalize()
    return streamer.full_text
