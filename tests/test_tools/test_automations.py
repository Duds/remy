"""Tests for remy.ai.tools.automations module."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.automations import (
    exec_breakdown_task,
    exec_grocery_list,
    exec_list_reminders,
    exec_remove_reminder,
    exec_schedule_reminder,
    exec_set_one_time_reminder,
)


USER_ID = 42

# Generate fixtures in local AEST/AEDT time — the executor treats naive datetimes
# as Australia/Canberra, so UTC-based offsets would be misinterpreted.
_LOCAL_TZ = ZoneInfo("Australia/Canberra")
_FUTURE_LOCAL = (datetime.now(_LOCAL_TZ) + timedelta(hours=12)).strftime(
    "%Y-%m-%dT%H:%M:%S"
)
_PAST_LOCAL = (datetime.now(_LOCAL_TZ) - timedelta(hours=1)).strftime(
    "%Y-%m-%dT%H:%M:%S"
)


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._automation_store = kwargs.get("automation_store")
    registry._scheduler_ref = kwargs.get("scheduler_ref", {})
    registry._claude_client = kwargs.get("claude_client")
    registry._knowledge_store = kwargs.get("knowledge_store")
    return registry


class TestExecScheduleReminder:
    """Tests for exec_schedule_reminder executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        registry = make_registry(automation_store=None)
        result = await exec_schedule_reminder(registry, {"label": "Test"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_label(self):
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        result = await exec_schedule_reminder(registry, {"label": ""}, USER_ID)
        assert "provide" in result.lower() or "label" in result.lower()

    @pytest.mark.asyncio
    async def test_daily_reminder_created(self):
        store = AsyncMock()
        store.add = AsyncMock(return_value=123)
        registry = make_registry(automation_store=store)

        result = await exec_schedule_reminder(
            registry,
            {
                "label": "Daily standup",
                "frequency": "daily",
                "time": "09:00",
            },
            USER_ID,
        )

        assert "123" in result
        assert "daily" in result.lower()
        store.add.assert_called_once_with(
            USER_ID, "Daily standup", "0 9 * * *", mediated=False
        )

    @pytest.mark.asyncio
    async def test_weekly_reminder_includes_day(self):
        store = AsyncMock()
        store.add = AsyncMock(return_value=7)
        registry = make_registry(automation_store=store)

        result = await exec_schedule_reminder(
            registry,
            {
                "label": "Weekly review",
                "frequency": "weekly",
                "time": "10:00",
                "day": "fri",
            },
            USER_ID,
        )

        assert "Friday" in result

    @pytest.mark.asyncio
    async def test_mediated_reminder_passes_flag(self):
        store = AsyncMock()
        store.add = AsyncMock(return_value=99)
        sched = MagicMock()
        registry = make_registry(
            automation_store=store, scheduler_ref={"proactive_scheduler": sched}
        )

        result = await exec_schedule_reminder(
            registry,
            {
                "label": "Sobriety check",
                "frequency": "daily",
                "time": "17:00",
                "mediated": True,
            },
            USER_ID,
        )

        assert "99" in result
        assert "mediated" in result.lower()
        store.add.assert_called_once_with(
            USER_ID, "Sobriety check", "0 17 * * *", mediated=True
        )
        sched.add_automation.assert_called_once_with(
            99, USER_ID, "Sobriety check", "0 17 * * *", mediated=True
        )


class TestExecListReminders:
    """Tests for exec_list_reminders executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        registry = make_registry(automation_store=None)
        result = await exec_list_reminders(registry, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_list(self):
        store = AsyncMock()
        store.get_all = AsyncMock(return_value=[])
        registry = make_registry(automation_store=store)

        result = await exec_list_reminders(registry, USER_ID)
        assert "no reminders" in result.lower()

    @pytest.mark.asyncio
    async def test_recurring_reminder_format(self):
        store = AsyncMock()
        store.get_all = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "label": "Daily standup",
                    "cron": "0 9 * * *",
                    "fire_at": None,
                    "last_run_at": None,
                    "mediated": 0,
                }
            ]
        )
        registry = make_registry(automation_store=store)

        result = await exec_list_reminders(registry, USER_ID)
        assert "[ID 1]" in result
        assert "direct" in result
        assert "Daily standup" in result
        assert "daily" in result.lower()
        assert "09:00" in result

    @pytest.mark.asyncio
    async def test_one_time_reminder_shows_friendly_time(self):
        store = AsyncMock()
        store.get_all = AsyncMock(
            return_value=[
                {
                    "id": 5,
                    "label": "Call dentist",
                    "cron": "",
                    "fire_at": "2026-03-15T10:30:00",
                    "last_run_at": None,
                    "mediated": 0,
                }
            ]
        )
        registry = make_registry(automation_store=store)

        result = await exec_list_reminders(registry, USER_ID)
        assert "[ID 5]" in result
        assert "Call dentist" in result
        assert "once" in result.lower()
        # Should show friendly format, not raw ISO
        assert "2026-03-15T10:30:00" not in result
        assert "10:30" in result


class TestExecRemoveReminder:
    """Tests for exec_remove_reminder executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        registry = make_registry(automation_store=None)
        result = await exec_remove_reminder(registry, {"id": 1}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_id(self):
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        result = await exec_remove_reminder(registry, {}, USER_ID)
        assert "provide" in result.lower() or "id" in result.lower()

    @pytest.mark.asyncio
    async def test_removes_existing_reminder(self):
        store = AsyncMock()
        store.remove = AsyncMock(return_value=True)
        registry = make_registry(automation_store=store)

        result = await exec_remove_reminder(registry, {"id": 3}, USER_ID)
        assert "3" in result
        store.remove.assert_called_once_with(USER_ID, 3)

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        store = AsyncMock()
        store.remove = AsyncMock(return_value=False)
        registry = make_registry(automation_store=store)

        result = await exec_remove_reminder(registry, {"id": 99}, USER_ID)
        assert "99" in result
        assert "not found" in result.lower() or "no reminder" in result.lower()


class TestExecSetOneTimeReminder:
    """Tests for exec_set_one_time_reminder executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        registry = make_registry(automation_store=None)
        result = await exec_set_one_time_reminder(registry, {"label": "Test"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_label(self):
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        result = await exec_set_one_time_reminder(
            registry, {"label": "", "fire_at": _FUTURE_LOCAL}, USER_ID
        )
        assert "label" in result.lower() or "provide" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_fire_at(self):
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        result = await exec_set_one_time_reminder(
            registry, {"label": "Call dentist", "fire_at": ""}, USER_ID
        )
        assert "fire_at" in result.lower() or "provide" in result.lower()

    @pytest.mark.asyncio
    async def test_invalid_fire_at_format(self):
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        result = await exec_set_one_time_reminder(
            registry, {"label": "Test", "fire_at": "not-a-date"}, USER_ID
        )
        assert "invalid" in result.lower() or "format" in result.lower()

    @pytest.mark.asyncio
    async def test_past_time_rejected(self):
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        result = await exec_set_one_time_reminder(
            registry, {"label": "Already gone", "fire_at": _PAST_LOCAL}, USER_ID
        )
        assert "past" in result.lower()

    @pytest.mark.asyncio
    async def test_creates_reminder_with_future_time(self):
        store = AsyncMock()
        store.add = AsyncMock(return_value=42)
        registry = make_registry(automation_store=store)

        result = await exec_set_one_time_reminder(
            registry, {"label": "Call dentist", "fire_at": _FUTURE_LOCAL}, USER_ID
        )

        assert "42" in result
        assert "Call dentist" in result
        store.add.assert_called_once_with(
            USER_ID, "Call dentist", cron="", fire_at=_FUTURE_LOCAL
        )

    @pytest.mark.asyncio
    async def test_confirmation_shows_friendly_time(self):
        store = AsyncMock()
        store.add = AsyncMock(return_value=5)
        registry = make_registry(automation_store=store)

        result = await exec_set_one_time_reminder(
            registry,
            {"label": "Stand up and stretch", "fire_at": "2026-06-01T14:30:00"},
            USER_ID,
        )

        # Confirmation should include formatted time, not raw ISO string
        assert "2026-06-01T14:30:00" not in result
        assert "14:30" in result


class TestExecBreakdownTask:
    """Tests for exec_breakdown_task executor."""

    @pytest.mark.asyncio
    async def test_requires_task(self):
        registry = make_registry()
        result = await exec_breakdown_task(registry, {"task": ""})
        assert "provide" in result.lower() or "task" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value="1. Step one\n2. Step two")
        registry = make_registry(claude_client=claude)

        result = await exec_breakdown_task(registry, {"task": "Plan a party"})
        assert isinstance(result, str)


class TestExecGroceryList:
    """Tests for exec_grocery_list executor."""

    @pytest.mark.asyncio
    async def test_no_knowledge_store_returns_requires_memory(self):
        registry = make_registry(knowledge_store=None)
        result = await exec_grocery_list(registry, {"action": "show"}, USER_ID)
        assert "requires memory" in result.lower()

    @pytest.mark.asyncio
    async def test_no_user_id_returns_requires_memory(self):
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        result = await exec_grocery_list(registry, {"action": "show"}, 0)
        assert "requires memory" in result.lower()

    @pytest.mark.asyncio
    async def test_show_action_returns_string(self):
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=ks)

        result = await exec_grocery_list(registry, {"action": "show"}, USER_ID)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_add_action_requires_items(self):
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)

        result = await exec_grocery_list(
            registry, {"action": "add", "items": ""}, USER_ID
        )
        assert "specify" in result.lower() or "provide" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)

        result = await exec_grocery_list(registry, {"action": "unknown"}, USER_ID)
        assert "unknown" in result.lower()
