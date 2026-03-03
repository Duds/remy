"""Tests for remy.ai.tools.bookmarks module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.bookmarks import (
    _is_valid_url,
    exec_list_bookmarks,
    exec_save_bookmark,
)

USER_ID = 42


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._knowledge_store = kwargs.get("knowledge_store")
    registry._fact_store = kwargs.get("fact_store")
    return registry


class TestIsValidUrl:
    """Tests for _is_valid_url."""

    def test_http_valid(self):
        assert _is_valid_url("http://example.com") is True

    def test_https_valid(self):
        assert _is_valid_url("https://example.com/path") is True

    def test_ftp_invalid(self):
        assert _is_valid_url("ftp://example.com") is False

    def test_no_scheme_invalid(self):
        assert _is_valid_url("example.com") is False


class TestExecSaveBookmark:
    """Tests for exec_save_bookmark."""

    @pytest.mark.asyncio
    async def test_missing_url_returns_message(self):
        registry = make_registry(fact_store=MagicMock())
        result = await exec_save_bookmark(registry, {"url": "", "note": ""}, USER_ID)
        assert "Please provide a URL" in result

    @pytest.mark.asyncio
    async def test_invalid_url_returns_message(self):
        registry = make_registry(fact_store=MagicMock())
        result = await exec_save_bookmark(
            registry, {"url": "not-a-url", "note": ""}, USER_ID
        )
        assert "valid URL" in result
        assert "http" in result

    @pytest.mark.asyncio
    async def test_no_memory_returns_message(self):
        registry = make_registry()
        registry._fact_store = None
        registry._knowledge_store = None
        result = await exec_save_bookmark(
            registry, {"url": "https://example.com", "note": ""}, USER_ID
        )
        assert "Memory not available" in result

    @pytest.mark.asyncio
    async def test_save_with_knowledge_store(self):
        store = AsyncMock()
        store.add_item = AsyncMock(return_value=1)
        registry = make_registry(knowledge_store=store)
        registry._fact_store = None
        result = await exec_save_bookmark(
            registry, {"url": "https://example.com", "note": "my note"}, USER_ID
        )
        assert "🔖 Bookmark saved" in result
        store.add_item.assert_called_once_with(
            USER_ID, "fact", "https://example.com — my note", {"category": "bookmark"}
        )

    @pytest.mark.asyncio
    async def test_save_with_fact_store(self):
        store = AsyncMock()
        store.add = AsyncMock(return_value=1)
        registry = make_registry(fact_store=store)
        registry._knowledge_store = None
        result = await exec_save_bookmark(
            registry, {"url": "https://example.com", "note": ""}, USER_ID
        )
        assert "🔖 Bookmark saved" in result
        store.add.assert_called_once_with(USER_ID, "https://example.com", "bookmark")


class TestExecListBookmarks:
    """Tests for exec_list_bookmarks."""

    @pytest.mark.asyncio
    async def test_no_memory_returns_message(self):
        registry = make_registry()
        registry._fact_store = None
        registry._knowledge_store = None
        result = await exec_list_bookmarks(registry, {}, USER_ID)
        assert "Memory not available" in result

    @pytest.mark.asyncio
    async def test_list_empty_with_knowledge_store(self):
        store = AsyncMock()
        store.get_by_type = AsyncMock(return_value=[])
        registry = make_registry(knowledge_store=store)
        registry._fact_store = None
        result = await exec_list_bookmarks(registry, {}, USER_ID)
        assert "No bookmarks saved" in result
        store.get_by_type.assert_called_once_with(USER_ID, "fact", limit=50)

    @pytest.mark.asyncio
    async def test_list_with_results_from_knowledge_store(self):
        from remy.models import KnowledgeItem

        items = [
            KnowledgeItem(
                entity_type="fact",
                content="https://a.com — note",
                metadata={"category": "bookmark"},
            ),
            KnowledgeItem(
                entity_type="fact",
                content="https://b.com",
                metadata={"category": "bookmark"},
            ),
            KnowledgeItem(
                entity_type="fact",
                content="other fact",
                metadata={"category": "other"},
            ),
        ]
        store = AsyncMock()
        store.get_by_type = AsyncMock(return_value=items)
        registry = make_registry(knowledge_store=store)
        registry._fact_store = None
        result = await exec_list_bookmarks(registry, {}, USER_ID)
        assert "2 item(s)" in result
        assert "https://a.com" in result
        assert "https://b.com" in result
        assert "other fact" not in result

    @pytest.mark.asyncio
    async def test_list_empty_with_fact_store(self):
        store = AsyncMock()
        store.get_by_category = AsyncMock(return_value=[])
        registry = make_registry(fact_store=store)
        registry._knowledge_store = None
        result = await exec_list_bookmarks(registry, {}, USER_ID)
        assert "No bookmarks saved" in result

    @pytest.mark.asyncio
    async def test_list_with_results_from_fact_store(self):
        store = AsyncMock()
        store.get_by_category = AsyncMock(
            return_value=[{"content": "https://x.com"}, {"content": "https://y.com"}]
        )
        registry = make_registry(fact_store=store)
        registry._knowledge_store = None
        result = await exec_list_bookmarks(registry, {}, USER_ID)
        assert "2 item(s)" in result
        assert "https://x.com" in result
        assert "https://y.com" in result
