"""Automation and reminder tool executors."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)

_DOW_MAP = {
    "mon": "1", "tue": "2", "wed": "3", "thu": "4",
    "fri": "5", "sat": "6", "sun": "0",
}
_DOW_NAMES = {
    "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
    "4": "Thursday", "5": "Friday", "6": "Saturday", "*": "every day",
}


async def exec_schedule_reminder(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Create a recurring reminder that fires daily or weekly."""
    if registry._automation_store is None:
        return "Automation store not available."

    label = inp.get("label", "").strip()
    frequency = inp.get("frequency", "daily")
    time_str = inp.get("time", "09:00").strip()
    day = inp.get("day", "mon").strip().lower()

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
        automation_id = await registry._automation_store.add(user_id, label, cron)
    except Exception as e:
        return f"Failed to save reminder: {e}"

    sched = registry._scheduler_ref.get("proactive_scheduler")
    if sched is not None:
        sched.add_automation(automation_id, user_id, label, cron)

    return (
        f"✅ Reminder set (ID {automation_id}): '{label}'\n"
        f"Fires {freq_desc}."
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
        if row.get("fire_at"):
            lines.append(
                f"[ID {row['id']}] '{row['label']}' — once at {row['fire_at']}"
            )
        else:
            cron_parts = row["cron"].split()
            minute, hour, _, _, dow = cron_parts
            time_fmt = f"{int(hour):02d}:{int(minute):02d}"
            freq = "daily" if dow == "*" else f"every {_DOW_NAMES.get(dow, dow)}"
            lines.append(
                f"[ID {row['id']}] '{row['label']}' — {freq} at {time_fmt} | last run: {last}"
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


async def exec_set_one_time_reminder(registry: ToolRegistry, inp: dict, user_id: int) -> str:
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

    if fire_dt.tzinfo is None:
        fire_dt_utc = fire_dt.replace(tzinfo=timezone.utc).replace(
            hour=(fire_dt.hour - 10) % 24
        )
    else:
        fire_dt_utc = fire_dt.astimezone(timezone.utc)

    if fire_dt_utc <= datetime.now(timezone.utc):
        return "That time is already in the past. Please provide a future datetime."

    try:
        automation_id = await registry._automation_store.add(
            user_id, label, cron="", fire_at=fire_at_str
        )
    except Exception as e:
        return f"Failed to save reminder: {e}"

    sched = registry._scheduler_ref.get("proactive_scheduler")
    if sched is not None:
        sched.add_automation(automation_id, user_id, label, cron="", fire_at=fire_at_str)

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


async def exec_grocery_list(registry: ToolRegistry, inp: dict, user_id: int = 0) -> str:
    """Manage the shopping/grocery list via unified KnowledgeStore (or file fallback)."""
    action = inp.get("action", "show")
    items_raw = inp.get("items", "").strip()

    if registry._knowledge_store is not None and user_id:
        if action == "show":
            items = await registry._knowledge_store.get_by_type(user_id, "shopping_item", limit=100)
            if not items:
                return "Shopping list is empty."
            lines = [f"• [ID:{i.id}] {i.content}" for i in items]
            return "Shopping list:\n" + "\n".join(lines) + "\n\n(Use the ID to remove specific items)"

        elif action == "add":
            if not items_raw:
                return "Please specify what to add."
            new_items = [s.strip() for s in items_raw.replace(";", ",").split(",") if s.strip()]
            from ...models import KnowledgeItem
            ki_list = [KnowledgeItem(entity_type="shopping_item", content=it) for it in new_items]
            await registry._knowledge_store.upsert(user_id, ki_list)
            return f"✅ Added to shopping list: {', '.join(new_items)}"

        elif action == "remove":
            if not items_raw:
                return "Please specify what to remove (name substring or item ID)."
            if items_raw.isdigit():
                removed = await registry._knowledge_store.delete(user_id, int(items_raw))
                return f"✅ Removed item {items_raw}." if removed else f"Item {items_raw} not found."
            all_items = await registry._knowledge_store.get_by_type(user_id, "shopping_item", limit=100)
            removed_count = 0
            for item in all_items:
                if items_raw.lower() in item.content.lower():
                    await registry._knowledge_store.delete(user_id, item.id)
                    removed_count += 1
            return f"✅ Removed {removed_count} item(s) matching '{items_raw}'."

        elif action == "clear":
            all_items = await registry._knowledge_store.get_by_type(user_id, "shopping_item", limit=500)
            for item in all_items:
                await registry._knowledge_store.delete(user_id, item.id)
            return "✅ Shopping list cleared."

        return f"Unknown action: {action}"

    grocery_file = registry._grocery_list_file
    if not grocery_file:
        return "Grocery list not configured."

    def _read():
        try:
            with open(grocery_file, encoding="utf-8") as f:
                return [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            return []

    def _write(items: list[str]):
        os.makedirs(os.path.dirname(grocery_file) or ".", exist_ok=True)
        with open(grocery_file, "w", encoding="utf-8") as f:
            f.write("\n".join(items) + ("\n" if items else ""))

    if action == "show":
        items = await asyncio.to_thread(_read)
        if not items:
            return "Grocery list is empty."
        return "Grocery list:\n" + "\n".join(f"• {i}" for i in items)

    elif action == "add":
        if not items_raw:
            return "Please specify what to add."
        new_items = [i.strip() for i in items_raw.replace(";", ",").split(",") if i.strip()]
        items = await asyncio.to_thread(_read)
        items.extend(new_items)
        await asyncio.to_thread(_write, items)
        return f"✅ Added to grocery list: {', '.join(new_items)}"

    elif action == "remove":
        if not items_raw:
            return "Please specify what to remove."
        items = await asyncio.to_thread(_read)
        lower_target = items_raw.lower()
        before = len(items)
        items = [i for i in items if lower_target not in i.lower()]
        await asyncio.to_thread(_write, items)
        removed = before - len(items)
        return f"✅ Removed {removed} item(s) matching '{items_raw}'."

    elif action == "clear":
        await asyncio.to_thread(_write, [])
        return "✅ Grocery list cleared."

    return f"Unknown action: {action}"
