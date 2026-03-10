"""
Integration tests: every tool in TOOL_SCHEMAS is routable via ToolRegistry.dispatch.

Verifies that each tool name in the schema is recognised by the registry and
dispatches to an executor (no "Unknown tool"). Uses minimal or mock inputs;
some tools return "not available" or validation errors, which still proves routing.
"""

from __future__ import annotations

import pytest

from remy.ai.tools import TOOL_SCHEMAS, ToolRegistry


USER_ID = 42


def _all_tool_names():
    """All tool names from TOOL_SCHEMAS (single source of truth)."""
    return [s["name"] for s in TOOL_SCHEMAS]


def _minimal_input_for_tool(tool_name: str) -> dict:
    """
    Minimal input for each tool so dispatch reaches the executor without
    missing required keys. Executors may still return "not available" or errors.
    """
    minimal = {
        "run_board": {"topic": "test"},
        "search_gmail": {"query": "test"},
        "read_email": {"message_id": "id123"},
        "label_emails": {"message_ids": ["id1"]},
        "create_gmail_label": {"name": "Test"},
        "create_email_draft": {"to": "a@b.com", "subject": "S", "body": "B"},
        "search_contacts": {"query": "x"},
        "web_search": {"query": "test"},
        "price_check": {"item": "widget"},
        "read_file": {"path": "~/Projects/README.md"},
        "get_file_download_link": {"path": "~/Projects/README.md"},
        "list_directory": {"path": "~/Projects"},
        "write_file": {"path": "~/Projects/x.txt", "content": "x"},
        "append_file": {"path": "~/Projects/x.txt", "content": "x"},
        "find_files": {"pattern": "*.py"},
        "git_show_commit": {"ref": "HEAD"},
        "create_calendar_event": {"title": "T", "date": "2026-01-01", "time": "09:00"},
        "schedule_reminder": {"label": "Test", "frequency": "daily"},
        "set_one_time_reminder": {"label": "Test", "fire_at": "2026-12-31T09:00:00"},
        "breakdown_task": {"task": "test"},
        "remove_reminder": {"id": 999},
        "manage_memory": {"action": "add", "content": "test", "category": "other"},
        "manage_goal": {"action": "add", "title": "Test"},
        "get_counter": {"name": "test_counter"},
        "set_counter": {"name": "test_counter", "value": 0},
        "increment_counter": {"name": "test_counter"},
        "reset_counter": {"name": "test_counter"},
        "create_plan": {"title": "T", "steps": ["Step 1"]},
        "update_plan_step": {"step_id": 1},
        "update_plan_status": {"plan_id": 1, "status": "complete"},
        "update_plan": {"plan_id": 1},
        "search_files": {"query": "test"},
        "set_project": {"path": "~/Projects"},
        "organize_directory": {"path": "~/Projects"},
        "clean_directory": {"path": "~/Projects"},
        "save_bookmark": {"url": "https://example.com"},
        "get_contact_details": {"name": "X"},
        "update_contact_note": {"name": "X", "note": "n"},
        "read_gdoc": {"doc_id_or_url": "x"},
        "append_to_gdoc": {"doc_id_or_url": "x", "text": "t"},
        "grocery_list": {"action": "show"},
        "suggest_actions": {"actions": [{"label": "OK", "callback_id": "dismiss"}]},
        "react_to_message": {"emoji": "👍"},
        "run_claude_code": {"task": "echo ok"},
        "run_python": {"code": "print(1)"},
    }
    return minimal.get(tool_name, {})


def make_registry(**kwargs) -> ToolRegistry:
    """ToolRegistry with minimal defaults for integration tests."""
    defaults = dict(
        logs_dir="/tmp/test_logs",
        goal_store=None,
        fact_store=None,
        knowledge_store=None,
        board_orchestrator=None,
        claude_client=None,
        ollama_base_url="http://localhost:11434",
        model_complex="claude-sonnet-4-6",
    )
    defaults.update(kwargs)
    return ToolRegistry(**defaults)


@pytest.mark.parametrize("tool_name", _all_tool_names())
@pytest.mark.asyncio
async def test_dispatch_every_tool_routes(tool_name: str, tmp_path):
    """
    Every tool in TOOL_SCHEMAS is recognised by the registry and returns a string.
    We do not get 'Unknown tool: <name>'. Executors may return errors or 'not available'.
    """
    reg = make_registry(logs_dir=str(tmp_path))
    inp = _minimal_input_for_tool(tool_name)

    # set_proactive_chat and react_to_message need chat_id/message_id for some paths
    chat_id = 123 if tool_name in ("set_proactive_chat", "react_to_message") else None
    message_id = "456" if tool_name == "react_to_message" else None

    result = await reg.dispatch(
        tool_name, inp, USER_ID, chat_id=chat_id, message_id=message_id
    )

    assert isinstance(result, str), f"{tool_name} must return str"
    assert f"Unknown tool: {tool_name}" not in result, (
        f"Tool {tool_name} must be routed by registry (not unknown)"
    )


@pytest.mark.asyncio
async def test_dispatch_get_current_time_returns_au_time(tmp_path):
    """get_current_time is synchronous and returns Australia/Canberra time."""
    reg = make_registry(logs_dir=str(tmp_path))
    result = await reg.dispatch("get_current_time", {}, USER_ID)
    assert isinstance(result, str)
    assert (
        "Australia" in result
        or "Canberra" in result
        or "AEST" in result
        or "AEDT" in result
    )


@pytest.mark.asyncio
async def test_dispatch_suggest_actions_returns_attached(tmp_path):
    """suggest_actions is a no-op in dispatch and returns 'Attached.'."""
    reg = make_registry(logs_dir=str(tmp_path))
    result = await reg.dispatch(
        "suggest_actions",
        {"actions": [{"label": "OK", "callback_id": "dismiss"}]},
        USER_ID,
    )
    assert result == "Attached."


# Tools that need optional mocks to avoid filesystem/network in integration test
@pytest.mark.asyncio
async def test_dispatch_relay_tools_return_json_like(tmp_path):
    """Relay tools return JSON-like strings (or error payload)."""
    reg = make_registry(logs_dir=str(tmp_path))
    for name, inp in [
        ("relay_get_messages", {}),
        ("relay_get_tasks", {}),
    ]:
        result = await reg.dispatch(name, inp, USER_ID)
        assert isinstance(result, str)
        assert "Unknown tool" not in result
        # Either JSON object or error message
        assert (
            "messages" in result
            or "tasks" in result
            or "error" in result
            or "[]" in result
        )
