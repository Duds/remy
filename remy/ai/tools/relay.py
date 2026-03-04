"""Relay tool executors — read/post messages and tasks to cowork (US-claude-desktop-relay)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ...config import settings
from ...relay.client import (
    get_messages_for_remy,
    get_tasks_for_remy,
    post_message_to_cowork,
    post_note,
    update_task,
)

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)

REMY_AGENT = "remy"
COWORK_AGENT = "cowork"


def _relay_db_path() -> str:
    """Path to relay DB — same as shared relay server (data/relay.db when run from repo)."""
    return settings.relay_db_path_resolved


async def exec_relay_get_messages(
    registry: ToolRegistry,
    inp: dict,
    user_id: int,
) -> str:
    """Get messages for Remy from the relay inbox."""
    unread_only = inp.get("unread_only", True)
    mark_read = inp.get("mark_read", True)
    limit = min(int(inp.get("limit", 20)), 100)

    try:
        messages, unread_count = await get_messages_for_remy(
            agent=REMY_AGENT,
            unread_only=unread_only,
            mark_read=mark_read,
            limit=limit,
            db_path=_relay_db_path(),
        )
        return json.dumps(
            {
                "agent": REMY_AGENT,
                "unread_count": unread_count,
                "messages": messages,
            },
            indent=2,
        )
    except Exception as e:
        logger.warning("relay_get_messages failed: %s", e)
        return json.dumps(
            {
                "error": f"Relay unavailable: {e}",
                "agent": REMY_AGENT,
                "unread_count": 0,
                "messages": [],
            }
        )


async def exec_relay_post_message(
    registry: ToolRegistry,
    inp: dict,
    user_id: int,
) -> str:
    """Post a message from Remy to cowork."""
    content = (inp.get("content") or "").strip()
    if not content:
        return json.dumps({"error": "content is required", "status": "failed"})

    thread_id = inp.get("thread_id") or None

    try:
        result = await post_message_to_cowork(
            content=content,
            from_agent=REMY_AGENT,
            to_agent=COWORK_AGENT,
            thread_id=thread_id,
            db_path=_relay_db_path(),
        )
        if result is None:
            return json.dumps({"error": "Failed to post message", "status": "failed"})
        return json.dumps(result)
    except Exception as e:
        logger.warning("relay_post_message failed: %s", e)
        return json.dumps({"error": str(e), "status": "failed"})


async def exec_relay_get_tasks(
    registry: ToolRegistry,
    inp: dict,
    user_id: int,
) -> str:
    """Get tasks assigned to Remy from the relay."""
    status = inp.get("status", "pending")
    limit = min(int(inp.get("limit", 20)), 100)

    try:
        tasks, pending_count = await get_tasks_for_remy(
            agent=REMY_AGENT,
            status=status if status else None,
            limit=limit,
            db_path=_relay_db_path(),
        )
        return json.dumps(
            {
                "agent": REMY_AGENT,
                "pending_count": pending_count,
                "tasks": tasks,
            },
            indent=2,
        )
    except Exception as e:
        logger.warning("relay_get_tasks failed: %s", e)
        return json.dumps(
            {"error": str(e), "agent": REMY_AGENT, "pending_count": 0, "tasks": []}
        )


async def exec_relay_update_task(
    registry: ToolRegistry,
    inp: dict,
    user_id: int,
) -> str:
    """Update a relay task (claim, complete, or flag)."""
    task_id = (inp.get("task_id") or "").strip()
    status = (inp.get("status") or "").strip()
    if not task_id or not status:
        return json.dumps(
            {"error": "task_id and status are required", "updated": False}
        )

    result_text = (inp.get("result") or "").strip() or None
    notes = (inp.get("notes") or "").strip() or None

    try:
        result = await update_task(
            task_id=task_id,
            status=status,
            result=result_text,
            notes=notes,
            db_path=_relay_db_path(),
        )
        if result is None:
            return json.dumps(
                {
                    "error": "Task not found or invalid status",
                    "task_id": task_id,
                    "updated": False,
                }
            )
        return json.dumps(result)
    except Exception as e:
        logger.warning("relay_update_task failed: %s", e)
        return json.dumps({"error": str(e), "task_id": task_id, "updated": False})


async def exec_relay_post_note(
    registry: ToolRegistry,
    inp: dict,
    user_id: int,
) -> str:
    """Post a shared note to the relay for cowork to read."""
    content = (inp.get("content") or "").strip()
    if not content:
        return json.dumps({"error": "content is required", "status": "failed"})

    tags = inp.get("tags")
    if isinstance(tags, list):
        tags = [str(t) for t in tags][:10]
    else:
        tags = []

    try:
        result = await post_note(
            content=content,
            from_agent=REMY_AGENT,
            tags=tags,
            db_path=_relay_db_path(),
        )
        if result is None:
            return json.dumps({"error": "Failed to post note", "status": "failed"})
        return json.dumps(result)
    except Exception as e:
        logger.warning("relay_post_note failed: %s", e)
        return json.dumps({"error": str(e), "status": "failed"})
