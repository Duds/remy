"""
Tests for relay_mcp server tool handlers (no ctx.request_context).

The MCP SDK can pass a string as the second argument to tool handlers;
we use module-level _db_connection and _get_db() instead. These tests
verify relay_get_messages and relay_get_tasks work with that pattern.

Requires mcp[cli] (e.g. from requirements-dev.txt). Skipped when mcp not installed.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("mcp")

# Import after path is set; relay_mcp is a package (relay_mcp/__init__.py)
from relay_mcp.server import (
    GetMessagesInput,
    GetTasksInput,
    _get_db,
    get_db,
    init_db,
    relay_get_messages,
    relay_get_tasks,
    server as server_module,
)


@pytest.fixture
def temp_relay_db():
    """Temporary SQLite DB with relay_mcp schema; _db_connection set for handlers."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    conn = get_db(path)
    init_db(conn)
    # Inject so _get_db() returns this connection (simulates lifespan)
    orig = server_module._db_connection
    server_module._db_connection = conn
    try:
        yield conn
    finally:
        server_module._db_connection = orig
        conn.close()
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_relay_get_messages_returns_json(temp_relay_db):
    """relay_get_messages returns JSON with agent, unread_count, messages (no ctx)."""
    params = GetMessagesInput(
        agent="cowork", unread_only=True, limit=20, mark_read=True
    )
    result = await relay_get_messages(params)
    data = json.loads(result)
    assert data["agent"] == "cowork"
    assert "unread_count" in data
    assert "messages" in data
    assert data["unread_count"] == 0
    assert data["messages"] == []


@pytest.mark.asyncio
async def test_relay_get_tasks_returns_json(temp_relay_db):
    """relay_get_tasks returns JSON with agent, pending_count, tasks (no ctx)."""
    params = GetTasksInput(agent="cowork", status="pending", limit=20)
    result = await relay_get_tasks(params)
    data = json.loads(result)
    assert data["agent"] == "cowork"
    assert "pending_count" in data
    assert "tasks" in data
    assert data["pending_count"] == 0
    assert data["tasks"] == []


@pytest.mark.asyncio
async def test_get_db_raises_when_not_initialised():
    """_get_db() raises RuntimeError when _db_connection is None."""
    orig = server_module._db_connection
    try:
        server_module._db_connection = None
        with pytest.raises(RuntimeError, match="database not initialised"):
            _get_db()
    finally:
        server_module._db_connection = orig
