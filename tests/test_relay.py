"""
Tests for relay client (direct DB writes to relay.db).
"""

import tempfile
from pathlib import Path

import pytest

from remy.relay.client import post_message_to_cowork, post_note


@pytest.fixture
def temp_data_dir():
    """Temporary directory for relay.db."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.mark.asyncio
async def test_post_message_to_cowork_creates_message(temp_data_dir):
    """Post message writes to relay.db."""
    ok = await post_message_to_cowork("Hello cowork", data_dir=temp_data_dir)
    assert ok is True

    import aiosqlite
    path = Path(temp_data_dir) / "relay.db"
    assert path.exists()
    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, from_agent, to_agent, content FROM messages"
        ) as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["from_agent"] == "remy"
    assert rows[0]["to_agent"] == "cowork"
    assert rows[0]["content"] == "Hello cowork"


@pytest.mark.asyncio
async def test_post_message_empty_returns_false(temp_data_dir):
    """Empty content returns False."""
    assert await post_message_to_cowork("", data_dir=temp_data_dir) is False
    assert await post_message_to_cowork("   ", data_dir=temp_data_dir) is False


@pytest.mark.asyncio
async def test_post_note_creates_note(temp_data_dir):
    """Post note writes to shared_notes."""
    ok = await post_note("Gmail audit complete", tags=["gmail", "audit"], data_dir=temp_data_dir)
    assert ok is True

    import aiosqlite
    path = Path(temp_data_dir) / "relay.db"
    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, from_agent, content, tags FROM shared_notes"
        ) as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["from_agent"] == "remy"
    assert rows[0]["content"] == "Gmail audit complete"
    import json
    assert json.loads(rows[0]["tags"]) == ["gmail", "audit"]
