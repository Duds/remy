"""Tests for remy.ai.tools.analytics module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.analytics import (
    exec_consolidate_memory,
    exec_generate_retrospective,
    exec_get_goal_status,
    exec_get_stats,
    exec_list_background_jobs,
)


USER_ID = 42


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._conversation_analyzer = kwargs.get("conversation_analyzer")
    registry._claude_client = kwargs.get("claude_client")
    registry._job_store = kwargs.get("job_store")
    
    if "proactive_scheduler" in kwargs:
        registry._scheduler_ref = {"proactive_scheduler": kwargs["proactive_scheduler"]}
        registry._proactive_scheduler = kwargs["proactive_scheduler"]
    else:
        registry._scheduler_ref = {}
        registry._proactive_scheduler = None
    
    return registry


class TestExecGetStats:
    """Tests for exec_get_stats executor."""

    @pytest.mark.asyncio
    async def test_no_analyzer_returns_not_available(self):
        """Should return not available when analyzer not configured."""
        registry = make_registry(conversation_analyzer=None)
        result = await exec_get_stats(registry, {}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        analyzer = AsyncMock()
        analyzer.get_stats = AsyncMock(return_value={
            "total_messages": 150,
            "total_tokens": 50000,
        })
        analyzer.format_stats_message = MagicMock(return_value="Stats: 150 messages")
        registry = make_registry(conversation_analyzer=analyzer)
        
        result = await exec_get_stats(registry, {"period": "30d"}, USER_ID)
        assert isinstance(result, str)


class TestExecGetGoalStatus:
    """Tests for exec_get_goal_status executor."""

    @pytest.mark.asyncio
    async def test_no_analyzer_returns_not_available(self):
        """Should return not available when analyzer not configured."""
        registry = make_registry(conversation_analyzer=None)
        result = await exec_get_goal_status(registry, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        analyzer = AsyncMock()
        analyzer.get_active_goals_with_age = AsyncMock(return_value=[])
        analyzer.get_completed_goals_since = AsyncMock(return_value=[])
        analyzer.format_goal_status_message = MagicMock(return_value="Active: 0")
        registry = make_registry(conversation_analyzer=analyzer)
        
        result = await exec_get_goal_status(registry, USER_ID)
        assert isinstance(result, str)


class TestExecGenerateRetrospective:
    """Tests for exec_generate_retrospective executor."""

    @pytest.mark.asyncio
    async def test_no_analyzer_returns_not_available(self):
        """Should return not available when analyzer not configured."""
        registry = make_registry(conversation_analyzer=None)
        result = await exec_generate_retrospective(registry, {}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_no_claude_returns_not_available(self):
        """Should return not available when Claude client not configured."""
        analyzer = AsyncMock()
        registry = make_registry(conversation_analyzer=analyzer, claude_client=None)
        
        result = await exec_generate_retrospective(registry, {}, USER_ID)
        assert "not available" in result.lower()


class TestExecConsolidateMemory:
    """Tests for exec_consolidate_memory executor."""

    @pytest.mark.asyncio
    async def test_no_scheduler_returns_not_available(self):
        """Should return not available when scheduler not configured."""
        registry = make_registry(proactive_scheduler=None)
        result = await exec_consolidate_memory(registry, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        scheduler = AsyncMock()
        scheduler.run_memory_consolidation_now = AsyncMock(return_value={
            "status": "success",
            "facts_stored": 5,
            "goals_stored": 2,
        })
        registry = make_registry(proactive_scheduler=scheduler)
        
        result = await exec_consolidate_memory(registry, USER_ID)
        assert isinstance(result, str)


class TestExecListBackgroundJobs:
    """Tests for exec_list_background_jobs executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when job store not configured."""
        registry = make_registry(job_store=None)
        result = await exec_list_background_jobs(registry, {}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        store = AsyncMock()
        store.list_recent = AsyncMock(return_value=[])
        registry = make_registry(job_store=store)
        
        result = await exec_list_background_jobs(registry, {}, USER_ID)
        assert isinstance(result, str)
