"""Automation and reminder tool executors."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)

_DOW_MAP = {
    "mon": "1",
    "tue": "2",
    "wed": "3",
    "thu": "4",
    "fri": "5",
    "sat": "6",
    "sun": "0",
}
_DOW_NAMES = {
    "0": "Sunday",
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
    "*": "every day",
}


async def exec_schedule_reminder(
    registry: ToolRegistry, inp: dict, user_id: int
) -> str:
    """Create a recurring reminder that fires daily or weekly."""
    if registry._automation_store is None:
        return "Automation store not available."

    label = inp.get("label", "").strip()
    frequency = inp.get("frequency", "daily")
    time_str = inp.get("time", "09:00").strip()
    day = inp.get("day", "mon").strip().lower()
    mediated = inp.get("mediated", False) is True

    if not label:
        return "Please provide a label for the reminder."

    parts = time_str.split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        hour = int(parts[0])
        minute = int(parts[1])
    else:
        hour, minute = 9, 0

    if frequency == "weekly":
        dow = _DOW_MAP.get(day, "1")
        cron = f"{minute} {hour} * * {dow}"
        day_name = _DOW_NAMES.get(dow, day.capitalize())
        freq_desc = f"every {day_name} at {hour:02d}:{minute:02d}"
    else:
        cron = f"{minute} {hour} * * *"
        freq_desc = f"every day at {hour:02d}:{minute:02d}"

    try:
        automation_id = await registry._automation_store.add(
            user_id, label, cron, mediated=mediated
        )
    except Exception as e:
        return f"Failed to save reminder: {e}"

    sched = registry._scheduler_ref.get("proactive_scheduler")
    if sched is not None:
        sched.add_automation(automation_id, user_id, label, cron, mediated=mediated)

    delivery = (
        "mediated (Remy composes at fire time)" if mediated else "direct (static text)"
    )
    return (
        f"✅ Reminder set (ID {automation_id}): '{label}'\n"
        f"Fires {freq_desc}. Delivery: {delivery}."
    )


async def exec_list_reminders(registry: ToolRegistry, user_id: int) -> str:
    """Show all scheduled reminders with their IDs and next fire times."""
    if registry._automation_store is None:
        return "Automation store not available."

    rows = await registry._automation_store.get_all(user_id)
    if not rows:
        return "No reminders scheduled. Use schedule_reminder to create one."

    lines = [f"Scheduled reminders ({len(rows)}):"]
    for row in rows:
        last = row["last_run_at"] or "never"
        mediated = bool(row.get("mediated", 0))
        delivery = "mediated" if mediated else "direct"
        if row.get("fire_at"):
            try:
                fire_dt = datetime.fromisoformat(row["fire_at"])
                display = fire_dt.strftime("%a %d %b %Y at %H:%M")
            except (ValueError, TypeError):
                display = row["fire_at"]
            lines.append(
                f"[ID {row['id']}] '{row['label']}' — once at {display} ({delivery})"
            )
        else:
            cron_parts = row["cron"].split()
            minute, hour, _, _, dow = cron_parts
            time_fmt = f"{int(hour):02d}:{int(minute):02d}"
            freq = "daily" if dow == "*" else f"every {_DOW_NAMES.get(dow, dow)}"
            lines.append(
                f"[ID {row['id']}] '{row['label']}' — {freq} at {time_fmt} | last run: {last} ({delivery})"
            )

    return "\n".join(lines)


async def exec_remove_reminder(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Remove a scheduled reminder by its ID."""
    if registry._automation_store is None:
        return "Automation store not available."

    reminder_id = int(inp.get("id", 0))
    if not reminder_id:
        return "Please provide a reminder ID. Use list_reminders to find it."

    removed = await registry._automation_store.remove(user_id, reminder_id)
    if not removed:
        return f"No reminder with ID {reminder_id} found (or it doesn't belong to you)."

    sched = registry._scheduler_ref.get("proactive_scheduler")
    if sched is not None:
        sched.remove_automation(reminder_id)

    return f"✅ Reminder {reminder_id} removed."


