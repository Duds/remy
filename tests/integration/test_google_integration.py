"""Integration tests for Google API clients with circuit breaker and retry."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    """Configure settings for testing."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    
    import remy.config
    remy.config._settings = None
    
    return tmp_path


class TestGoogleResilience:
    """Tests for Google API resilience (circuit breaker + retry)."""

    @pytest.mark.asyncio
    async def test_with_retry_succeeds_on_first_attempt(self, mock_settings):
        """Verify with_retry returns result on first successful attempt."""
        from remy.google.base import with_retry
        
        async def success():
            return "success"
        
        result = await with_retry(success)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_with_retry_retries_on_transient_error(self, mock_settings):
        """Verify with_retry retries on transient errors."""
        from remy.google.base import with_retry
        
        call_count = 0
        
        async def transient_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("503 Service Unavailable")
            return "success"
        
        with patch("remy.google.base.asyncio.sleep", new_callable=AsyncMock):
            result = await with_retry(transient_then_success, max_retries=3)
        
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_with_retry_raises_on_permanent_error(self, mock_settings):
        """Verify with_retry raises immediately on permanent errors."""
        from remy.google.base import with_retry
        
        async def permanent_error():
            raise ValueError("Invalid argument")
        
        with pytest.raises(ValueError):
            await with_retry(permanent_error, max_retries=3)

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self, mock_settings):
        """Verify circuit breaker opens after threshold failures."""
        from remy.google.base import with_circuit_breaker
        from remy.utils.circuit_breaker import CircuitOpenError, reset_all_circuits
        
        # Reset circuits before test
        reset_all_circuits()
        
        call_count = 0
        
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise Exception("Service error")
        
        # Trigger failures up to threshold
        for _ in range(5):
            try:
                await with_circuit_breaker("test_service", always_fail())
            except Exception:
                pass
        
        # Next call should be blocked by circuit breaker
        with pytest.raises(CircuitOpenError):
            coro = always_fail()
            try:
                await with_circuit_breaker("test_service", coro)
            finally:
                # Ensure coroutine is closed to avoid warning
                coro.close()
        
        # Clean up
        reset_all_circuits()

    @pytest.mark.asyncio
    async def test_with_google_resilience_combines_retry_and_circuit_breaker(self, mock_settings):
        """Verify with_google_resilience combines retry and circuit breaker."""
        from remy.google.base import with_google_resilience
        from remy.utils.circuit_breaker import reset_all_circuits
        
        reset_all_circuits()
        
        call_count = 0
        
        async def transient_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("503 Service Unavailable")
            return "success"
        
        with patch("remy.google.base.asyncio.sleep", new_callable=AsyncMock):
            result = await with_google_resilience(
                "test_combined",
                transient_then_success,
                max_retries=3,
            )
        
        assert result == "success"
        
        reset_all_circuits()


class TestGmailClient:
    """Tests for GmailClient with resilience."""

    @pytest.mark.asyncio
    async def test_gmail_get_unread_uses_resilience(self, mock_settings):
        """Verify Gmail client uses resilience wrapper."""
        with patch("remy.google.gmail.with_google_resilience") as mock_resilience:
            mock_resilience.return_value = []
            
            from remy.google.gmail import GmailClient
            
            client = GmailClient(token_file="test_token.json")
            
            with patch.object(client, "_service") as mock_service:
                mock_service.return_value.users.return_value.messages.return_value.list.return_value.execute.return_value = {
                    "messages": []
                }
                
                # The actual call goes through with_google_resilience
                result = await client.get_unread()
                
                # Verify resilience wrapper was called
                mock_resilience.assert_called()


class TestCalendarClient:
    """Tests for CalendarClient with resilience."""

    @pytest.mark.asyncio
    async def test_calendar_list_events_uses_resilience(self, mock_settings):
        """Verify Calendar client uses resilience wrapper."""
        with patch("remy.google.calendar.with_google_resilience") as mock_resilience:
            mock_resilience.return_value = []
            
            from remy.google.calendar import CalendarClient
            
            client = CalendarClient(token_file="test_token.json")
            
            result = await client.list_events()
            
            # Verify resilience wrapper was called
            mock_resilience.assert_called()


class TestContactsClient:
    """Tests for ContactsClient with resilience."""

    @pytest.mark.asyncio
    async def test_contacts_list_uses_resilience(self, mock_settings):
        """Verify Contacts client uses resilience wrapper."""
        with patch("remy.google.contacts.with_google_resilience") as mock_resilience:
            mock_resilience.return_value = []
            
            from remy.google.contacts import ContactsClient
            
            client = ContactsClient(token_file="test_token.json")
            
            result = await client.list_contacts()
            
            # Verify resilience wrapper was called
            mock_resilience.assert_called()


class TestDocsClient:
    """Tests for DocsClient with resilience."""

    @pytest.mark.asyncio
    async def test_docs_read_uses_resilience(self, mock_settings):
        """Verify Docs client uses resilience wrapper."""
        with patch("remy.google.docs.with_google_resilience") as mock_resilience:
            mock_resilience.return_value = ("Test Doc", "Content")
            
            from remy.google.docs import DocsClient
            
            client = DocsClient(token_file="test_token.json")
            
            result = await client.read_document("test_doc_id")
            
            # Verify resilience wrapper was called
            mock_resilience.assert_called()
