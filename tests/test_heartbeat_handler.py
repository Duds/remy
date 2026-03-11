"""Tests for HeartbeatHandler (SAD v7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy import config
from remy.bot.heartbeat_handler import HeartbeatHandler, _filter_reminders_for_heartbeat


def test_filter_reminders_excludes_one_time_more_than_3_days_future():
    """One-time reminders >3 days in future are excluded (Bug 46)."""
    rows = [
        {"id": 1, "label": "Jane's dad anniversary", "fire_at": "2026-03-26T09:00:00", "cron": ""},
        {"id": 2, "label": "Meeting", "fire_at": None, "cron": "0 9 * * 1-5"},
    ]
    # Today 2026-03-11; 26 March is 15 days away
    result = _filter_reminders_for_heartbeat(rows, "2026-03-11")
    assert len(result) == 1
    assert result[0]["id"] == 2
    assert result[0]["label"] == "Meeting"


def test_filter_reminders_includes_one_time_today():
    """One-time reminders for today are included."""
    rows = [
        {"id": 1, "label": "Anniversary", "fire_at": "2026-03-11T09:00:00", "cron": ""},
    ]
    result = _filter_reminders_for_heartbeat(rows, "2026-03-11")
    assert len(result) == 1
    assert result[0]["label"] == "Anniversary"


def test_filter_reminders_includes_one_time_within_3_days():
    """One-time reminders within 3 days are included."""
    rows = [
        {"id": 1, "label": "Tomorrow", "fire_at": "2026-03-12T09:00:00", "cron": ""},
        {"id": 2, "label": "In 3 days", "fire_at": "2026-03-14T09:00:00", "cron": ""},
    ]
    result = _filter_reminders_for_heartbeat(rows, "2026-03-11")
    assert len(result) == 2


def test_filter_reminders_excludes_one_time_4_days_future():
    """One-time reminders 4+ days in future are excluded."""
    rows = [
        {"id": 1, "label": "In 4 days", "fire_at": "2026-03-15T09:00:00", "cron": ""},
    ]
    result = _filter_reminders_for_heartbeat(rows, "2026-03-11")
    assert len(result) == 0


def test_filter_reminders_recurring_always_included():
    """Recurring reminders (no fire_at) are always included."""
    rows = [
        {"id": 1, "label": "Daily standup", "fire_at": None, "cron": "0 9 * * *"},
    ]
    result = _filter_reminders_for_heartbeat(rows, "2026-03-11")
    assert len(result) == 1


def test_filter_reminders_bad_today_returns_all():
    """Invalid today_iso returns rows unfiltered (fail-open)."""
    rows = [{"id": 1, "label": "X", "fire_at": "2026-03-26T09:00:00", "cron": ""}]
    result = _filter_reminders_for_heartbeat(rows, "invalid")
    assert len(result) == 1


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
async def test_handler_filters_future_reminders_from_items_checked():
    """Reminders >3 days in future are excluded from context (Bug 46)."""
    automation = AsyncMock()
    automation.get_all = AsyncMock(
        return_value=[
            {"id": 1, "label": "Jane's dad anniversary", "fire_at": "2026-03-26T09:00:00", "cron": ""},
            {"id": 2, "label": "Meeting tomorrow", "fire_at": "2026-03-12T09:00:00", "cron": ""},
        ]
    )
    claude = AsyncMock()
    claude.complete = AsyncMock(return_value="HEARTBEAT_OK")
    handler = HeartbeatHandler(
        automation_store=automation,
        claude_client=claude,
        outbound_queue=None,
        bot=None,
    )
    result = await handler.run(
        user_id=1,
        chat_id=12345,
        config_text="Evaluate.",
        current_local_time="2026-03-11 10:00 AEDT (day of week: Wednesday)",
    )
    reminders = result.items_checked.get("reminders", "")
    assert "Meeting tomorrow" in reminders
    assert "Jane's dad anniversary" not in reminders


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