async def exec_set_one_time_reminder(
    registry: ToolRegistry, inp: dict, user_id: int
) -> str:
    """Set a one-time reminder that fires at a specific date and time."""
    if registry._automation_store is None:
        return "Automation store not available."

    label = inp.get("label", "").strip()
    fire_at_str = inp.get("fire_at", "").strip()

    if not label:
        return "Please provide a label for the reminder."
    if not fire_at_str:
        return "Please provide a fire_at datetime."

    try:
        fire_dt = datetime.fromisoformat(fire_at_str)
    except ValueError:
        return (
            f"Invalid fire_at format: {fire_at_str!r}. "
            "Use ISO 8601, e.g. '2026-02-27T15:30:00'."
        )

    # Treat naive datetimes as local (AEST/AEDT). Using zoneinfo handles
    # DST correctly — ZoneInfo("Australia/Canberra") is UTC+10 in winter
    # and UTC+11 in summer, unlike a hardcoded offset.
    _local_tz = ZoneInfo("Australia/Canberra")
    if fire_dt.tzinfo is None:
        fire_dt_aware = fire_dt.replace(tzinfo=_local_tz)
    else:
        fire_dt_aware = fire_dt.astimezone(timezone.utc)

    if fire_dt_aware <= datetime.now(timezone.utc):
        return "That time is already in the past. Please provide a future datetime."

    try:
        automation_id = await registry._automation_store.add(
            user_id, label, cron="", fire_at=fire_at_str
        )
    except Exception as e:
        return f"Failed to save reminder: {e}"

    sched = registry._scheduler_ref.get("proactive_scheduler")
    if sched is not None:
        sched.add_automation(
            automation_id, user_id, label, cron="", fire_at=fire_at_str
        )

    try:
        display_time = fire_dt.strftime("%a %d %b at %H:%M")
    except Exception as e:
        logger.debug("Failed to format display time: %s", e)
        display_time = fire_at_str

    return (
        f"✅ One-time reminder set (ID {automation_id}): '{label}'\n"
        f"Fires {display_time}."
    )


async def exec_breakdown_task(registry: ToolRegistry, inp: dict) -> str:
    """Break a task or project into 5 clear, actionable steps."""
    task = inp.get("task", "").strip()
    if not task:
        return "Please specify a task to break down."

    if registry._claude_client is None:
        return "Claude client not available for task breakdown."

    system = (
        "You are an ADHD-friendly task coach. When given a task, break it down into "
        "exactly 5 clear, concrete, actionable steps. Each step should be completable "
        "in under 30 minutes. Number them 1–5. Be specific and encouraging. "
        "After the steps, add one brief motivational sentence."
    )
    try:
        response = await registry._claude_client.complete(
            messages=[{"role": "user", "content": f"Break down this task: {task}"}],
            system=system,
            max_tokens=600,
        )
    except Exception as e:
        return f"Could not break down task: {e}"

    return response if isinstance(response, str) else str(response)


async def grocery_list_impl(
    store: Any,
    user_id: int,
    action: str,
    items_raw: str,
) -> str:
    """
    Single implementation for grocery/shopping list (KnowledgeStore).

    Used by both the grocery_list tool and the /grocery-list command.
    store must have get_by_type(user_id, entity_type, limit), upsert(user_id, items), delete(user_id, item_id).
    """
    from ...models import KnowledgeItem

    action = (action or "show").strip().lower()
    items_raw = (items_raw or "").strip()

    if action == "show":
        items = await store.get_by_type(user_id, "shopping_item", limit=100)
        if not items:
            return "Shopping list is empty."
        lines = [f"• [ID:{i.id}] {i.content}" for i in items]
        return (
            "Shopping list:\n"
            + "\n".join(lines)
            + "\n\n(Use the ID to remove specific items)"
        )

    if action == "add":
        if not items_raw:
            return "Please specify what to add."
        new_items = [
            s.strip() for s in items_raw.replace(";", ",").split(",") if s.strip()
        ]
        ki_list = [
            KnowledgeItem(entity_type="shopping_item", content=it) for it in new_items
        ]
        await store.upsert(user_id, ki_list)
        return f"✅ Added to shopping list: {', '.join(new_items)}"

    if action == "remove":
        if not items_raw:
            return "Please specify what to remove (name substring or item ID)."
        if items_raw.isdigit():
            removed = await store.delete(user_id, int(items_raw))
            return (
                f"✅ Removed item {items_raw}."
                if removed
                else f"Item {items_raw} not found."
            )
        all_items = await store.get_by_type(user_id, "shopping_item", limit=100)
        removed_count = 0
        for item in all_items:
            if items_raw.lower() in item.content.lower():
                await store.delete(user_id, item.id)
                removed_count += 1
        return f"✅ Removed {removed_count} item(s) matching '{items_raw}'."

    if action == "clear":
        all_items = await store.get_by_type(user_id, "shopping_item", limit=500)
        for item in all_items:
            await store.delete(user_id, item.id)
        return "✅ Shopping list cleared."

    return f"Unknown action: {action}"


async def exec_grocery_list(registry: ToolRegistry, inp: dict, user_id: int = 0) -> str:
    """Manage the shopping/grocery list via KnowledgeStore. Delegates to grocery_list_impl."""
    if registry._knowledge_store is None or not user_id:
        return (
            "Grocery list requires memory (KnowledgeStore) to be configured. "
            "Use the /grocery-list command or ensure memory is enabled."
        )
    action = inp.get("action", "show")
    items_raw = (inp.get("items") or "").strip()
    return await grocery_list_impl(
        registry._knowledge_store, user_id, action, items_raw
    )
