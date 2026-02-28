"""Memory and status tool executors."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_get_logs(registry: ToolRegistry, inp: dict) -> str:
    """Read remy's log file for diagnostics."""
    from ...diagnostics import (
        get_error_summary, get_recent_logs,
        get_session_start, get_session_start_line, _since_dt,
    )

    mode = inp.get("mode", "summary")
    lines = min(int(inp.get("lines", 30)), 100)
    since_param = inp.get("since")

    if since_param is None and mode in ("summary", "errors"):
        since_param = "startup"

    since_dt_val = None
    since_line_val = None
    if since_param == "startup":
        since_line_val = await asyncio.to_thread(get_session_start_line, registry._logs_dir)
        ts = await asyncio.to_thread(get_session_start, registry._logs_dir)
        since_label = f"session start ({ts.strftime('%Y-%m-%d %H:%M:%S')})" if ts else "session start"
    elif since_param in ("1h", "6h", "24h"):
        since_dt_val = _since_dt(since_param)
        since_label = f"last {since_param}"
    else:
        since_label = "all time"

    if mode == "tail":
        result = await asyncio.to_thread(
            get_recent_logs, registry._logs_dir, lines, None, since_dt_val, since_line_val
        )
        return f"Last {lines} log lines ({since_label}):\n\n{result}"
    elif mode == "errors":
        result = await asyncio.to_thread(
            get_error_summary, registry._logs_dir, 10, since_dt_val, since_line_val
        )
        return f"Error/warning summary ({since_label}):\n\n{result}"
    else:
        summary = await asyncio.to_thread(
            get_error_summary, registry._logs_dir, 5, since_dt_val, since_line_val
        )
        tail = await asyncio.to_thread(
            get_recent_logs, registry._logs_dir, 10, None, since_dt_val, since_line_val
        )
        return f"Diagnostics summary ({since_label}):\n\n{summary}\n\nRecent log tail (10 lines):\n{tail}"


