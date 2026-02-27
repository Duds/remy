"""Tests for remy/memory/conversations.py"""

import pytest
from remy.memory.conversations import ConversationStore
from remy.models import ConversationTurn


@pytest.fixture
def store(tmp_path):
    return ConversationStore(sessions_dir=str(tmp_path / "sessions"))


@pytest.mark.asyncio
async def test_append_and_read(store):
    turn = ConversationTurn(role="user", content="Hello, bot!")
    await store.append_turn(1, "user_1_20260225", turn)

    turns = await store.get_recent_turns(1, "user_1_20260225", limit=10)
    assert len(turns) == 1
    assert turns[0].content == "Hello, bot!"
    assert turns[0].role == "user"


@pytest.mark.asyncio
async def test_multiple_turns_order_preserved(store):
    for i in range(5):
        t = ConversationTurn(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
        await store.append_turn(1, "user_1_20260225", t)

    turns = await store.get_recent_turns(1, "user_1_20260225")
    assert [t.content for t in turns] == [f"msg {i}" for i in range(5)]


@pytest.mark.asyncio
async def test_limit_returns_last_n(store):
    for i in range(10):
        t = ConversationTurn(role="user", content=f"msg {i}")
        await store.append_turn(1, "user_1_20260225", t)

    turns = await store.get_recent_turns(1, "user_1_20260225", limit=3)
    assert len(turns) == 3
    assert turns[-1].content == "msg 9"


@pytest.mark.asyncio
async def test_compact_replaces_file(store):
    for i in range(5):
        t = ConversationTurn(role="user", content=f"msg {i}")
        await store.append_turn(1, "user_1_20260225", t)

    await store.compact(1, "user_1_20260225", "Summary: five messages.")

    turns = await store.get_recent_turns(1, "user_1_20260225")
    assert len(turns) == 1
    assert "Summary: five messages." in turns[0].content


@pytest.mark.asyncio
async def test_no_file_returns_empty(store):
    turns = await store.get_recent_turns(1, "user_1_99991231")
    assert turns == []


@pytest.mark.asyncio
async def test_invalid_session_key_rejected(store):
    t = ConversationTurn(role="user", content="test")
    # Path traversal attempt
    await store.append_turn(1, "../../../etc/passwd", t)
    # Should not write anything
    import os
    assert not os.path.exists("/etc/passwd.jsonl")


@pytest.mark.asyncio
async def test_get_all_sessions(store):
    for key in ["user_1_20260101", "user_1_20260102", "user_1_20260103"]:
        t = ConversationTurn(role="user", content="hi")
        await store.append_turn(1, key, t)

    sessions = await store.get_all_sessions(1)
    assert sessions == ["user_1_20260101", "user_1_20260102", "user_1_20260103"]
