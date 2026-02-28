"""Tests for remy.ai.tools.contacts module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.contacts import (
    exec_find_sparse_contacts,
    exec_get_contact_details,
    exec_search_contacts,
    exec_upcoming_birthdays,
    exec_update_contact_note,
)


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._contacts = kwargs.get("contacts")
    return registry


class TestExecSearchContacts:
    """Tests for exec_search_contacts executor."""

    @pytest.mark.asyncio
    async def test_no_contacts_returns_not_configured(self):
        """Should return not configured when Contacts not set up."""
        registry = make_registry(contacts=None)
        result = await exec_search_contacts(registry, {"query": "John"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_query(self):
        """Should require a search query."""
        contacts = AsyncMock()
        registry = make_registry(contacts=contacts)
        
        result = await exec_search_contacts(registry, {"query": ""})
        assert "provide" in result.lower() or "query" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_no_results_message(self):
        """Should return appropriate message when no contacts found."""
        contacts = AsyncMock()
        contacts.search_contacts = AsyncMock(return_value=[])
        registry = make_registry(contacts=contacts)
        
        result = await exec_search_contacts(registry, {"query": "Nonexistent"})
        assert "no contact" in result.lower() or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        contacts = AsyncMock()
        contacts.search_contacts = AsyncMock(return_value=[])
        registry = make_registry(contacts=contacts)
        
        result = await exec_search_contacts(registry, {"query": "John"})
        assert isinstance(result, str)


class TestExecUpcomingBirthdays:
    """Tests for exec_upcoming_birthdays executor."""

    @pytest.mark.asyncio
    async def test_no_contacts_returns_not_configured(self):
        """Should return not configured when Contacts not set up."""
        registry = make_registry(contacts=None)
        result = await exec_upcoming_birthdays(registry, {})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        contacts = AsyncMock()
        contacts.get_upcoming_birthdays = AsyncMock(return_value=[])
        registry = make_registry(contacts=contacts)
        
        result = await exec_upcoming_birthdays(registry, {})
        assert isinstance(result, str)


class TestExecGetContactDetails:
    """Tests for exec_get_contact_details executor."""

    @pytest.mark.asyncio
    async def test_no_contacts_returns_not_configured(self):
        """Should return not configured when Contacts not set up."""
        registry = make_registry(contacts=None)
        result = await exec_get_contact_details(registry, {"name": "John"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_name(self):
        """Should require a contact name."""
        contacts = AsyncMock()
        registry = make_registry(contacts=contacts)
        
        result = await exec_get_contact_details(registry, {"name": ""})
        assert "provide" in result.lower() or "name" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_not_found_message(self):
        """Should return not found when contact doesn't exist."""
        contacts = AsyncMock()
        contacts.search_contacts = AsyncMock(return_value=[])
        registry = make_registry(contacts=contacts)
        
        result = await exec_get_contact_details(registry, {"name": "Unknown"})
        assert "no contact" in result.lower() or "not found" in result.lower()


class TestExecUpdateContactNote:
    """Tests for exec_update_contact_note executor."""

    @pytest.mark.asyncio
    async def test_no_contacts_returns_not_configured(self):
        """Should return not configured when Contacts not set up."""
        registry = make_registry(contacts=None)
        result = await exec_update_contact_note(registry, {"name": "John", "note": "Test"})
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_name(self):
        """Should require a contact name."""
        contacts = AsyncMock()
        registry = make_registry(contacts=contacts)
        
        result = await exec_update_contact_note(registry, {"name": "", "note": "Test"})
        assert "provide" in result.lower() or "name" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_note(self):
        """Should require a note."""
        contacts = AsyncMock()
        registry = make_registry(contacts=contacts)
        
        result = await exec_update_contact_note(registry, {"name": "John", "note": ""})
        assert "provide" in result.lower() or "note" in result.lower()


class TestExecFindSparseContacts:
    """Tests for exec_find_sparse_contacts executor."""

    @pytest.mark.asyncio
    async def test_no_contacts_returns_not_configured(self):
        """Should return not configured when Contacts not set up."""
        registry = make_registry(contacts=None)
        result = await exec_find_sparse_contacts(registry)
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        contacts = AsyncMock()
        contacts.find_sparse_contacts = AsyncMock(return_value=[])
        registry = make_registry(contacts=contacts)
        
        result = await exec_find_sparse_contacts(registry)
        assert isinstance(result, str)
