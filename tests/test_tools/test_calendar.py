"""Tests for remy.ai.tools.calendar module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.calendar import exec_calendar_events, exec_create_calendar_event


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._calendar = kwargs.get("calendar")
    return registry


class TestExecCalendarEvents:
    """Tests for exec_calendar_events executor."""

    @pytest.mark.asyncio
    async def test_no_calendar_returns_not_configured(self):
        """Should return not configured when calendar not set up."""
        registry = make_registry(calendar=None)
        result = await exec_calendar_events(registry, {})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        calendar = AsyncMock()
        calendar.list_events = AsyncMock(return_value=[])
        registry = make_registry(calendar=calendar)
        
        result = await exec_calendar_events(registry, {})
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_handles_calendar_error(self):
        """Should handle calendar API errors gracefully."""
        calendar = AsyncMock()
        calendar.list_events = AsyncMock(side_effect=Exception("API Error"))
        registry = make_registry(calendar=calendar)
        
        result = await exec_calendar_events(registry, {})
        
        assert "error" in result.lower() or "could not" in result.lower()


class TestExecCreateCalendarEvent:
    """Tests for exec_create_calendar_event executor."""

    @pytest.mark.asyncio
    async def test_no_calendar_returns_not_configured(self):
        """Should return not configured when calendar not set up."""
        registry = make_registry(calendar=None)
        result = await exec_create_calendar_event(registry, {"summary": "Test"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_summary(self):
        """Should require a summary/title."""
        calendar = AsyncMock()
        registry = make_registry(calendar=calendar)
        
        result = await exec_create_calendar_event(registry, {"summary": ""})
        assert "provide" in result.lower() or "required" in result.lower() or "title" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        calendar = AsyncMock()
        registry = make_registry(calendar=calendar)
        
        result = await exec_create_calendar_event(registry, {"summary": "Meeting"})
        assert isinstance(result, str)
