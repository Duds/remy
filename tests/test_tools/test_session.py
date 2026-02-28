"""Tests for remy.ai.tools.session module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.session import (
    exec_compact_conversation,
    exec_delete_conversation,
    exec_end_session,
    exec_help,
    exec_set_proactive_chat,
    exec_start_privacy_audit,
    exec_trigger_reindex,
)


USER_ID = 42


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._automation_store = kwargs.get("automation_store")
    registry._scheduler_ref = kwargs.get("scheduler_ref", {})
    
    if "proactive_scheduler" in kwargs:
        registry._scheduler_ref = {"proactive_scheduler": kwargs["proactive_scheduler"]}
        registry._proactive_scheduler = kwargs["proactive_scheduler"]
    else:
        registry._proactive_scheduler = None
    
    return registry


class TestExecCompactConversation:
    """Tests for exec_compact_conversation executor."""

    @pytest.mark.asyncio
    async def test_returns_command_redirect(self):
        """Should redirect to /compact command."""
        registry = make_registry()
        result = await exec_compact_conversation(registry, USER_ID)
        
        assert "/compact" in result.lower() or "command" in result.lower()


class TestExecDeleteConversation:
    """Tests for exec_delete_conversation executor."""

    @pytest.mark.asyncio
    async def test_returns_command_redirect(self):
        """Should redirect to /delete_conversation command."""
        registry = make_registry()
        result = await exec_delete_conversation(registry, USER_ID)
        
        assert "delete" in result.lower() and "command" in result.lower()


class TestExecSetProactiveChat:
    """Tests for exec_set_proactive_chat executor."""

    @pytest.mark.asyncio
    async def test_no_chat_id_returns_redirect(self):
        """Should redirect to /setmychat when no chat_id provided."""
        registry = make_registry()
        result = await exec_set_proactive_chat(registry, USER_ID, chat_id=None)
        
        assert "/setmychat" in result.lower() or "command" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        result = await exec_set_proactive_chat(registry, USER_ID, chat_id=None)
        assert isinstance(result, str)


class TestExecTriggerReindex:
    """Tests for exec_trigger_reindex executor."""

    @pytest.mark.asyncio
    async def test_no_scheduler_returns_not_available(self):
        """Should return not available when scheduler not configured."""
        registry = make_registry(proactive_scheduler=None)
        result = await exec_trigger_reindex(registry)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result when scheduler configured."""
        scheduler = AsyncMock()
        scheduler.run_file_reindex_now = AsyncMock(return_value={
            "status": "success",
            "files_indexed": 100,
        })
        registry = make_registry(proactive_scheduler=scheduler)
        
        result = await exec_trigger_reindex(registry)
        assert isinstance(result, str)


class TestExecStartPrivacyAudit:
    """Tests for exec_start_privacy_audit executor."""

    @pytest.mark.asyncio
    async def test_returns_privacy_audit_intro(self):
        """Should return privacy audit introduction."""
        registry = make_registry()
        result = await exec_start_privacy_audit(registry)
        
        assert "Privacy Audit" in result or "🔒" in result


class TestExecEndSession:
    """Tests for exec_end_session executor."""

    @pytest.mark.asyncio
    async def test_ends_session(self):
        """Should end session and return confirmation."""
        registry = make_registry()
        result = await exec_end_session(registry, {}, USER_ID)
        
        assert "session" in result.lower() or "ended" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        result = await exec_end_session(registry, {}, USER_ID)
        assert isinstance(result, str)


class TestExecHelp:
    """Tests for exec_help executor."""

    @pytest.mark.asyncio
    async def test_returns_category_list(self):
        """Should return list of tool categories."""
        registry = make_registry()
        result = await exec_help(registry, {}, USER_ID)
        
        assert "Categories" in result or "tools" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        result = await exec_help(registry, {}, USER_ID)
        assert isinstance(result, str)
