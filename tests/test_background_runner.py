"""
Tests for remy/agents/background.py — BackgroundTaskRunner.

All Telegram bot calls are mocked — no real network calls are made.
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from remy.agents.background import BackgroundTaskRunner, _MAX_MESSAGE_LENGTH


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def make_bot(*send_return_values) -> MagicMock:
    """Return a mock bot whose send_message() succeeds."""
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=list(send_return_values) if send_return_values else None)
    return bot


async def ok_coro(result: str = "done"):
    return result


async def failing_coro():
    raise ValueError("something went wrong")


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_run_sends_result_to_chat():
    bot = make_bot()
    runner = BackgroundTaskRunner(bot, chat_id=42)
    await runner.run(ok_coro("hello"), label="test")
    bot.send_message.assert_awaited_once_with(42, "hello", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_run_empty_result_sends_nothing():
    bot = make_bot()
    runner = BackgroundTaskRunner(bot, chat_id=42)
    await runner.run(ok_coro(""), label="test")
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_exception_sends_failure_notice():
    bot = make_bot()
    runner = BackgroundTaskRunner(bot, chat_id=99)
    await runner.run(failing_coro(), label="board analysis")
    bot.send_message.assert_awaited_once()
    call_args = bot.send_message.call_args
    assert call_args[0][0] == 99
    assert "board analysis" in call_args[0][1]
    assert "failed" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_long_result_split_into_multiple_messages():
    # Result just over one message boundary
    long_text = "x" * (_MAX_MESSAGE_LENGTH + 10)
    bot = make_bot()
    runner = BackgroundTaskRunner(bot, chat_id=7)
    await runner.run(ok_coro(long_text), label="test")
    assert bot.send_message.await_count == 2
    first_call = bot.send_message.await_args_list[0]
    second_call = bot.send_message.await_args_list[1]
    assert first_call[0][0] == 7
    assert second_call[0][0] == 7
    # Together they reconstruct the original
    combined = first_call[0][1] + second_call[0][1]
    assert combined == long_text


@pytest.mark.asyncio
async def test_run_result_exactly_max_length_sends_one_message():
    text = "y" * _MAX_MESSAGE_LENGTH
    bot = make_bot()
    runner = BackgroundTaskRunner(bot, chat_id=1)
    await runner.run(ok_coro(text), label="test")
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_task_integration():
    """Verify create_task correctly schedules runner.run and delivers the message."""
    bot = make_bot()
    runner = BackgroundTaskRunner(bot, chat_id=5)
    task = asyncio.create_task(runner.run(ok_coro("result"), label="integration"))
    await task
    bot.send_message.assert_awaited_once_with(5, "result", parse_mode="Markdown")
