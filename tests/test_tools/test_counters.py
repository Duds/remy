"""Tests for remy.ai.tools.counters — get/set/increment/reset counter tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.counters import (
    exec_get_counter,
    exec_increment_counter,
    exec_reset_counter,
    exec_set_counter,
)


USER_ID = 42


def make_registry(counter_store=None):
    """Mock registry with counter_store."""
    registry = MagicMock()
    registry._counter_store = counter_store
    return registry


@pytest.mark.asyncio
async def test_get_counter_no_store():
    """When counter_store is None, return not available."""
    registry = make_registry(counter_store=None)
    result = await exec_get_counter(registry, {"name": "sobriety_streak"}, USER_ID)
    assert "not available" in result.lower()


@pytest.mark.asyncio
async def test_get_counter_no_name():
    """When name is missing/empty, ask for name."""
    store = MagicMock()
    registry = make_registry(counter_store=store)
    result = await exec_get_counter(registry, {}, USER_ID)
    assert "name" in result.lower()
    store.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_counter_not_set():
    """When counter not set, return message."""
    store = MagicMock()
    store.get = AsyncMock(return_value=None)
    registry = make_registry(counter_store=store)
    result = await exec_get_counter(registry, {"name": "sobriety_streak"}, USER_ID)
    assert "no counter" in result.lower() or "not set" in result.lower()
    store.get.assert_called_once_with(USER_ID, "sobriety_streak")


@pytest.mark.asyncio
async def test_get_counter_returns_value():
    """When counter is set, return value and unit."""
    store = MagicMock()
    store.get = AsyncMock(
        return_value={"value": 14, "unit": "days", "updated_at": "2026-03-06"}
    )
    registry = make_registry(counter_store=store)
    result = await exec_get_counter(registry, {"name": "sobriety_streak"}, USER_ID)
    assert "14" in result
    assert "days" in result


@pytest.mark.asyncio
async def test_set_counter_no_store():
    """When counter_store is None, return not available."""
    registry = make_registry(counter_store=None)
    result = await exec_set_counter(
        registry, {"name": "sobriety_streak", "value": 5}, USER_ID
    )
    assert "not available" in result.lower()


@pytest.mark.asyncio
async def test_set_counter_success():
    """set_counter calls store.set and returns confirmation."""
    store = MagicMock()
    store.set = AsyncMock()
    registry = make_registry(counter_store=store)
    result = await exec_set_counter(
        registry, {"name": "sobriety_streak", "value": 5}, USER_ID
    )
    assert "set" in result.lower() and "5" in result
    store.set.assert_called_once_with(USER_ID, "sobriety_streak", 5, unit="days")


@pytest.mark.asyncio
async def test_increment_counter_success():
    """increment_counter calls store.increment and returns new value."""
    store = MagicMock()
    store.increment = AsyncMock(return_value=6)
    registry = make_registry(counter_store=store)
    result = await exec_increment_counter(
        registry, {"name": "sobriety_streak"}, USER_ID
    )
    assert "6" in result
    store.increment.assert_called_once_with(USER_ID, "sobriety_streak", by=1)


@pytest.mark.asyncio
async def test_reset_counter_success():
    """reset_counter calls store.reset and returns confirmation."""
    store = MagicMock()
    store.reset = AsyncMock()
    registry = make_registry(counter_store=store)
    result = await exec_reset_counter(registry, {"name": "sobriety_streak"}, USER_ID)
    assert "reset" in result.lower()
    store.reset.assert_called_once_with(USER_ID, "sobriety_streak")
