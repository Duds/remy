"""Tests for remy.ai.tools.automations module."""

from __future__ import annotations

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


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._automation_store = kwargs.get("automation_store")
    registry._scheduler_ref = kwargs.get("scheduler_ref", {})
    registry._claude_client = kwargs.get("claude_client")
    registry._knowledge_store = kwargs.get("knowledge_store")
    registry._grocery_list_file = kwargs.get("grocery_list_file", "")
    return registry


class TestExecScheduleReminder:
    """Tests for exec_schedule_reminder executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when automation store not configured."""
        registry = make_registry(automation_store=None)
        result = await exec_schedule_reminder(registry, {"label": "Test"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_label(self):
        """Should require a reminder label."""
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        
        result = await exec_schedule_reminder(registry, {"label": ""}, USER_ID)
        assert "provide" in result.lower() or "label" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        store = AsyncMock()
        store.add_reminder = AsyncMock(return_value=123)
        registry = make_registry(automation_store=store)
        
        result = await exec_schedule_reminder(registry, {
            "label": "Daily standup",
            "time": "09:00",
            "days": "mon,tue,wed,thu,fri",
        }, USER_ID)
        
        assert isinstance(result, str)


class TestExecListReminders:
    """Tests for exec_list_reminders executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when automation store not configured."""
        registry = make_registry(automation_store=None)
        result = await exec_list_reminders(registry, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        store = AsyncMock()
        store.get_reminders = AsyncMock(return_value=[])
        registry = make_registry(automation_store=store)
        
        result = await exec_list_reminders(registry, USER_ID)
        assert isinstance(result, str)


class TestExecRemoveReminder:
    """Tests for exec_remove_reminder executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when automation store not configured."""
        registry = make_registry(automation_store=None)
        result = await exec_remove_reminder(registry, {"reminder_id": 1}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_reminder_id(self):
        """Should require a reminder ID."""
        store = AsyncMock()
        registry = make_registry(automation_store=store)
        
        result = await exec_remove_reminder(registry, {"reminder_id": None}, USER_ID)
        assert "provide" in result.lower() or "id" in result.lower()


class TestExecSetOneTimeReminder:
    """Tests for exec_set_one_time_reminder executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when automation store not configured."""
        registry = make_registry(automation_store=None)
        result = await exec_set_one_time_reminder(registry, {"message": "Test"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        store = AsyncMock()
        store.add_one_time_reminder = AsyncMock(return_value=456)
        registry = make_registry(automation_store=store)
        
        result = await exec_set_one_time_reminder(registry, {
            "message": "Call dentist",
            "minutes": 30,
        }, USER_ID)
        
        assert isinstance(result, str)


class TestExecBreakdownTask:
    """Tests for exec_breakdown_task executor."""

    @pytest.mark.asyncio
    async def test_requires_task(self):
        """Should require a task description."""
        registry = make_registry()
        result = await exec_breakdown_task(registry, {"task": ""})
        assert "provide" in result.lower() or "task" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value="1. Step one\n2. Step two")
        registry = make_registry(claude_client=claude)
        
        result = await exec_breakdown_task(registry, {"task": "Plan a party"})
        assert isinstance(result, str)


class TestExecGroceryList:
    """Tests for exec_grocery_list executor."""

    @pytest.mark.asyncio
    async def test_show_action_returns_string(self):
        """Should return a string result for show action."""
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_grocery_list(registry, {"action": "show"}, USER_ID)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_add_action_requires_items(self):
        """Should require items to add."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_grocery_list(registry, {"action": "add", "items": ""}, USER_ID)
        assert "specify" in result.lower() or "provide" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        """Should return error for unknown action."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_grocery_list(registry, {"action": "unknown"}, USER_ID)
        assert "unknown" in result.lower()
