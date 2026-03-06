"""Tests for delivery: send_via_queue_or_bot, OutboundQueue enqueue (SAD v7)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.delivery.queue import OutboundQueue, QueueStatus
from remy.delivery.send import send_via_queue_or_bot
from remy.memory.database import DatabaseManager


@pytest.fixture
async def temp_db(tmp_path):
    """Create a real DB with schema (so outbound_queue and heartbeat_log exist)."""
    db_path = str(tmp_path / "remy.db")
    db = DatabaseManager(db_path=db_path)
    await db.init()
    yield db_path
    # no need to close; tests use path only for OutboundQueue


@pytest.mark.asyncio
async def test_send_via_queue_enqueues_when_queue_and_bot_set(temp_db):
    """When queue and bot are set, message is enqueued and returns True."""
    queue = OutboundQueue(db_path=temp_db, bot=None)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    ok = await send_via_queue_or_bot(queue=queue, bot=bot, chat_id=12345, text="Hello")
    assert ok is True
    bot.send_message.assert_not_called()
    pending = await queue.get_pending(limit=5)
    assert len(pending) == 1
    assert pending[0].message_text == "Hello"
    assert pending[0].chat_id == "12345"


@pytest.mark.asyncio
async def test_send_via_queue_fallback_to_bot_when_queue_none():
    """When queue is None, sends via bot and returns True."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    ok = await send_via_queue_or_bot(queue=None, bot=bot, chat_id=999, text="Fallback")
    assert ok is True
    bot.send_message.assert_called_once_with(chat_id=999, text="Fallback", parse_mode=None)


@pytest.mark.asyncio
async def test_send_via_queue_returns_false_when_both_none():
    ok = await send_via_queue_or_bot(queue=None, bot=None, chat_id=1, text="No op")
    assert ok is False


@pytest.mark.asyncio
async def test_outbound_queue_enqueue_returns_id(temp_db):
    queue = OutboundQueue(db_path=temp_db, bot=None)
    qid = await queue.enqueue(chat_id="123", message_text="Test", message_type="text")
    assert isinstance(qid, int)
    assert qid >= 1
    pending = await queue.get_pending(limit=1)
    assert len(pending) == 1
    assert pending[0].id == qid
    assert pending[0].status == QueueStatus.PENDING
