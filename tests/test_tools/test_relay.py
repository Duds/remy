"""Tests for relay tool executors (US-claude-desktop-relay)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from remy.ai.tools import relay


def make_registry() -> MagicMock:
    return MagicMock()


@pytest.fixture
def temp_db_path():
    """Temp path for relay DB (used as settings.relay_db_path_resolved)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_exec_relay_get_messages_empty(temp_db_path):
    """relay_get_messages returns JSON with agent, unread_count, messages."""
    with patch("remy.ai.tools.relay.settings") as mock_settings:
        mock_settings.relay_db_path_resolved = temp_db_path
        registry = make_registry()
        result = await relay.exec_relay_get_messages(registry, {}, user_id=1)
    data = json.loads(result)
    assert data.get("agent") == "remy"
    assert "unread_count" in data
    assert "messages" in data
    assert data["unread_count"] == 0
    assert data["messages"] == []


@pytest.mark.asyncio
async def test_exec_relay_post_message_success(temp_db_path):
    """relay_post_message writes to DB and returns success JSON."""
    from remy.relay.client import _ensure_db

    await _ensure_db(Path(temp_db_path))

    with patch("remy.ai.tools.relay.settings") as mock_settings:
        mock_settings.relay_db_path_resolved = temp_db_path
        registry = make_registry()
        post_result = await relay.exec_relay_post_message(
            registry, {"content": "Hello from Remy"}, user_id=1
        )
    data = json.loads(post_result)
    assert data.get("status") == "sent" and data.get("message_id")


@pytest.mark.asyncio
async def test_exec_relay_get_tasks_empty(temp_db_path):
    """relay_get_tasks returns JSON with agent, pending_count, tasks."""
    with patch("remy.ai.tools.relay.settings") as mock_settings:
        mock_settings.relay_db_path_resolved = temp_db_path
        registry = make_registry()
        result = await relay.exec_relay_get_tasks(
            registry, {"status": "pending"}, user_id=1
        )
    data = json.loads(result)
    assert data.get("agent") == "remy"
    assert "pending_count" in data
    assert "tasks" in data
