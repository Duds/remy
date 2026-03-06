"""Tests for compaction + lifecycle hooks (SAD v7): context.cancelled skips compaction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.hooks import HookEvents, hook_manager
from remy.memory.compaction import CompactionConfig, CompactionResult, CompactionService


@pytest.fixture
def store():
    return AsyncMock()


@pytest.fixture
def claude_client():
    return AsyncMock()


@pytest.mark.asyncio
async def test_compaction_respects_cancelled_hook(store, claude_client, tmp_path):
    """When a handler sets context.cancelled on BEFORE_COMPACTION, compaction is skipped."""
    store.get_recent_turns = AsyncMock(return_value=[
        type("T", (), {"content": "msg", "role": "user"})(),
        type("T", (), {"content": "reply", "role": "assistant"})(),
    ] * 30)
    for t in (store.get_recent_turns.return_value or []):
        t.content = "x" * 500
    claude_client.complete = AsyncMock(return_value="Summary.")

    async def cancel_compaction(ctx):
        ctx.cancelled = True
        return ctx

    hook_manager.register(HookEvents.BEFORE_COMPACTION, cancel_compaction)
    try:
        service = CompactionService(
            conv_store=store,
            claude_client=claude_client,
            config=CompactionConfig(token_threshold=100, turn_threshold=10),
        )
        result = await service.check_and_compact(user_id=1, session_key="user_1_20260101")
        assert result.compacted is False
        assert "cancelled" in result.reason.lower()
        claude_client.complete.assert_not_called()
    finally:
        hook_manager.unregister(HookEvents.BEFORE_COMPACTION, cancel_compaction)


def test_compaction_config_default_token_threshold():
    """CompactionConfig default token_threshold is 40_000 (SAD v7)."""
    config = CompactionConfig()
    assert config.token_threshold == 40_000
