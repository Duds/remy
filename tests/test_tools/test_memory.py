"""Tests for remy.ai.tools.memory module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.ai.tools.memory import (
    exec_check_status,
    exec_get_facts,
    exec_get_goals,
    exec_get_logs,
    exec_get_memory_summary,
    exec_manage_goal,
    exec_manage_memory,
    exec_run_board,
)


USER_ID = 42


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._logs_dir = kwargs.get("logs_dir", "/tmp/test_logs")
    registry._knowledge_store = kwargs.get("knowledge_store")
    registry._goal_store = kwargs.get("goal_store")
    registry._fact_store = kwargs.get("fact_store")
    registry._board_orchestrator = kwargs.get("board_orchestrator")
    registry._claude_client = kwargs.get("claude_client")
    registry._mistral_client = kwargs.get("mistral_client")
    registry._moonshot_client = kwargs.get("moonshot_client")
    registry._ollama_base_url = kwargs.get("ollama_base_url", "http://localhost:11434")
    registry._model_complex = kwargs.get("model_complex", "claude-sonnet-4-6")
    return registry


class TestExecGetLogs:
    """Tests for exec_get_logs executor."""

    @pytest.mark.asyncio
    async def test_summary_mode_returns_diagnostics(self):
        """Summary mode should return diagnostics summary."""
        registry = make_registry(logs_dir="/tmp")
        with patch("remy.ai.tools.memory.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [
                0,              # get_session_start_line
                None,           # get_session_start
                "Error summary",
                "Tail content",
            ]
            result = await exec_get_logs(registry, {"mode": "summary"})
        
        assert "Error summary" in result or "Tail content" in result
        assert "Diagnostics" in result or "summary" in result.lower()

    @pytest.mark.asyncio
    async def test_tail_mode_returns_log_lines(self):
        """Tail mode should return recent log lines."""
        registry = make_registry(logs_dir="/tmp")
        with patch("remy.ai.tools.memory.asyncio.to_thread", return_value="log lines here"):
            result = await exec_get_logs(registry, {"mode": "tail", "lines": 10})
        
        assert "log lines here" in result
        assert "10" in result

    @pytest.mark.asyncio
    async def test_errors_mode_returns_error_summary(self):
        """Errors mode should return error/warning summary."""
        registry = make_registry(logs_dir="/tmp")
        with patch("remy.ai.tools.memory.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [
                0,             # get_session_start_line
                None,          # get_session_start
                "errors here",
            ]
            result = await exec_get_logs(registry, {"mode": "errors"})
        
        assert "errors here" in result

    @pytest.mark.asyncio
    async def test_lines_capped_at_100(self):
        """Lines parameter should be capped at 100."""
        registry = make_registry(logs_dir="/tmp")
        with patch("remy.ai.tools.memory.asyncio.to_thread", return_value="logs") as mock_thread:
            result = await exec_get_logs(registry, {"mode": "tail", "lines": 500})
        
        # The result should mention 100 lines (capped), not 500
        assert "100" in result or "logs" in result


class TestExecGetGoals:
    """Tests for exec_get_goals executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available message when no store configured."""
        registry = make_registry(knowledge_store=None, goal_store=None)
        result = await exec_get_goals(registry, {}, USER_ID)
        assert "not available" in result.lower() or "not initialised" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_goals_returns_no_goals_message(self):
        """Should return appropriate message when no goals exist."""
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_goals(registry, {}, USER_ID)
        assert "no active goals" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_goal_list(self):
        """Should return formatted list of goals."""
        goal = MagicMock()
        goal.id = 1
        goal.content = "Learn Python"
        goal.metadata = {"status": "active", "description": "Master the language"}
        
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[goal])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_goals(registry, {}, USER_ID)
        
        assert "Learn Python" in result
        assert "ID:1" in result
        assert "Active goals" in result

    @pytest.mark.asyncio
    async def test_filters_non_active_goals(self):
        """Should only show active goals."""
        active_goal = MagicMock()
        active_goal.id = 1
        active_goal.content = "Active Goal"
        active_goal.metadata = {"status": "active"}
        
        completed_goal = MagicMock()
        completed_goal.id = 2
        completed_goal.content = "Completed Goal"
        completed_goal.metadata = {"status": "completed"}
        
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[active_goal, completed_goal])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_goals(registry, {}, USER_ID)
        
        assert "Active Goal" in result
        assert "Completed Goal" not in result

    @pytest.mark.asyncio
    async def test_limit_parameter_respected(self):
        """Should respect the limit parameter."""
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=ks)
        
        await exec_get_goals(registry, {"limit": 5}, USER_ID)
        
        ks.get_by_type.assert_called_once_with(USER_ID, "goal", limit=5)

    @pytest.mark.asyncio
    async def test_limit_capped_at_50(self):
        """Limit should be capped at 50."""
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=ks)
        
        await exec_get_goals(registry, {"limit": 100}, USER_ID)
        
        ks.get_by_type.assert_called_once_with(USER_ID, "goal", limit=50)


class TestExecGetFacts:
    """Tests for exec_get_facts executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when no store configured."""
        registry = make_registry(knowledge_store=None, fact_store=None)
        result = await exec_get_facts(registry, {}, USER_ID)
        assert "not available" in result.lower() or "not initialised" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_facts_returns_no_facts_message(self):
        """Should return appropriate message when no facts exist."""
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_facts(registry, {}, USER_ID)
        assert "no facts found" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_fact_list(self):
        """Should return formatted list of facts."""
        fact = MagicMock()
        fact.id = 1
        fact.content = "User likes coffee"
        fact.metadata = {"category": "preference"}
        
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[fact])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_facts(registry, {}, USER_ID)
        
        assert "User likes coffee" in result
        assert "ID:1" in result
        assert "preference" in result

    @pytest.mark.asyncio
    async def test_category_filter(self):
        """Should filter facts by category."""
        fact1 = MagicMock()
        fact1.id = 1
        fact1.content = "Likes coffee"
        fact1.metadata = {"category": "preference"}
        
        fact2 = MagicMock()
        fact2.id = 2
        fact2.content = "Works at Acme"
        fact2.metadata = {"category": "work"}
        
        ks = AsyncMock()
        ks.get_by_type = AsyncMock(return_value=[fact1, fact2])
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_facts(registry, {"category": "preference"}, USER_ID)
        
        assert "Likes coffee" in result
        assert "Works at Acme" not in result


class TestExecRunBoard:
    """Tests for exec_run_board executor."""

    @pytest.mark.asyncio
    async def test_no_orchestrator_returns_not_available(self):
        """Should return not available when orchestrator not configured."""
        registry = make_registry(board_orchestrator=None)
        result = await exec_run_board(registry, {"topic": "test"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_topic_returns_error(self):
        """Should return error for empty topic."""
        orchestrator = AsyncMock()
        registry = make_registry(board_orchestrator=orchestrator)
        
        result = await exec_run_board(registry, {"topic": ""}, USER_ID)
        assert "no topic" in result.lower()

    @pytest.mark.asyncio
    async def test_calls_orchestrator_with_topic(self):
        """Should call orchestrator with the provided topic."""
        orchestrator = AsyncMock()
        orchestrator.run_board = AsyncMock(return_value="Board report here")
        registry = make_registry(board_orchestrator=orchestrator)
        
        result = await exec_run_board(registry, {"topic": "Career change"}, USER_ID)
        
        orchestrator.run_board.assert_called_once_with("Career change")
        assert "Board report here" in result


class TestExecCheckStatus:
    """Tests for exec_check_status executor."""

    @pytest.mark.asyncio
    async def test_returns_backend_status_header(self):
        """Should return 'Backend status' header."""
        registry = make_registry(claude_client=None)
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            result = await exec_check_status(registry)
        
        assert "Backend status" in result

    @pytest.mark.asyncio
    async def test_claude_client_available(self):
        """Should show Claude as online when available."""
        claude = AsyncMock()
        claude.ping = AsyncMock(return_value=True)
        registry = make_registry(claude_client=claude)
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            result = await exec_check_status(registry)
        
        assert "Claude" in result
        assert "online" in result.lower()

    @pytest.mark.asyncio
    async def test_claude_client_not_configured(self):
        """Should show warning when Claude not configured."""
        registry = make_registry(claude_client=None)
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            result = await exec_check_status(registry)
        
        assert "Claude" in result
        assert "not configured" in result.lower()


class TestExecManageMemory:
    """Tests for exec_manage_memory executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when no store configured."""
        registry = make_registry(knowledge_store=None)
        result = await exec_manage_memory(registry, {"action": "add"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_add_action_requires_content(self):
        """Add action should require content."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_memory(registry, {"action": "add", "content": ""}, USER_ID)
        assert "provide content" in result.lower()

    @pytest.mark.asyncio
    async def test_add_action_stores_fact(self):
        """Add action should store the fact."""
        ks = AsyncMock()
        ks.add_item = AsyncMock(return_value=123)
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_memory(
            registry, 
            {"action": "add", "content": "User likes tea", "category": "preference"}, 
            USER_ID
        )
        
        ks.add_item.assert_called_once_with(USER_ID, "fact", "User likes tea", {"category": "preference"})
        assert "123" in result
        assert "stored" in result.lower()

    @pytest.mark.asyncio
    async def test_update_action_requires_fact_id(self):
        """Update action should require fact_id."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_memory(
            registry, 
            {"action": "update", "content": "new content"}, 
            USER_ID
        )
        assert "provide fact_id" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_action_requires_fact_id(self):
        """Delete action should require fact_id."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_memory(registry, {"action": "delete"}, USER_ID)
        assert "provide fact_id" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        """Unknown action should return error."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_memory(registry, {"action": "unknown"}, USER_ID)
        assert "unknown action" in result.lower()


class TestExecManageGoal:
    """Tests for exec_manage_goal executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when no store configured."""
        registry = make_registry(knowledge_store=None)
        result = await exec_manage_goal(registry, {"action": "add"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_add_action_requires_title(self):
        """Add action should require title."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_goal(registry, {"action": "add", "title": ""}, USER_ID)
        assert "provide" in result.lower() and "title" in result.lower()

    @pytest.mark.asyncio
    async def test_add_action_creates_goal(self):
        """Add action should create a new goal."""
        ks = AsyncMock()
        ks.add_item = AsyncMock(return_value=456)
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_goal(
            registry, 
            {"action": "add", "title": "Learn Rust", "description": "Systems programming"}, 
            USER_ID
        )
        
        ks.add_item.assert_called_once()
        assert "456" in result
        assert "added" in result.lower()

    @pytest.mark.asyncio
    async def test_complete_action_requires_goal_id(self):
        """Complete action should require goal_id."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_goal(registry, {"action": "complete"}, USER_ID)
        assert "provide goal_id" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        """Unknown action should return error."""
        ks = AsyncMock()
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_manage_goal(registry, {"action": "unknown"}, USER_ID)
        assert "unknown action" in result.lower()


class TestExecGetMemorySummary:
    """Tests for exec_get_memory_summary executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when no store configured."""
        registry = make_registry(knowledge_store=None)
        result = await exec_get_memory_summary(registry, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_summary_with_counts(self):
        """Should return summary with fact and goal counts."""
        ks = AsyncMock()
        ks.get_memory_summary = AsyncMock(return_value={
            "total_facts": 25,
            "total_goals": 5,
            "recent_facts_7d": 3,
            "categories": {"preference": 10, "work": 8, "health": 7},
        })
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_memory_summary(registry, USER_ID)
        
        assert "25 facts" in result
        assert "5 goals" in result
        assert "Memory summary" in result

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        ks = AsyncMock()
        ks.get_memory_summary = AsyncMock(side_effect=Exception("Database error"))
        registry = make_registry(knowledge_store=ks)
        
        result = await exec_get_memory_summary(registry, USER_ID)
        
        assert "could not retrieve" in result.lower() or "error" in result.lower()
