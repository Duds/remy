"""Tests for remy.ai.tools.email module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.email import (
    exec_classify_promotional_emails,
    exec_create_email_draft,
    exec_create_gmail_label,
    exec_label_emails,
    exec_list_gmail_labels,
    exec_read_email,
    exec_read_emails,
    exec_search_gmail,
)


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._gmail = kwargs.get("gmail")
    return registry


class TestExecReadEmails:
    """Tests for exec_read_emails executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_read_emails(registry, {})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        gmail = AsyncMock()
        gmail.get_unread = AsyncMock(return_value=[])
        registry = make_registry(gmail=gmail)
        
        result = await exec_read_emails(registry, {})
        assert isinstance(result, str)


class TestExecSearchGmail:
    """Tests for exec_search_gmail executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_search_gmail(registry, {"query": "test"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_query(self):
        """Should require a search query."""
        gmail = AsyncMock()
        registry = make_registry(gmail=gmail)
        
        result = await exec_search_gmail(registry, {"query": ""})
        assert "provide" in result.lower() or "query" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        gmail = AsyncMock()
        gmail.search = AsyncMock(return_value=[])
        registry = make_registry(gmail=gmail)
        
        result = await exec_search_gmail(registry, {"query": "test"})
        assert isinstance(result, str)


class TestExecReadEmail:
    """Tests for exec_read_email executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_read_email(registry, {"message_id": "123"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_message_id(self):
        """Should require a message ID."""
        gmail = AsyncMock()
        registry = make_registry(gmail=gmail)
        
        result = await exec_read_email(registry, {"message_id": ""})
        assert "provide" in result.lower() or "message" in result.lower()


class TestExecListGmailLabels:
    """Tests for exec_list_gmail_labels executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_list_gmail_labels(registry, {})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        gmail = AsyncMock()
        gmail.list_labels = AsyncMock(return_value=[])
        registry = make_registry(gmail=gmail)
        
        result = await exec_list_gmail_labels(registry, {})
        assert isinstance(result, str)


class TestExecLabelEmails:
    """Tests for exec_label_emails executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_label_emails(registry, {"message_ids": ["123"], "label": "Work"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_message_ids(self):
        """Should require message IDs."""
        gmail = AsyncMock()
        registry = make_registry(gmail=gmail)
        
        result = await exec_label_emails(registry, {"message_ids": [], "label": "Work"})
        assert "provide" in result.lower() or "message" in result.lower()


class TestExecCreateGmailLabel:
    """Tests for exec_create_gmail_label executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_create_gmail_label(registry, {"name": "NewLabel"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_name(self):
        """Should require a label name."""
        gmail = AsyncMock()
        registry = make_registry(gmail=gmail)
        
        result = await exec_create_gmail_label(registry, {"name": ""})
        assert "provide" in result.lower() or "name" in result.lower()


class TestExecCreateEmailDraft:
    """Tests for exec_create_email_draft executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_create_email_draft(registry, {"to": "test@example.com"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_recipient(self):
        """Should require a recipient."""
        gmail = AsyncMock()
        registry = make_registry(gmail=gmail)
        
        result = await exec_create_email_draft(registry, {"to": ""})
        assert "provide" in result.lower() or "recipient" in result.lower() or "to" in result.lower()


class TestExecClassifyPromotionalEmails:
    """Tests for exec_classify_promotional_emails executor."""

    @pytest.mark.asyncio
    async def test_no_gmail_returns_not_configured(self):
        """Should return not configured when Gmail not set up."""
        registry = make_registry(gmail=None)
        result = await exec_classify_promotional_emails(registry, {})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        gmail = AsyncMock()
        gmail.classify_promotional = AsyncMock(return_value=[])
        registry = make_registry(gmail=gmail)
        
        result = await exec_classify_promotional_emails(registry, {})
        assert isinstance(result, str)
