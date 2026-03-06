"""Tests for lifecycle hooks (SAD v7): HookEvents, emit, MESSAGE_SENT / HEARTBEAT_*."""

from __future__ import annotations

import pytest

from remy.hooks.lifecycle import HookContext, HookEvents, HookManager, hook_manager


def test_hook_events_include_message_sent_and_heartbeat():
    assert hasattr(HookEvents, "MESSAGE_SENT")
    assert HookEvents.MESSAGE_SENT.value == "message_sent"
    assert hasattr(HookEvents, "HEARTBEAT_START")
    assert HookEvents.HEARTBEAT_START.value == "heartbeat_start"
    assert hasattr(HookEvents, "HEARTBEAT_END")
    assert HookEvents.HEARTBEAT_END.value == "heartbeat_end"


@pytest.mark.asyncio
async def test_emit_runs_handlers_and_returns_context():
    manager = HookManager()
    seen = []

    async def handler(ctx: HookContext) -> HookContext:
        seen.append(ctx.event)
        return ctx

    manager.register(HookEvents.HEARTBEAT_START, handler)
    result = await manager.emit(HookEvents.HEARTBEAT_START, {"chat_id": 123})
    assert result.event == HookEvents.HEARTBEAT_START
    assert result.data.get("chat_id") == 123
    assert seen == [HookEvents.HEARTBEAT_START]


@pytest.mark.asyncio
async def test_emit_cancelled_stops_chain():
    manager = HookManager()
    order = []

    async def cancel_handler(ctx: HookContext) -> HookContext:
        order.append("cancel")
        ctx.cancelled = True
        return ctx

    async def never_called(ctx: HookContext) -> HookContext:
        order.append("never")
        return ctx

    manager.register(HookEvents.HEARTBEAT_END, cancel_handler)
    manager.register(HookEvents.HEARTBEAT_END, never_called)
    result = await manager.emit(HookEvents.HEARTBEAT_END, {})
    assert result.cancelled is True
    assert order == ["cancel"]


@pytest.mark.asyncio
async def test_get_stats():
    manager = HookManager()
    await manager.emit(HookEvents.MESSAGE_SENT, {"user_id": 1})
    stats = manager.get_stats()
    assert stats["total_emissions"] >= 1
    assert "message_sent" in stats["emissions_by_event"] or stats["total_emissions"] > 0
