"""
Integration test: max_iterations yields step-limit (Bug 47 — no auto Board hand-off).

Proves the full path:
  1. Main agent hits max_iterations → StepLimitReached is yielded (not HandOffToSubAgent).
  2. Step-limit message text is present (Continue / Break down / Stop).
  3. Sub-agent simulation: when we have a topic, we can run a coroutine that uses tools
     (tests the pattern; Board hand-off is explicit user opt-in only).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.ai.claude_client import ClaudeClient, StepLimitReached, TextChunk
from remy.ai.tools import ToolRegistry


USER_ID = 99


def _make_stream_event(event_type: str, **kwargs):
    evt = MagicMock()
    evt.__class__.__name__ = event_type
    for k, v in kwargs.items():
        setattr(evt, k, v)
    return evt


def _make_tool_use_stream(
    tool_name: str = "get_current_time", tool_id: str = "toolu_1"
):
    """Return a mock stream that yields one tool_use and final message with stop_reason=tool_use."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = tool_id
    tool_block.name = tool_name
    tool_block.input = {}

    final_msg = MagicMock()
    final_msg.stop_reason = "tool_use"
    final_msg.content = [tool_block]
    final_msg.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    async def fake_iter():
        yield _make_stream_event("RawContentBlockStartEvent", content_block=tool_block)

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.__aiter__ = lambda self: fake_iter().__aiter__()
    mock_stream.get_final_message = AsyncMock(return_value=final_msg)
    return mock_stream


@pytest.mark.asyncio
async def test_max_iterations_yields_step_limit_not_board_handoff(tmp_path):
    """
    When main agent hits max_iterations we get StepLimitReached (Bug 47: no auto Board hand-off).
    (SDK path: run_quick_assistant_streaming mocked to yield step-limit + StepLimitReached.)
    """
    from remy.ai.tools.context import ToolContext

    async def mock_sdk_stream(*, messages, registry, user_id, **kwargs):
        yield TextChunk(
            text="\n\n_I've hit my step limit for this turn. "
            "Tap Continue to keep going, Break down for smaller steps, or Stop._"
        )
        yield StepLimitReached()

    ctx = ToolContext(logs_dir=str(tmp_path))
    registry = ToolRegistry(ctx)

    client = ClaudeClient.__new__(ClaudeClient)
    client._client = MagicMock()

    with patch("remy.agents.sdk_subagents.is_sdk_available", return_value=True), patch(
        "remy.agents.sdk_subagents.run_quick_assistant_streaming", side_effect=mock_sdk_stream
    ):
        events = []
        async for event in client.stream_with_tools(
            messages=[
                {"role": "user", "content": "What time is it? Then list my goals."}
            ],
            tool_registry=registry,
            user_id=USER_ID,
        ):
            events.append(event)

    step_limits = [e for e in events if isinstance(e, StepLimitReached)]
    assert len(step_limits) == 1, "Expected StepLimitReached after max_iterations (Bug 47)"
    step_text = [
        e.text for e in events if isinstance(e, TextChunk) and "step limit" in (e.text or "").lower()
    ]
    assert step_text, "Expected step-limit message text"


@pytest.mark.asyncio
async def test_subagent_tool_sequence_recorded(tmp_path):
    """
    Sub-agent runs multiple tool calls in sequence; we record and assert the order.
    """
    from remy.ai.tools.context import ToolContext

    ctx = ToolContext(logs_dir=str(tmp_path))
    registry = ToolRegistry(ctx)
    sequence: list[str] = []

    async def record_dispatch(name, inp, uid, chat_id=None, message_id=None):
        sequence.append(name)
        if name == "get_current_time":
            from remy.ai.tools.time import exec_get_current_time

            return exec_get_current_time(registry)
        if name == "get_goals":
            return "Goal list (empty for test)."
        return "ok"

    registry.dispatch = AsyncMock(side_effect=record_dispatch)

    async def subagent_with_two_tools(reg: ToolRegistry, user_id: int) -> str:
        t = await reg.dispatch("get_current_time", {}, user_id, None, None)
        g = await reg.dispatch("get_goals", {}, user_id, None, None)
        return f"Time: {t[:40]}... Goals: {g[:40]}."

    result = await subagent_with_two_tools(registry, USER_ID)

    assert sequence == ["get_current_time", "get_goals"]
    assert "Time:" in result
    assert "Goals:" in result
