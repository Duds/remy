"""Tests for HeartbeatHandler (SAD v7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy import config
from remy.bot.heartbeat_handler import HeartbeatHandler


@pytest.fixture
def handler_no_claude():
    """Handler with no Claude client — always returns HEARTBEAT_OK."""
    return HeartbeatHandler(
        goal_store=None,
        plan_store=None,
        calendar_client=None,
        gmail_client=None,
        automation_store=None,
        claude_client=None,
        outbound_queue=None,
        bot=None,
    )


@pytest.mark.asyncio
async def test_handler_without_claude_returns_heartbeat_ok(handler_no_claude):
    result = await handler_no_claude.run(user_id=1, chat_id=12345, config_text="Check goals.")
    assert result.outcome == "HEARTBEAT_OK"
    assert result.content is None
    assert "goals" in result.items_checked


@pytest.mark.asyncio
async def test_handler_with_claude_heartbeat_ok_response():
    claude = AsyncMock()
    claude.complete = AsyncMock(return_value="HEARTBEAT_OK")
    handler = HeartbeatHandler(claude_client=claude, outbound_queue=None, bot=None)
    result = await handler.run(user_id=1, chat_id=12345, config_text="Evaluate.")
    assert result.outcome == "HEARTBEAT_OK"
    claude.complete.assert_called_once()


@pytest.mark.asyncio
async def test_handler_with_claude_delivered_response():
    claude = AsyncMock()
    claude.complete = AsyncMock(return_value="You have 3 overdue goals. Consider reviewing them.")
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value=1)
    handler = HeartbeatHandler(
        claude_client=claude,
        outbound_queue=queue,
        bot=MagicMock(),
    )
    result = await handler.run(user_id=1, chat_id=12345, config_text="Evaluate.")
    assert result.outcome == "delivered"
    assert result.content is not None
    assert "overdue" in result.content
    queue.enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_handler_includes_moonshot_low_balance_in_items_checked():
    """When moonshot_client has balance below threshold, items_checked includes warning."""
    moonshot = AsyncMock()
    moonshot.get_balance = AsyncMock(return_value=2.5)
    handler = HeartbeatHandler(
        goal_store=None,
        plan_store=None,
        calendar_client=None,
        gmail_client=None,
        automation_store=None,
        counter_store=None,
        claude_client=None,
        outbound_queue=None,
        bot=None,
        moonshot_client=moonshot,
    )
    with patch.object(config.settings, "moonshot_balance_warn_usd", 5.0):
        result = await handler.run(user_id=1, chat_id=12345, config_text="Check.")
    assert "moonshot_credits" in result.items_checked
    assert "2.50" in result.items_checked["moonshot_credits"] or "2.5" in result.items_checked["moonshot_credits"]
    assert "low" in result.items_checked["moonshot_credits"].lower()
