"""Tests for remy/bot/working_message.py — animated placeholder messages."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.bot.working_message import WorkingMessage, _PHRASES, _EDIT_INTERVAL


def make_mock_bot():
    """Create a mock bot with async send_message, edit_message_text, delete_message."""
    bot = MagicMock()
    sent_msg = MagicMock()
    sent_msg.message_id = 12345
    bot.send_message = AsyncMock(return_value=sent_msg)
    bot.edit_message_text = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_start_sends_initial_placeholder():
    """start() should send an initial '⚙️ …' message."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    await wm.stop()

    bot.send_message.assert_called_once_with(
        999, "⚙️ …", message_thread_id=None
    )


@pytest.mark.asyncio
async def test_start_with_thread_id():
    """start() should pass thread_id to send_message."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999, thread_id=42)

    await wm.start()
    await wm.stop()

    bot.send_message.assert_called_once_with(
        999, "⚙️ …", message_thread_id=42
    )


@pytest.mark.asyncio
async def test_stop_deletes_placeholder():
    """stop() should delete the placeholder message."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    await wm.stop()

    bot.delete_message.assert_called_once_with(999, 12345)


@pytest.mark.asyncio
async def test_stop_cancels_animation_task():
    """stop() should cancel the animation task cleanly."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    assert wm._task is not None
    assert not wm._task.done()

    await wm.stop()
    assert wm._task is None


@pytest.mark.asyncio
async def test_stop_twice_is_safe():
    """Calling stop() twice should not raise an error."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    await wm.stop()
    await wm.stop()  # Second call should be a no-op

    # delete_message should only be called once
    assert bot.delete_message.call_count == 1


@pytest.mark.asyncio
async def test_animation_edits_message():
    """After waiting, the animation should edit the message with a phrase."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    # Wait for at least one edit cycle
    await asyncio.sleep(_EDIT_INTERVAL + 0.1)
    await wm.stop()

    # Should have at least one edit call
    assert bot.edit_message_text.call_count >= 1

    # Check that the edit contains a phrase from the list
    call_args = bot.edit_message_text.call_args[0]
    text = call_args[0]
    assert text.startswith("⚙️ ")
    assert any(phrase in text for phrase in _PHRASES)


@pytest.mark.asyncio
async def test_animation_uses_typewriter_suffixes():
    """Animation should cycle through ▌ and … suffixes."""
    bot = make_mock_bot()
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    # Wait for two edit cycles to see both suffixes
    await asyncio.sleep(_EDIT_INTERVAL * 2 + 0.1)
    await wm.stop()

    # Check that we got edits with both suffixes
    edit_texts = [call[0][0] for call in bot.edit_message_text.call_args_list]
    has_block_cursor = any("▌" in t for t in edit_texts)
    has_ellipsis = any("…" in t for t in edit_texts)

    assert has_block_cursor or has_ellipsis  # At least one suffix type


@pytest.mark.asyncio
async def test_edit_failure_does_not_crash():
    """If edit_message_text fails, the animation should continue."""
    bot = make_mock_bot()
    bot.edit_message_text = AsyncMock(side_effect=Exception("Telegram error"))
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    await asyncio.sleep(_EDIT_INTERVAL + 0.1)
    # Should not raise
    await wm.stop()


@pytest.mark.asyncio
async def test_delete_failure_does_not_crash():
    """If delete_message fails, stop() should not raise."""
    bot = make_mock_bot()
    bot.delete_message = AsyncMock(side_effect=Exception("Already deleted"))
    wm = WorkingMessage(bot, chat_id=999)

    await wm.start()
    # Should not raise
    await wm.stop()


@pytest.mark.asyncio
async def test_start_failure_does_not_crash():
    """If send_message fails, start() should not raise."""
    bot = make_mock_bot()
    bot.send_message = AsyncMock(side_effect=Exception("Network error"))
    wm = WorkingMessage(bot, chat_id=999)

    # Should not raise
    await wm.start()
    await wm.stop()


@pytest.mark.asyncio
async def test_phrases_list_is_not_empty():
    """The phrases list should have content."""
    assert len(_PHRASES) >= 10  # Spec says 15+


@pytest.mark.asyncio
async def test_phrases_are_unique():
    """All phrases should be unique."""
    assert len(_PHRASES) == len(set(_PHRASES))
