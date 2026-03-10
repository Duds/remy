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
    async def test_save_without_knowledge_store_returns_memory_not_available(self):
        """Phase 1.4: No fallback to fact_store; returns clear message when knowledge_store is None."""
        store = AsyncMock()
        store.add = AsyncMock(return_value=1)
        registry = make_registry(fact_store=store)
        registry._knowledge_store = None
        result = await exec_save_bookmark(
            registry, {"url": "https://example.com", "note": ""}, USER_ID
        )
        assert "Memory not available" in result
        store.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_with_valid_tag_stores_metadata(self):
        """US-bookmarks-tag-buttons: optional tag preferences/work/personal is stored."""
        store = AsyncMock()
        store.add_item = AsyncMock(return_value=1)
        registry = make_registry(knowledge_store=store)
        registry._fact_store = None
        result = await exec_save_bookmark(
            registry,
            {"url": "https://example.com", "note": "my note", "tag": "work"},
            USER_ID,
        )
        assert "🔖 Bookmark saved" in result
        assert "tag: work" in result
        call_kw = store.add_item.call_args[1]
        assert call_kw.get("metadata", {}).get("tag") == "work"

    @pytest.mark.asyncio
    async def test_save_with_invalid_tag_returns_error(self):
        """Invalid tag returns clear error and lists allowed tags."""
        store = AsyncMock()
        registry = make_registry(knowledge_store=store)
        result = await exec_save_bookmark(
            registry,
            {"url": "https://example.com", "note": "", "tag": "invalid"},
            USER_ID,
        )
        assert "Invalid tag" in result
        assert "preferences" in result or "work" in result or "personal" in result
        store.add_item.assert_not_called()


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

    @pytest.mark.asyncio
    async def test_list_filters_by_tag_when_tag_in_allowed_set(self):
        """US-bookmarks-tag-buttons: list_bookmarks with tag=work returns only work bookmarks."""
        from remy.models import KnowledgeItem

        items = [
            KnowledgeItem(
                entity_type="fact",
                content="https://work.com — work link",
                metadata={"category": "bookmark", "tag": "work"},
            ),
            KnowledgeItem(
                entity_type="fact",
                content="https://personal.com",
                metadata={"category": "bookmark", "tag": "personal"},
            ),
        ]
        store = AsyncMock()
        store.get_by_type = AsyncMock(return_value=items)
        registry = make_registry(knowledge_store=store)
        registry._fact_store = None
        result = await exec_list_bookmarks(
            registry, {"tag": "work"}, USER_ID
        )
        assert "1 item(s)" in result or "work" in result
        assert "https://work.com" in result
        assert "tag: work" in result or "(tag: work)" in result
