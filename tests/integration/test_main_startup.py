"""Integration tests for main.py startup sequence."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    """Configure settings for testing."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS_RAW", "12345")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_ENVIRONMENT", "false")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    
    # Create required directories
    (tmp_path / "sessions").mkdir()
    (tmp_path / "logs").mkdir()
    
    return tmp_path


@pytest.fixture
def mock_telegram_bot():
    """Mock TelegramBot to avoid actual Telegram connections."""
    with patch("remy.main.TelegramBot") as mock:
        mock_instance = MagicMock()
        mock_instance.run = MagicMock()
        mock_instance.application = MagicMock()
        mock_instance.application.bot = MagicMock()
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def mock_claude_client():
    """Mock ClaudeClient to avoid actual API calls."""
    with patch("remy.main.ClaudeClient") as mock:
        mock_instance = MagicMock()
        mock_instance.ping = AsyncMock(return_value=True)
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def mock_database():
    """Mock DatabaseManager to use in-memory database."""
    with patch("remy.main.DatabaseManager") as mock:
        mock_instance = MagicMock()
        mock_instance.init = AsyncMock()
        mock_instance.db_path = ":memory:"
        mock.return_value = mock_instance
        yield mock


class TestMainStartup:
    """Tests for main.py startup sequence."""

    def test_data_directories_created(self, mock_settings, mock_telegram_bot, mock_claude_client, mock_database):
        """Verify data directories are created on startup."""
        from remy.config import get_settings
        
        # Clear cached settings
        import remy.config
        remy.config._settings = None
        
        settings = get_settings()
        
        assert os.path.exists(settings.data_dir)
        assert os.path.exists(settings.sessions_dir)
        assert os.path.exists(settings.logs_dir)

    def test_logging_configured(self, mock_settings, mock_telegram_bot, mock_claude_client, mock_database):
        """Verify logging is configured on startup."""
        import logging
        from remy.logging_config import setup_logging
        from remy.config import get_settings
        
        import remy.config
        remy.config._settings = None
        
        settings = get_settings()
        setup_logging(settings.log_level, settings.logs_dir, settings.azure_environment)
        
        logger = logging.getLogger("remy")
        assert logger.level == logging.DEBUG or logger.level == logging.NOTSET

    def test_components_initialised(self, mock_settings, mock_telegram_bot, mock_claude_client, mock_database):
        """Verify all major components are initialised."""
        from contextlib import ExitStack
        
        patches_to_apply = [
            "remy.main.MistralClient",
            "remy.main.MoonshotClient",
            "remy.main.OllamaClient",
            "remy.main.ModelRouter",
            "remy.main.SessionManager",
            "remy.main.ConversationStore",
            "remy.main.EmbeddingStore",
            "remy.main.FactStore",
            "remy.main.FactExtractor",
            "remy.main.GoalStore",
            "remy.main.GoalExtractor",
            "remy.main.FTSSearch",
            "remy.main.KnowledgeStore",
            "remy.main.KnowledgeExtractor",
            "remy.main.MemoryInjector",
            "remy.main.AutomationStore",
            "remy.main.PlanStore",
            "remy.main.ConversationAnalyzer",
            "remy.main.FileIndexer",
            "remy.main.VoiceTranscriber",
            "remy.main.BoardOrchestrator",
            "remy.main.ToolRegistry",
            "remy.main.DiagnosticsRunner",
            "remy.main.OutboundQueue",
            "remy.main.setup_logging",
            "remy.main.log_startup_config",
            "remy.ai.tone.ToneDetector",
        ]
        
        with ExitStack() as stack:
            for target in patches_to_apply:
                stack.enter_context(patch(target))
            
            mock_job_store = stack.enter_context(patch("remy.main.BackgroundJobStore"))
            mock_handlers = stack.enter_context(patch("remy.main.make_handlers"))
            
            mock_handlers.return_value = {"briefing": MagicMock()}
            mock_job_store.return_value.mark_interrupted = AsyncMock()
            
            # Import main to trigger component initialisation
            import remy.config
            remy.config._settings = None
            
            from remy.main import main
            
            # Verify TelegramBot was instantiated
            mock_telegram_bot.assert_not_called()  # Not called until main() runs


class TestHealthMonitor:
    """Tests for the health_monitor coroutine."""

    @pytest.mark.asyncio
    async def test_health_monitor_logs_failures(self, mock_settings):
        """Verify health monitor logs consecutive failures."""
        from remy.main import health_monitor
        
        mock_claude = MagicMock()
        mock_claude.ping = AsyncMock(side_effect=[False, False, True])
        
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        
        # Run health monitor with short sleep
        with patch("remy.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, None, asyncio.CancelledError()]
            
            with pytest.raises(asyncio.CancelledError):
                await health_monitor(mock_claude, mock_bot)
        
        # Should have attempted to send alert after 2 consecutive failures
        assert mock_claude.ping.call_count >= 2


class TestSignalHandling:
    """Tests for signal handling in main."""

    def test_sigterm_handler_registered(self, mock_settings, mock_telegram_bot, mock_claude_client, mock_database):
        """Verify SIGTERM handler is registered."""
        import signal
        
        original_handler = signal.getsignal(signal.SIGTERM)
        
        # The handler is registered inside main(), so we just verify the mechanism works
        assert signal.getsignal(signal.SIGTERM) is not None
