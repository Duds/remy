"""Tests for remy/bot/streaming.py — uses mock Telegram Message."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from remy.bot.session import SessionManager
from remy.bot.streaming import StreamingReply, stream_to_telegram


def make_mock_message():
    msg = MagicMock()
    msg.edit_text = AsyncMock()
    msg.chat.send_message = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    return msg


@pytest.mark.asyncio
async def test_finalize_sends_final_text():
    msg = make_mock_message()
    sm = SessionManager()
    streamer = StreamingReply(msg, sm, user_id=1)

    await streamer.feed("Hello")
    await streamer.feed(", world")
    await streamer.finalize()

    # Last edit should not have '…' suffix
    last_call_text = msg.edit_text.call_args[0][0]
    assert "…" not in last_call_text
    assert "Hello, world" in last_call_text


@pytest.mark.asyncio
async def test_cancelled_stops_feeding():
    msg = make_mock_message()
    sm = SessionManager()
    sm.request_cancel(1)
    streamer = StreamingReply(msg, sm, user_id=1)

    await streamer.feed("Should not appear")
    # No edits since cancelled
    msg.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_full_text_accumulates():
    msg = make_mock_message()
    sm = SessionManager()
    streamer = StreamingReply(msg, sm, user_id=1)

    await streamer.feed("A")
    await streamer.feed("B")
    await streamer.feed("C")
    await streamer.finalize()

    assert streamer.full_text == "ABC"


@pytest.mark.asyncio
async def test_stream_to_telegram_returns_full_text():
    msg = make_mock_message()
    sm = SessionManager()

    async def chunks():
        for word in ["Hello", " ", "world"]:
            yield word

    result = await stream_to_telegram(chunks(), msg, sm, user_id=1)
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_stream_to_telegram_cancel_appends_cancelled():
    msg = make_mock_message()
    sm = SessionManager()

    async def chunks():
        sm.request_cancel(1)
        yield "partial"

    result = await stream_to_telegram(chunks(), msg, sm, user_id=1)
    assert "[Cancelled]" in result
