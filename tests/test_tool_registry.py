"""
Tests for remy/ai/tool_registry.py and the tool-use streaming path.

All external calls (Claude API, Ollama, diagnostics, memory stores) are mocked.
No real API calls or file I/O.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from remy.ai.tool_registry import ToolRegistry, TOOL_SCHEMAS
from remy.ai.claude_client import (
    ClaudeClient,
    TextChunk,
    ToolStatusChunk,
    ToolResultChunk,
    ToolTurnComplete,
    StreamEvent,
)
from remy.bot.handlers import _build_message_from_turn, _TOOL_TURN_PREFIX
from remy.models import ConversationTurn


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

USER_ID = 42


def make_registry(**kwargs) -> ToolRegistry:
    """Construct a ToolRegistry with sensible mock defaults."""
    defaults = dict(
        logs_dir="/tmp/test_logs",
        goal_store=None,
        fact_store=None,
        board_orchestrator=None,
        claude_client=None,
        ollama_base_url="http://localhost:11434",
        model_complex="claude-sonnet-4-6",
    )
    defaults.update(kwargs)
    return ToolRegistry(**defaults)


# --------------------------------------------------------------------------- #
# 1. Tool schema validation                                                    #
# --------------------------------------------------------------------------- #

def test_tool_schemas_count():
    """Check that we have a healthy number of tools."""
    assert len(TOOL_SCHEMAS) >= 5


def test_tool_schema_names():
    """Primary expected tool names are present."""
    names = {s["name"] for s in TOOL_SCHEMAS}
    expected = {"get_logs", "get_goals", "get_facts", "run_board", "check_status"}
    assert expected.issubset(names)


def test_tool_schemas_have_required_keys():
    """Each schema has name, description, and input_schema."""
    for schema in TOOL_SCHEMAS:
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["description"].strip()  # non-empty


def test_tool_schemas_input_schema_type():
    """Each input_schema has type=object and properties."""
    for schema in TOOL_SCHEMAS:
        inp = schema["input_schema"]
        assert inp["type"] == "object"
        assert "properties" in inp


def test_registry_schemas_property():
    """ToolRegistry.schemas returns TOOL_SCHEMAS."""
    reg = make_registry()
    assert reg.schemas is TOOL_SCHEMAS


# --------------------------------------------------------------------------- #
# 2. StreamEvent dataclasses                                                   #
# --------------------------------------------------------------------------- #

def test_text_chunk_dataclass():
    chunk = TextChunk(text="hello")
    assert chunk.text == "hello"


def test_tool_status_chunk_dataclass():
    chunk = ToolStatusChunk(tool_name="get_logs", tool_use_id="abc123")
    assert chunk.tool_name == "get_logs"
    assert chunk.tool_use_id == "abc123"
    assert chunk.tool_input == {}  # default_factory


def test_tool_result_chunk_dataclass():
    chunk = ToolResultChunk(tool_name="get_goals", tool_use_id="xyz", result="goals here")
    assert chunk.result == "goals here"


def test_tool_turn_complete_dataclass():
    turn = ToolTurnComplete(
        assistant_blocks=[{"type": "tool_use", "name": "get_logs"}],
        tool_result_blocks=[{"type": "tool_result", "content": "ok"}],
    )
    assert len(turn.assistant_blocks) == 1
    assert len(turn.tool_result_blocks) == 1


# --------------------------------------------------------------------------- #
# 3. _build_message_from_turn (conversation history reconstruction)            #
# --------------------------------------------------------------------------- #

def test_build_message_plain_text():
    """Regular turn returns plain text dict."""
    turn = ConversationTurn(role="user", content="Hello!")
    msg = _build_message_from_turn(turn)
    assert msg == {"role": "user", "content": "Hello!"}


def test_build_message_tool_turn():
    """Tool turns are deserialised from JSON sentinel."""
    blocks = [{"type": "tool_use", "id": "1", "name": "get_logs", "input": {}}]
    sentinel = _TOOL_TURN_PREFIX + json.dumps(blocks)
    turn = ConversationTurn(role="assistant", content=sentinel)
    msg = _build_message_from_turn(turn)
    assert msg["role"] == "assistant"
    assert isinstance(msg["content"], list)
    assert msg["content"][0]["type"] == "tool_use"


def test_build_message_tool_result_turn():
    """Tool result turns (user role) are deserialised correctly."""
    blocks = [{"type": "tool_result", "tool_use_id": "1", "content": "log data"}]
    sentinel = _TOOL_TURN_PREFIX + json.dumps(blocks)
    turn = ConversationTurn(role="user", content=sentinel)
    msg = _build_message_from_turn(turn)
    assert msg["role"] == "user"
    assert msg["content"][0]["type"] == "tool_result"


def test_build_message_invalid_json_sentinel_falls_back():
    """Corrupted tool sentinel falls back to plain text."""
    bad = _TOOL_TURN_PREFIX + "NOT_VALID_JSON"
    turn = ConversationTurn(role="assistant", content=bad)
    msg = _build_message_from_turn(turn)
    # Falls back to treating entire content as plain string
    assert msg["role"] == "assistant"
    assert isinstance(msg["content"], str)


# --------------------------------------------------------------------------- #
# 4. ToolRegistry.dispatch routing                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error():
    reg = make_registry()
    result = await reg.dispatch("nonexistent_tool", {}, USER_ID)
    assert "Unknown tool" in result


@pytest.mark.asyncio
async def test_dispatch_get_logs_summary():
    """dispatch('get_logs') calls get_error_summary and get_recent_logs.

    startup mode makes 4 calls to asyncio.to_thread:
        get_session_start_line, get_session_start, get_error_summary, get_recent_logs
    """
    reg = make_registry(logs_dir="/tmp")
    with patch("remy.ai.tool_registry.asyncio.to_thread") as mock_thread:
        mock_thread.side_effect = [
            0,              # get_session_start_line → int
            None,           # get_session_start → None (no timestamp found)
            "Error summary",  # get_error_summary
            "Tail content",   # get_recent_logs
        ]
        result = await reg.dispatch("get_logs", {"mode": "summary"}, USER_ID)
    assert "Error summary" in result or "Tail content" in result


@pytest.mark.asyncio
async def test_dispatch_get_logs_tail():
    reg = make_registry(logs_dir="/tmp")
    with patch("remy.ai.tool_registry.asyncio.to_thread", return_value="log lines") as mock_thread:
        result = await reg.dispatch("get_logs", {"mode": "tail", "lines": 10}, USER_ID)
    assert "log lines" in result


@pytest.mark.asyncio
async def test_dispatch_get_logs_errors():
    """dispatch('get_logs', errors) makes 3 asyncio.to_thread calls:
        get_session_start_line, get_session_start, get_error_summary
    """
    reg = make_registry(logs_dir="/tmp")
    with patch("remy.ai.tool_registry.asyncio.to_thread") as mock_thread:
        mock_thread.side_effect = [
            0,             # get_session_start_line → int
            None,          # get_session_start → None
            "errors here", # get_error_summary
        ]
        result = await reg.dispatch("get_logs", {"mode": "errors"}, USER_ID)
    assert "errors here" in result


@pytest.mark.asyncio
async def test_dispatch_get_goals_no_store():
    """get_goals without a goal_store returns a clear message."""
    reg = make_registry(goal_store=None)
    result = await reg.dispatch("get_goals", {}, USER_ID)
    assert "not available" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_get_goals_returns_list():
    goal_store = MagicMock()
    goal_store.get_active = AsyncMock(return_value=[
        {"title": "Launch remy", "description": "Go live"},
        {"title": "Write tests"},
    ])
    reg = make_registry(goal_store=goal_store)
    result = await reg.dispatch("get_goals", {"limit": 5}, USER_ID)
    assert "Launch remy" in result
    assert "Write tests" in result


@pytest.mark.asyncio
async def test_dispatch_get_goals_empty():
    goal_store = MagicMock()
    goal_store.get_active = AsyncMock(return_value=[])
    reg = make_registry(goal_store=goal_store)
    result = await reg.dispatch("get_goals", {}, USER_ID)
    assert "No active goals" in result


@pytest.mark.asyncio
async def test_dispatch_get_facts_no_store():
    reg = make_registry(fact_store=None)
    result = await reg.dispatch("get_facts", {}, USER_ID)
    assert "not available" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_get_facts_returns_list():
    fact_store = MagicMock()
    fact_store.get_for_user = AsyncMock(return_value=[
        {"category": "name", "content": "User's name is Dale"},
        {"category": "location", "content": "User is in Sydney"},
    ])
    reg = make_registry(fact_store=fact_store)
    result = await reg.dispatch("get_facts", {}, USER_ID)
    assert "Dale" in result
    assert "Sydney" in result


@pytest.mark.asyncio
async def test_dispatch_get_facts_with_category_filter():
    fact_store = MagicMock()
    fact_store.get_by_category = AsyncMock(return_value=[])
    reg = make_registry(fact_store=fact_store)
    await reg.dispatch("get_facts", {"category": "name"}, USER_ID)
    fact_store.get_by_category.assert_called_once_with(USER_ID, "name")


@pytest.mark.asyncio
async def test_dispatch_manage_memory_add():
    ks = MagicMock()
    ks.add_item = AsyncMock(return_value=123)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "add",
        "content": "I like blue",
        "category": "preference"
    }, USER_ID)
    
    assert "Fact stored" in result
    assert "123" in result
    ks.add_item.assert_called_once_with(USER_ID, "fact", "I like blue", {"category": "preference"})


@pytest.mark.asyncio
async def test_dispatch_manage_memory_update():
    ks = MagicMock()
    ks.update = AsyncMock(return_value=True)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "update",
        "fact_id": 456,
        "content": "I like red",
        "category": "preference"
    }, USER_ID)
    
    assert "Fact 456 updated" in result
    ks.update.assert_called_once_with(USER_ID, 456, "I like red", {"category": "preference"})


@pytest.mark.asyncio
async def test_dispatch_manage_memory_delete():
    ks = MagicMock()
    ks.delete = AsyncMock(return_value=True)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "delete",
        "fact_id": 789
    }, USER_ID)
    
    assert "Fact 789 deleted" in result
    ks.delete.assert_called_once_with(USER_ID, 789)


@pytest.mark.asyncio
async def test_dispatch_run_board_no_orchestrator():
    reg = make_registry(board_orchestrator=None)
    result = await reg.dispatch("run_board", {"topic": "test"}, USER_ID)
    assert "not available" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_run_board_calls_orchestrator():
    board = MagicMock()
    board.run_board = AsyncMock(return_value="Board report here")
    reg = make_registry(board_orchestrator=board)
    result = await reg.dispatch("run_board", {"topic": "My quarterly focus"}, USER_ID)
    assert "Board report here" in result
    board.run_board.assert_called_once_with("My quarterly focus")


@pytest.mark.asyncio
async def test_dispatch_run_board_empty_topic():
    board = MagicMock()
    board.run_board = AsyncMock(return_value="ok")
    reg = make_registry(board_orchestrator=board)
    result = await reg.dispatch("run_board", {"topic": ""}, USER_ID)
    assert "no topic" in result.lower()
    board.run_board.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_check_status_claude_available():
    claude = MagicMock()
    claude.ping = AsyncMock(return_value=True)
    reg = make_registry(claude_client=claude)
    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http.return_value)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.return_value.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                json=lambda: {"models": [{"name": "llama3"}]},
            )
        )
        result = await reg.dispatch("check_status", {}, USER_ID)
    assert "online" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_manage_goal_add():
    ks = MagicMock()
    ks.add_item = AsyncMock(return_value=123)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_goal", {
        "action": "add",
        "title": "Learn Rust",
        "description": "Read the book"
    }, USER_ID)
    
    assert "Goal added" in result
    assert "123" in result
    ks.add_item.assert_called_once_with(USER_ID, "goal", "Learn Rust", {"status": "active", "description": "Read the book"})


@pytest.mark.asyncio
async def test_dispatch_manage_goal_complete():
    from remy.models import KnowledgeItem
    item = KnowledgeItem(id=456, entity_type="goal", content="Launch", metadata={"status": "active"}, confidence=1.0)
    
    ks = MagicMock()
    ks.get_by_type = AsyncMock(return_value=[item])
    ks.update = AsyncMock(return_value=True)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_goal", {
        "action": "complete",
        "goal_id": 456
    }, USER_ID)
    
    assert "marked as completed" in result
    ks.update.assert_called_once_with(USER_ID, 456, metadata={"status": "completed"})


@pytest.mark.asyncio
async def test_dispatch_handles_tool_exception():
    """Exceptions in tool executors are caught and returned as error strings."""
    goal_store = MagicMock()
    goal_store.get_active = AsyncMock(side_effect=RuntimeError("DB locked"))
    reg = make_registry(goal_store=goal_store)
    result = await reg.dispatch("get_goals", {}, USER_ID)
    assert "error" in result.lower() or "DB locked" in result


# --------------------------------------------------------------------------- #
# 5. ClaudeClient.stream_with_tools — agentic loop behaviour                   #
# --------------------------------------------------------------------------- #

def _make_stream_event(delta_type: str, **kwargs):
    """Create a minimal mock stream event."""
    evt = MagicMock()
    evt.__class__.__name__ = delta_type
    for k, v in kwargs.items():
        setattr(evt, k, v)
    return evt


@pytest.mark.asyncio
async def test_stream_with_tools_yields_text_chunks():
    """
    When Claude returns end_turn (no tool calls), only TextChunks are yielded.
    """
    # Mock the raw stream events
    delta_event = _make_stream_event("RawContentBlockDeltaEvent")
    delta = MagicMock()
    delta.type = "text_delta"
    delta.text = "Hello!"
    delta_event.delta = delta

    # Mock final message (no tool use)
    final_msg = MagicMock()
    final_msg.stop_reason = "end_turn"
    final_msg.content = [MagicMock(type="text", text="Hello!")]

    # Build async iterator for stream events
    async def fake_stream_iter():
        yield delta_event

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.__aiter__ = lambda self: fake_stream_iter().__aiter__()
    mock_stream.get_final_message = AsyncMock(return_value=final_msg)

    tool_registry = make_registry()

    client = ClaudeClient.__new__(ClaudeClient)
    client._client = MagicMock()
    client._client.messages.stream = MagicMock(return_value=mock_stream)

    events = []
    async for event in client.stream_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tool_registry=tool_registry,
        user_id=USER_ID,
    ):
        events.append(event)

    text_events = [e for e in events if isinstance(e, TextChunk)]
    assert len(text_events) >= 1
    assert text_events[0].text == "Hello!"
    # No tool events since stop_reason = end_turn
    tool_events = [e for e in events if isinstance(e, ToolTurnComplete)]
    assert len(tool_events) == 0
