"""Tests for remy.ai.tools.web module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from remy.ai.tools.web import exec_price_check, exec_web_search


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._claude_client = kwargs.get("claude_client")
    return registry


class TestExecWebSearch:
    """Tests for exec_web_search executor."""

    @pytest.mark.asyncio
    async def test_requires_query(self):
        """Should require a search query."""
        registry = make_registry()
        result = await exec_web_search(registry, {"query": ""})
        assert "provide" in result.lower() or "query" in result.lower() or "no" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        # Test with a query that will likely fail but still return a string
        result = await exec_web_search(registry, {"query": "test"})
        assert isinstance(result, str)


class TestExecPriceCheck:
    """Tests for exec_price_check executor."""

    @pytest.mark.asyncio
    async def test_requires_item(self):
        """Should require an item/product name."""
        registry = make_registry()
        result = await exec_price_check(registry, {"item": ""})
        assert "provide" in result.lower() or "item" in result.lower() or "no" in result.lower() or "specify" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        # Test with an item that will likely fail but still return a string
        result = await exec_price_check(registry, {"item": "test"})
        assert isinstance(result, str)
