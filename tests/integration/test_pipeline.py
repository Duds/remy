"""Integration tests for pipeline.py (proactive message pipeline)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    """Configure settings for testing."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS_RAW", "12345")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    
    import remy.config
    remy.config._settings = None
    
    return tmp_path


@pytest.fixture
def mock_claude_client():
    """Mock ClaudeClient for testing."""
    mock = MagicMock()
    mock.stream_with_tools = AsyncMock()
    return mock


@pytest.fixture
def mock_tool_registry():
    """Mock ToolRegistry for testing."""
    mock = MagicMock()
    mock.dispatch = AsyncMock(return_value="Tool result")
    mock.get_tool_schemas = MagicMock(return_value=[])
    return mock


@pytest.fixture
def mock_conv_store(tmp_path):
    """Mock ConversationStore for testing."""
    mock = MagicMock()
    mock.get_recent_turns = AsyncMock(return_value=[])
    mock.append_turn = AsyncMock()
    return mock


@pytest.fixture
def mock_session_manager():
    """Mock SessionManager for testing."""
    mock = MagicMock()
    mock.get_session_key = MagicMock(return_value="test_session")
    return mock


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot for testing."""
    mock = MagicMock()
    mock.send_message = AsyncMock(return_value=MagicMock(message_id=123))
    return mock


class TestProactivePipeline:
    """Tests for the proactive message pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_sends_message(
        self,
        mock_settings,
        mock_claude_client,
        mock_tool_registry,
        mock_conv_store,
        mock_session_manager,
        mock_telegram_bot,
    ):
        """Verify pipeline sends a message to the user."""
        from remy.bot.pipeline import run_proactive_trigger
        from remy.ai.claude_client import TextChunk
        
        # Mock streaming response
        async def mock_stream(*args, **kwargs):
            yield TextChunk(text="Good morning!")
        
        mock_claude_client.stream_with_tools = mock_stream
        
        mock_sent = MagicMock()
        mock_sent.edit_text = AsyncMock()
        mock_telegram_bot.send_message = AsyncMock(return_value=mock_sent)
        
        await run_proactive_trigger(
            bot=mock_telegram_bot,
            chat_id=12345,
            user_id=12345,
            label="Morning briefing",
            claude_client=mock_claude_client,
            tool_registry=mock_tool_registry,
            conv_store=mock_conv_store,
            session_manager=mock_session_manager,
        )
        
        # Verify message was sent
        mock_telegram_bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_pipeline_handles_tool_use(
        self,
        mock_settings,
        mock_claude_client,
        mock_tool_registry,
        mock_conv_store,
        mock_session_manager,
        mock_telegram_bot,
    ):
        """Verify pipeline handles tool use correctly."""
        from remy.bot.pipeline import run_proactive_trigger
        from remy.ai.claude_client import TextChunk, ToolStatusChunk, ToolResultChunk, ToolTurnComplete
        
        # Mock streaming response with tool use
        async def mock_stream(*args, **kwargs):
            yield ToolStatusChunk(tool_name="get_current_time")
            yield ToolResultChunk(tool_name="get_current_time", result="10:00 AM")
            yield ToolTurnComplete(
                assistant_blocks=[{"type": "tool_use", "id": "123", "name": "get_current_time", "input": {}}],
                tool_result_blocks=[{"type": "tool_result", "tool_use_id": "123", "content": "10:00 AM"}],
            )
            yield TextChunk(text="The time is 10:00 AM")
        
        mock_claude_client.stream_with_tools = mock_stream
        
        mock_sent = MagicMock()
        mock_sent.edit_text = AsyncMock()
        mock_telegram_bot.send_message = AsyncMock(return_value=mock_sent)
        
        await run_proactive_trigger(
            bot=mock_telegram_bot,
            chat_id=12345,
            user_id=12345,
            label="Time check",
            claude_client=mock_claude_client,
            tool_registry=mock_tool_registry,
            conv_store=mock_conv_store,
            session_manager=mock_session_manager,
        )
        
        # Verify tool status was shown
        assert mock_sent.edit_text.called

    @pytest.mark.asyncio
    async def test_pipeline_handles_errors_gracefully(
        self,
        mock_settings,
        mock_claude_client,
        mock_tool_registry,
        mock_conv_store,
        mock_session_manager,
        mock_telegram_bot,
    ):
        """Verify pipeline handles errors gracefully."""
        from remy.bot.pipeline import run_proactive_trigger
        
        # Mock streaming response that raises an error
        async def mock_stream(*args, **kwargs):
            raise ValueError("API error")
            yield  # Make it a generator
        
        mock_claude_client.stream_with_tools = mock_stream
        
        mock_sent = MagicMock()
        mock_sent.edit_text = AsyncMock()
        mock_telegram_bot.send_message = AsyncMock(return_value=mock_sent)
        
        # Should not raise
        await run_proactive_trigger(
            bot=mock_telegram_bot,
            chat_id=12345,
            user_id=12345,
            label="Error test",
            claude_client=mock_claude_client,
            tool_registry=mock_tool_registry,
            conv_store=mock_conv_store,
            session_manager=mock_session_manager,
        )
        
        # Verify error message was shown
        mock_sent.edit_text.assert_called()

    @pytest.mark.asyncio
    async def test_pipeline_persists_conversation(
        self,
        mock_settings,
        mock_claude_client,
        mock_tool_registry,
        mock_conv_store,
        mock_session_manager,
        mock_telegram_bot,
    ):
        """Verify pipeline persists conversation turns."""
        from remy.bot.pipeline import run_proactive_trigger
        from remy.ai.claude_client import TextChunk
        
        # Mock streaming response
        async def mock_stream(*args, **kwargs):
            yield TextChunk(text="Hello!")
        
        mock_claude_client.stream_with_tools = mock_stream
        
        mock_sent = MagicMock()
        mock_sent.edit_text = AsyncMock()
        mock_telegram_bot.send_message = AsyncMock(return_value=mock_sent)
        
        await run_proactive_trigger(
            bot=mock_telegram_bot,
            chat_id=12345,
            user_id=12345,
            label="Persist test",
            claude_client=mock_claude_client,
            tool_registry=mock_tool_registry,
            conv_store=mock_conv_store,
            session_manager=mock_session_manager,
        )
        
        # Verify conversation was persisted
        assert mock_conv_store.append_turn.called


class TestStreamingReply:
    """Tests for StreamingReply helper."""

    @pytest.mark.asyncio
    async def test_streaming_reply_updates_message(self, mock_settings):
        """Verify StreamingReply updates the Telegram message."""
        from remy.bot.streaming import StreamingReply
        
        mock_message = MagicMock()
        mock_message.edit_text = AsyncMock()
        
        mock_session_manager = MagicMock()
        mock_session_manager.is_cancelled = MagicMock(return_value=False)
        
        streamer = StreamingReply(mock_message, mock_session_manager, user_id=12345)
        
        await streamer.feed("Hello ")
        await streamer.feed("World!")
        await streamer.finalize()
        
        # Verify text was accumulated correctly
        assert streamer._accumulated == "Hello World!"
        # finalize() calls _flush() which should edit the message
        assert mock_message.edit_text.called
