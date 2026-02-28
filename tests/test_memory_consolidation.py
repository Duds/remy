"""
Tests for end-of-day memory consolidation feature.

Covers:
- ConversationStore.get_today_messages()
- ConversationStore.get_messages_since()
- ProactiveScheduler._consolidate_user_memory()
- consolidate_memory tool schema and dispatch
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.memory.conversations import ConversationStore
from remy.models import ConversationTurn


class TestConversationStoreHelpers:
    """Tests for ConversationStore.get_today_messages() and get_messages_since()."""

    @pytest.fixture
    def temp_sessions_dir(self):
        """Create a temporary directory for session files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def conv_store(self, temp_sessions_dir):
        """Create a ConversationStore with a temp directory."""
        return ConversationStore(temp_sessions_dir)

    @pytest.mark.asyncio
    async def test_get_today_messages_empty(self, conv_store):
        """Returns empty list when no sessions exist."""
        result = await conv_store.get_today_messages(user_id=123)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_today_messages_finds_today_session(self, conv_store):
        """Finds and returns turns from today's session."""
        user_id = 123
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        session_key = f"user_{user_id}_{today}"

        turn1 = ConversationTurn(role="user", content="Hello")
        turn2 = ConversationTurn(role="assistant", content="Hi there!")

        await conv_store.append_turn(user_id, session_key, turn1)
        await conv_store.append_turn(user_id, session_key, turn2)

        result = await conv_store.get_today_messages(user_id)
        assert len(result) == 2
        assert result[0].content == "Hello"
        assert result[1].content == "Hi there!"

    @pytest.mark.asyncio
    async def test_get_today_messages_ignores_old_sessions(self, conv_store):
        """Ignores sessions from previous days."""
        user_id = 123
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        today_key = f"user_{user_id}_{today}"
        yesterday_key = f"user_{user_id}_{yesterday}"

        await conv_store.append_turn(
            user_id, today_key, ConversationTurn(role="user", content="Today message")
        )
        await conv_store.append_turn(
            user_id, yesterday_key, ConversationTurn(role="user", content="Yesterday message")
        )

        result = await conv_store.get_today_messages(user_id)
        assert len(result) == 1
        assert result[0].content == "Today message"

    @pytest.mark.asyncio
    async def test_get_today_messages_with_thread_filter(self, conv_store):
        """Filters by thread_id when provided."""
        user_id = 123
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        thread_id = 456

        main_key = f"user_{user_id}_{today}"
        thread_key = f"user_{user_id}_thread_{thread_id}_{today}"

        await conv_store.append_turn(
            user_id, main_key, ConversationTurn(role="user", content="Main chat")
        )
        await conv_store.append_turn(
            user_id, thread_key, ConversationTurn(role="user", content="Thread chat")
        )

        # Without filter — gets both
        all_messages = await conv_store.get_today_messages(user_id)
        assert len(all_messages) == 2

        # With filter — gets only thread
        thread_messages = await conv_store.get_today_messages(user_id, thread_id=thread_id)
        assert len(thread_messages) == 1
        assert thread_messages[0].content == "Thread chat"

    @pytest.mark.asyncio
    async def test_get_messages_since(self, conv_store):
        """Filters turns by timestamp."""
        user_id = 123
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        session_key = f"user_{user_id}_{today}"

        # Create turns with explicit timestamps
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        recent_time = datetime.now(timezone.utc).isoformat()

        old_turn = ConversationTurn(role="user", content="Old message", timestamp=old_time)
        recent_turn = ConversationTurn(role="user", content="Recent message", timestamp=recent_time)

        await conv_store.append_turn(user_id, session_key, old_turn)
        await conv_store.append_turn(user_id, session_key, recent_turn)

        # Get messages since 1 hour ago
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await conv_store.get_messages_since(user_id, since)

        assert len(result) == 1
        assert result[0].content == "Recent message"


