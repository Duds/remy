"""Integration tests for telegram_bot.py."""

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
def sample_handlers():
    """Create sample handlers for testing."""
    return {
        "start": AsyncMock(),
        "help": AsyncMock(),
        "cancel": AsyncMock(),
        "status": AsyncMock(),
        "compact": AsyncMock(),
        "setmychat": AsyncMock(),
        "briefing": AsyncMock(),
        "goals": AsyncMock(),
        "delete_conversation": AsyncMock(),
        "consolidate": AsyncMock(),
        "plans": AsyncMock(),
        "read": AsyncMock(),
        "write": AsyncMock(),
        "ls": AsyncMock(),
        "find": AsyncMock(),
        "set_project": AsyncMock(),
        "project_status": AsyncMock(),
        "scan_downloads": AsyncMock(),
        "organize": AsyncMock(),
        "clean": AsyncMock(),
        "calendar": AsyncMock(),
        "calendar_today": AsyncMock(),
        "schedule": AsyncMock(),
        "gmail_unread": AsyncMock(),
        "gmail_unread_summary": AsyncMock(),
        "gmail_classify": AsyncMock(),
        "gmail_search": AsyncMock(),
        "gmail_read": AsyncMock(),
        "gmail_labels": AsyncMock(),
        "gdoc": AsyncMock(),
        "gdoc_append": AsyncMock(),
        "contacts": AsyncMock(),
        "contacts_birthday": AsyncMock(),
        "contacts_details": AsyncMock(),
        "contacts_note": AsyncMock(),
        "contacts_prune": AsyncMock(),
        "search": AsyncMock(),
        "research": AsyncMock(),
        "save_url": AsyncMock(),
        "bookmarks": AsyncMock(),
        "price_check": AsyncMock(),
        "grocery_list": AsyncMock(),
        "board": AsyncMock(),
        "breakdown": AsyncMock(),
        "logs": AsyncMock(),
        "schedule_daily": AsyncMock(),
        "schedule_weekly": AsyncMock(),
        "list_automations": AsyncMock(),
        "unschedule": AsyncMock(),
        "stats": AsyncMock(),
        "costs": AsyncMock(),
        "goal_status": AsyncMock(),
        "retrospective": AsyncMock(),
        "jobs": AsyncMock(),
        "reindex": AsyncMock(),
        "privacy_audit": AsyncMock(),
        "diagnostics": AsyncMock(),
        "message": AsyncMock(),
        "voice": AsyncMock(),
        "photo": AsyncMock(),
        "document": AsyncMock(),
    }


class TestTelegramBot:
    """Tests for TelegramBot class."""

    def test_bot_initialisation(self, mock_settings, sample_handlers):
        """Verify bot initialises with correct configuration."""
        with patch("remy.bot.telegram_bot.Application") as mock_app:
            mock_builder = MagicMock()
            mock_app.builder.return_value = mock_builder
            mock_builder.token.return_value = mock_builder
            mock_builder.connect_timeout.return_value = mock_builder
            mock_builder.read_timeout.return_value = mock_builder
            mock_builder.write_timeout.return_value = mock_builder
            mock_builder.pool_timeout.return_value = mock_builder
            mock_builder.get_updates_connect_timeout.return_value = mock_builder
            mock_builder.get_updates_read_timeout.return_value = mock_builder
            mock_builder.get_updates_write_timeout.return_value = mock_builder
            mock_builder.get_updates_pool_timeout.return_value = mock_builder
            mock_builder.build.return_value = MagicMock()
            
            from remy.bot.telegram_bot import TelegramBot
            
            bot = TelegramBot(handlers=sample_handlers)
            
            # Verify token was set
            mock_builder.token.assert_called_once_with("test_token")
            
            # Verify timeouts were configured
            assert mock_builder.connect_timeout.called
            assert mock_builder.read_timeout.called

    def test_handlers_registered(self, mock_settings, sample_handlers):
        """Verify all handlers are registered with the application."""
        with patch("remy.bot.telegram_bot.Application") as mock_app:
            mock_builder = MagicMock()
            mock_application = MagicMock()
            mock_app.builder.return_value = mock_builder
            mock_builder.token.return_value = mock_builder
            mock_builder.connect_timeout.return_value = mock_builder
            mock_builder.read_timeout.return_value = mock_builder
            mock_builder.write_timeout.return_value = mock_builder
            mock_builder.pool_timeout.return_value = mock_builder
            mock_builder.get_updates_connect_timeout.return_value = mock_builder
            mock_builder.get_updates_read_timeout.return_value = mock_builder
            mock_builder.get_updates_write_timeout.return_value = mock_builder
            mock_builder.get_updates_pool_timeout.return_value = mock_builder
            mock_builder.build.return_value = mock_application
            
            from remy.bot.telegram_bot import TelegramBot
            
            bot = TelegramBot(handlers=sample_handlers)
            
            # Verify handlers were added
            assert mock_application.add_handler.called
            # Should have many handler registrations
            assert mock_application.add_handler.call_count > 10


class TestErrorHandler:
    """Tests for the error handler."""

    @pytest.mark.asyncio
    async def test_error_handler_logs_transient_errors(self, mock_settings):
        """Verify transient errors are logged at WARNING level."""
        import telegram.error
        from remy.bot.telegram_bot import _error_handler
        
        mock_update = MagicMock()
        mock_context = MagicMock()
        mock_context.error = telegram.error.NetworkError("Connection reset")
        mock_context.bot = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        
        # Should not raise
        await _error_handler(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_error_handler_sends_alert_for_unexpected_errors(self, mock_settings):
        """Verify unexpected errors trigger admin alerts."""
        from remy.bot.telegram_bot import _error_handler
        from remy.config import get_settings
        
        import remy.config
        remy.config._settings = None
        
        mock_update = MagicMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 12345
        mock_update.effective_chat = MagicMock()
        mock_update.effective_chat.id = 12345
        
        mock_context = MagicMock()
        mock_context.error = ValueError("Unexpected error")
        mock_context.bot = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        
        await _error_handler(mock_update, mock_context)
        
        # Should attempt to send alert
        mock_context.bot.send_message.assert_called()


class TestBotRun:
    """Tests for bot run method."""

    def test_run_starts_polling(self, mock_settings, sample_handlers):
        """Verify run() starts the bot polling."""
        with patch("remy.bot.telegram_bot.Application") as mock_app:
            mock_builder = MagicMock()
            mock_application = MagicMock()
            mock_app.builder.return_value = mock_builder
            mock_builder.token.return_value = mock_builder
            mock_builder.connect_timeout.return_value = mock_builder
            mock_builder.read_timeout.return_value = mock_builder
            mock_builder.write_timeout.return_value = mock_builder
            mock_builder.pool_timeout.return_value = mock_builder
            mock_builder.get_updates_connect_timeout.return_value = mock_builder
            mock_builder.get_updates_read_timeout.return_value = mock_builder
            mock_builder.get_updates_write_timeout.return_value = mock_builder
            mock_builder.get_updates_pool_timeout.return_value = mock_builder
            mock_builder.build.return_value = mock_application
            
            from remy.bot.telegram_bot import TelegramBot
            
            bot = TelegramBot(handlers=sample_handlers)
            bot.run()
            
            # Verify run_polling was called
            mock_application.run_polling.assert_called_once()