async def exec_get_goals(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Retrieve the user's active goals from memory."""
    if registry._knowledge_store is None:
        if registry._goal_store is None:
            return "Goal store not available — memory system not initialised."
        limit = min(int(inp.get("limit", 10)), 50)
        goals = await registry._goal_store.get_active(user_id, limit=limit)
        if not goals:
            return "No active goals found."
        lines = []
        for g in goals:
            title = g.get("title", "Untitled")
            desc = g.get("description", "")
            gid = g.get("id", "?")
            line = f"• [ID:{gid}] {title}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        return f"Active goals ({len(goals)}):\n" + "\n".join(lines)

    limit = min(int(inp.get("limit", 10)), 50)
    goals = await registry._knowledge_store.get_by_type(user_id, "goal", limit=limit)

    if not goals:
        return "No active goals found."

    lines = []
    for g in goals:
        status = g.metadata.get("status", "active")
        if status != "active":
            continue
        desc = g.metadata.get("description", "")
        line = f"• [ID:{g.id}] {g.content}"
        if desc:
            line += f" — {desc}"
        lines.append(line)

    if not lines:
        return "No active goals found."

    return (
        f"Active goals ({len(lines)}):\n"
        + "\n".join(lines)
        + "\n\n(Use the ID with manage_goal to update, complete, or delete a goal)"
    )


async def exec_get_facts(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Retrieve facts stored about the user in memory."""
    category = inp.get("category")
    limit = min(int(inp.get("limit", 20)), 100)

    if registry._knowledge_store is not None:
        facts = await registry._knowledge_store.get_by_type(user_id, "fact", limit=limit)
        if category:
            facts = [f for f in facts if f.metadata.get("category") == category]
        if not facts:
            cat_str = f" in category '{category}'" if category else ""
            return f"No facts found{cat_str}."
        lines = []
        for f in facts:
            cat = f.metadata.get("category", "other")
            lines.append(f"[ID:{f.id}] [{cat}] {f.content}")
        cat_str = f" (category: {category})" if category else ""
        return f"Stored facts{cat_str} ({len(facts)}):\n" + "\n".join(lines)

    if registry._fact_store is None:
        return "Fact store not available — memory system not initialised."
    if category:
        facts = await registry._fact_store.get_by_category(user_id, category)
        facts = facts[:limit]
    else:
        facts = await registry._fact_store.get_for_user(user_id, limit=limit)
    if not facts:
        cat_str = f" in category '{category}'" if category else ""
        return f"No facts found{cat_str}."
    lines = []
    for f in facts:
        cat = f.get("category", "other")
        content = f.get("content", "")
        lines.append(f"[{cat}] {content}")
    cat_str = f" (category: {category})" if category else ""
    return f"Stored facts{cat_str} ({len(facts)}):\n" + "\n".join(lines)


async def exec_run_board(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Convene the Board of Directors for deep analysis."""
    if registry._board_orchestrator is None:
        return "Board of Directors not available."

    topic = inp.get("topic", "").strip()
    if not topic:
        return "Board: no topic provided."

    report = await registry._board_orchestrator.run_board(topic)
    return report


async def exec_check_status(registry: ToolRegistry) -> str:
    """Check the availability of backend services."""
    import httpx

    lines = []

    if registry._claude_client is not None:
        try:
            available = await registry._claude_client.ping()
            lines.append(
                f"Claude ({registry._model_complex}): {'✅ online' if available else '❌ offline'}"
            )
        except Exception as e:
            lines.append(f"Claude: ❌ error ({e})")
    else:
        lines.append("Claude: ⚠️  client not configured")

    if registry._mistral_client is not None:
        available = await registry._mistral_client.is_available()
        lines.append(f"Mistral: {'✅ online' if available else '❌ offline'}")

    if registry._moonshot_client is not None:
        available = await registry._moonshot_client.is_available()
        lines.append(f"Moonshot: {'✅ online' if available else '❌ offline'}")

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{registry._ollama_base_url}/api/tags")
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                model_str = ", ".join(models[:5]) or "no models"
                lines.append(f"Ollama: ✅ online — {model_str}")
            else:
                lines.append(f"Ollama: ❌ error ({resp.status_code})")
    except Exception as e:
        logger.debug("Ollama health check failed: %s", e)
        lines.append("Ollama: ❌ offline")

    return "Backend status:\n" + "\n".join(lines)


async def exec_manage_memory(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Add, update, or delete a stored memory fact."""
    if registry._knowledge_store is None:
        return "Memory system not available."

    action = inp.get("action", "").strip()
    fact_id = inp.get("fact_id")
    content = (inp.get("content") or "").strip()
    category = (inp.get("category") or "").strip().lower() or None

    if action == "add":
        if not content:
            return "Please provide content for the new fact."
        cat = category or "other"
        new_id = await registry._knowledge_store.add_item(user_id, "fact", content, {"category": cat})
        return f"✅ Fact stored (ID {new_id}): [{cat}] {content}"

    elif action == "update":
        if not fact_id:
            return "Please provide fact_id to update. Call get_facts to find IDs."
        if not content:
            return "Please provide the new content for the fact."
        metadata = {"category": category} if category else None
        updated = await registry._knowledge_store.update(user_id, int(fact_id), content, metadata)
        if not updated:
            return f"No fact with ID {fact_id} found."
        cat_note = f" (category: {category})" if category else ""
        return f"✅ Fact {fact_id} updated{cat_note}: {content}"

    elif action == "delete":
        if not fact_id:
            return "Please provide fact_id to delete. Call get_facts to find IDs."
        deleted = await registry._knowledge_store.delete(user_id, int(fact_id))
        if not deleted:
            return f"No fact with ID {fact_id} found."
        return f"✅ Fact {fact_id} deleted."

    return f"Unknown action '{action}'. Use: add, update, or delete."


async def exec_manage_goal(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Add, update, complete, abandon, or delete a goal."""
    if registry._knowledge_store is None:
        return "Goal store not available."

    action = inp.get("action", "").strip()
    goal_id = inp.get("goal_id")
    title = (inp.get("title") or "").strip() or None
    description = inp.get("description")

    if action == "add":
        if not title:
            return "Please provide a title for the new goal."
        metadata = {"status": "active"}
        if description:
            metadata["description"] = description
        new_id = await registry._knowledge_store.add_item(user_id, "goal", title, metadata)
        return f"✅ Goal added (ID {new_id}): {title}"

    elif action == "update":
        if not goal_id:
            return "Please provide goal_id to update. Call get_goals to find IDs."
        if not title and description is None:
            return "Please provide a new title and/or description."

        items = await registry._knowledge_store.get_by_type(user_id, "goal", limit=100)
        target = next((i for i in items if i.id == int(goal_id)), None)
        if not target:
            return f"No goal with ID {goal_id} found."

        new_meta = target.metadata.copy()
        if description is not None:
            new_meta["description"] = description

        updated = await registry._knowledge_store.update(user_id, int(goal_id), title, new_meta)
        if not updated:
            return f"No goal with ID {goal_id} found."

        parts = []
        if title:
            parts.append(f"title → '{title}'")
        if description is not None:
            parts.append(f"description → '{description}'")
        return f"✅ Goal {goal_id} updated: {', '.join(parts)}"

    elif action == "complete":
        if not goal_id:
            return "Please provide goal_id to mark complete. Call get_goals to find IDs."
        items = await registry._knowledge_store.get_by_type(user_id, "goal", limit=100)
        target = next((i for i in items if i.id == int(goal_id)), None)
        if not target:
            return f"No goal with ID {goal_id} found."

        new_meta = target.metadata.copy()
        new_meta["status"] = "completed"
        await registry._knowledge_store.update(user_id, int(goal_id), metadata=new_meta)
        return f"✅ Goal {goal_id} marked as completed. Nice work! 🎉"

    elif action == "abandon":
        if not goal_id:
            return "Please provide goal_id to abandon. Call get_goals to find IDs."
        items = await registry._knowledge_store.get_by_type(user_id, "goal", limit=100)
        target = next((i for i in items if i.id == int(goal_id)), None)
        if not target:
            return f"No goal with ID {goal_id} found."

        new_meta = target.metadata.copy()
        new_meta["status"] = "abandoned"
        await registry._knowledge_store.update(user_id, int(goal_id), metadata=new_meta)
        return f"✅ Goal {goal_id} marked as abandoned."

    elif action == "delete":
        if not goal_id:
            return "Please provide goal_id to delete. Call get_goals to find IDs."
        deleted = await registry._knowledge_store.delete(user_id, int(goal_id))
        if not deleted:
            return f"No goal with ID {goal_id} found."
        return f"✅ Goal {goal_id} permanently deleted."

    return f"Unknown action '{action}'. Use: add, update, complete, abandon, or delete."


async def exec_get_memory_summary(registry: ToolRegistry, user_id: int) -> str:
    """Return a structured overview of stored memory."""
    if registry._knowledge_store is None:
        return "Memory system not available."

    try:
        summary = await registry._knowledge_store.get_memory_summary(user_id)
    except Exception as e:
        logger.warning("get_memory_summary failed: %s", e)
        return f"Could not retrieve memory summary: {e}"

    total_facts = summary.get("total_facts", 0)
    total_goals = summary.get("total_goals", 0)
    recent = summary.get("recent_facts_7d", 0)
    categories = summary.get("categories", {})
    oldest = summary.get("oldest_fact")
    stale = summary.get("potentially_stale", 0)

    lines = [f"📋 **Memory summary** ({total_facts} facts, {total_goals} goals)"]
    lines.append(f"  Recent (last 7 days): {recent} facts")

    if categories:
        cat_parts = [f"{cat} ({cnt})" for cat, cnt in list(categories.items())[:6]]
        lines.append(f"  Categories: {', '.join(cat_parts)}")

    if oldest:
        content = oldest["content"][:50] + "..." if len(oldest["content"]) > 50 else oldest["content"]
        date_str = oldest["created_at"][:10] if oldest["created_at"] else "unknown"
        lines.append(f"  Oldest fact: \"{content}\" ({date_str})")

    if stale > 0:
        lines.append(f"  ⚠️ Potentially stale (>90 days, not referenced): {stale} facts")

    return "\n".join(lines)