class TestConsolidationToolSchema:
    """Tests for consolidate_memory tool schema."""

    def test_tool_schema_exists(self):
        """consolidate_memory tool is in TOOL_SCHEMAS."""
        from remy.ai.tool_registry import TOOL_SCHEMAS

        tool_names = [t["name"] for t in TOOL_SCHEMAS]
        assert "consolidate_memory" in tool_names

    def test_tool_schema_structure(self):
        """consolidate_memory tool has correct schema structure."""
        from remy.ai.tool_registry import TOOL_SCHEMAS

        tool = next(t for t in TOOL_SCHEMAS if t["name"] == "consolidate_memory")

        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"]["required"] == []

    def test_tool_description_mentions_key_features(self):
        """Tool description covers key use cases."""
        from remy.ai.tool_registry import TOOL_SCHEMAS

        tool = next(t for t in TOOL_SCHEMAS if t["name"] == "consolidate_memory")
        desc = tool["description"].lower()

        assert "memory" in desc
        assert "conversation" in desc or "today" in desc
        assert "fact" in desc or "goal" in desc


class TestConsolidationExecution:
    """Tests for memory consolidation execution."""

    @pytest.fixture
    def mock_claude_client(self):
        """Create a mock Claude client."""
        client = AsyncMock()
        client.complete = AsyncMock(return_value='{"facts": [], "goals": []}')
        return client

    @pytest.fixture
    def mock_conv_store(self):
        """Create a mock conversation store."""
        store = MagicMock()
        store.get_today_messages = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_fact_store(self):
        """Create a mock fact store."""
        store = MagicMock()
        store.add = AsyncMock(return_value=1)
        return store

    @pytest.fixture
    def mock_goal_store(self):
        """Create a mock goal store."""
        store = MagicMock()
        store.add = AsyncMock(return_value=1)
        return store

    @pytest.mark.asyncio
    async def test_consolidation_with_no_conversations(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Returns zero counts when no conversations exist."""
        from remy.scheduler.proactive import ProactiveScheduler

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        result = await scheduler._consolidate_user_memory(user_id=123)

        assert result["facts_stored"] == 0
        assert result["goals_stored"] == 0
        mock_claude_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_extracts_facts(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Extracts and stores facts from Claude response."""
        from remy.scheduler.proactive import ProactiveScheduler

        mock_conv_store.get_today_messages = AsyncMock(
            return_value=[
                ConversationTurn(role="user", content="The tyre's done"),
                ConversationTurn(role="assistant", content="Great!"),
            ]
        )

        mock_claude_client.complete = AsyncMock(
            return_value=json.dumps({
                "facts": [
                    {"content": "Tyre repair completed", "category": "other"}
                ],
                "goals": []
            })
        )

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        result = await scheduler._consolidate_user_memory(user_id=123)

        assert result["facts_stored"] == 1
        assert result["goals_stored"] == 0
        mock_fact_store.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_consolidation_extracts_goals(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Extracts and stores goals from Claude response."""
        from remy.scheduler.proactive import ProactiveScheduler

        mock_conv_store.get_today_messages = AsyncMock(
            return_value=[
                ConversationTurn(role="user", content="I want to learn Spanish"),
                ConversationTurn(role="assistant", content="That's a great goal!"),
            ]
        )

        mock_claude_client.complete = AsyncMock(
            return_value=json.dumps({
                "facts": [],
                "goals": [
                    {"title": "Learn Spanish", "description": "Language learning goal"}
                ]
            })
        )

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        result = await scheduler._consolidate_user_memory(user_id=123)

        assert result["facts_stored"] == 0
        assert result["goals_stored"] == 1
        mock_goal_store.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_consolidation_skips_tool_turns(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Skips tool turns and compacted summaries in transcript."""
        from remy.scheduler.proactive import ProactiveScheduler

        mock_conv_store.get_today_messages = AsyncMock(
            return_value=[
                ConversationTurn(role="user", content="Hello"),
                ConversationTurn(role="assistant", content="__TOOL_TURN__:[]"),
                ConversationTurn(role="assistant", content="[COMPACTED SUMMARY]\nOld chat"),
                ConversationTurn(role="assistant", content="Hi there!"),
            ]
        )

        mock_claude_client.complete = AsyncMock(
            return_value='{"facts": [], "goals": []}'
        )

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        await scheduler._consolidate_user_memory(user_id=123)

        # Check that Claude was called with a transcript that doesn't include tool turns
        call_args = mock_claude_client.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        prompt = messages[0]["content"]

        assert "__TOOL_TURN__" not in prompt
        assert "[COMPACTED SUMMARY]" not in prompt
        assert "Hello" in prompt
        assert "Hi there!" in prompt

    @pytest.mark.asyncio
    async def test_consolidation_handles_json_in_code_block(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Handles Claude response wrapped in markdown code block."""
        from remy.scheduler.proactive import ProactiveScheduler

        mock_conv_store.get_today_messages = AsyncMock(
            return_value=[
                ConversationTurn(role="user", content="Test message"),
            ]
        )

        mock_claude_client.complete = AsyncMock(
            return_value='```json\n{"facts": [{"content": "Test fact", "category": "other"}], "goals": []}\n```'
        )

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        result = await scheduler._consolidate_user_memory(user_id=123)

        assert result["facts_stored"] == 1

    @pytest.mark.asyncio
    async def test_consolidation_caps_facts_at_10(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Caps facts at 10 per consolidation run."""
        from remy.scheduler.proactive import ProactiveScheduler

        mock_conv_store.get_today_messages = AsyncMock(
            return_value=[
                ConversationTurn(role="user", content="Lots of info"),
            ]
        )

        # Return 15 facts
        facts = [{"content": f"Fact {i}", "category": "other"} for i in range(15)]
        mock_claude_client.complete = AsyncMock(
            return_value=json.dumps({"facts": facts, "goals": []})
        )

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        result = await scheduler._consolidate_user_memory(user_id=123)

        assert result["facts_stored"] == 10
        assert mock_fact_store.add.call_count == 10

    @pytest.mark.asyncio
    async def test_consolidation_caps_goals_at_5(
        self, mock_claude_client, mock_conv_store, mock_fact_store, mock_goal_store
    ):
        """Caps goals at 5 per consolidation run."""
        from remy.scheduler.proactive import ProactiveScheduler

        mock_conv_store.get_today_messages = AsyncMock(
            return_value=[
                ConversationTurn(role="user", content="Many goals"),
            ]
        )

        # Return 10 goals
        goals = [{"title": f"Goal {i}"} for i in range(10)]
        mock_claude_client.complete = AsyncMock(
            return_value=json.dumps({"facts": [], "goals": goals})
        )

        bot = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=mock_goal_store,
            fact_store=mock_fact_store,
            claude_client=mock_claude_client,
            conv_store=mock_conv_store,
        )

        result = await scheduler._consolidate_user_memory(user_id=123)

        assert result["goals_stored"] == 5
        assert mock_goal_store.add.call_count == 5


class TestManualConsolidationTrigger:
    """Tests for run_memory_consolidation_now() manual trigger."""

    @pytest.mark.asyncio
    async def test_manual_trigger_returns_error_without_conv_store(self):
        """Returns error when conversation store not configured."""
        from remy.scheduler.proactive import ProactiveScheduler

        bot = MagicMock()
        goal_store = MagicMock()
        scheduler = ProactiveScheduler(bot=bot, goal_store=goal_store)

        result = await scheduler.run_memory_consolidation_now(user_id=123)

        assert result["status"] == "error"
        assert "Conversation store" in result["message"]

    @pytest.mark.asyncio
    async def test_manual_trigger_returns_error_without_claude(self):
        """Returns error when Claude client not configured."""
        from remy.scheduler.proactive import ProactiveScheduler

        bot = MagicMock()
        goal_store = MagicMock()
        conv_store = MagicMock()
        scheduler = ProactiveScheduler(
            bot=bot, goal_store=goal_store, conv_store=conv_store
        )

        result = await scheduler.run_memory_consolidation_now(user_id=123)

        assert result["status"] == "error"
        assert "Claude" in result["message"]

    @pytest.mark.asyncio
    async def test_manual_trigger_consolidates_specific_user(self):
        """Consolidates only the specified user when user_id provided."""
        from remy.scheduler.proactive import ProactiveScheduler

        bot = MagicMock()
        goal_store = MagicMock()
        fact_store = MagicMock()
        fact_store.add = AsyncMock(return_value=1)
        conv_store = MagicMock()
        conv_store.get_today_messages = AsyncMock(return_value=[])
        claude_client = AsyncMock()

        scheduler = ProactiveScheduler(
            bot=bot,
            goal_store=goal_store,
            fact_store=fact_store,
            conv_store=conv_store,
            claude_client=claude_client,
        )

        with patch.object(
            scheduler, "_consolidate_user_memory",
            new_callable=AsyncMock,
            return_value={"facts_stored": 2, "goals_stored": 1}
        ) as mock_consolidate:
            result = await scheduler.run_memory_consolidation_now(user_id=123)

            mock_consolidate.assert_called_once_with(123)
            assert result["status"] == "success"
            assert result["facts_stored"] == 2
            assert result["goals_stored"] == 1
