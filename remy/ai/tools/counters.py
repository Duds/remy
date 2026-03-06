"""Counter tools: get/set/increment/reset named counters (e.g. sobriety streak)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_get_counter(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Return current counter value and unit, or a message if not set."""
    if registry._counter_store is None:
        return "Counters are not available."
    name = (inp.get("name") or "").strip()
    if not name:
        return "Please provide a counter name (e.g. sobriety_streak)."
    row = await registry._counter_store.get(user_id, name)
    if row is None:
        return f"No counter named '{name}' set yet. Use set_counter to create it."
    val = row["value"]
    unit = row.get("unit") or "days"
    updated = row.get("updated_at", "")
    return f"{name}: {val} {unit}" + (f" (updated {updated[:10]})" if updated else "")


async def exec_set_counter(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Set a counter to a value."""
    if registry._counter_store is None:
        return "Counters are not available."
    name = (inp.get("name") or "").strip()
    if not name:
        return "Please provide a counter name (e.g. sobriety_streak)."
    try:
        value = int(inp.get("value", 0))
    except (TypeError, ValueError):
        return "Please provide a non-negative integer value."
    if value < 0:
        return "Counter value must be non-negative."
    unit = (inp.get("unit") or "days").strip() or "days"
    try:
        await registry._counter_store.set(user_id, name, value, unit=unit)
        return f"Set {name} to {value} {unit}."
    except ValueError as e:
        return str(e)


async def exec_increment_counter(
    registry: ToolRegistry, inp: dict, user_id: int
) -> str:
    """Increment a counter by 1 or by a given amount."""
    if registry._counter_store is None:
        return "Counters are not available."
    name = (inp.get("name") or "").strip()
    if not name:
        return "Please provide a counter name (e.g. sobriety_streak)."
    by = 1
    if "by" in inp:
        try:
            by = int(inp["by"])
        except (TypeError, ValueError):
            return "Please provide a positive integer for 'by'."
        if by < 1:
            return "'by' must be at least 1."
    new_value = await registry._counter_store.increment(user_id, name, by=by)
    return f"Incremented {name} by {by}. New value: {new_value}."


async def exec_reset_counter(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Reset a counter to 0."""
    if registry._counter_store is None:
        return "Counters are not available."
    name = (inp.get("name") or "").strip()
    if not name:
        return "Please provide a counter name (e.g. sobriety_streak)."
    await registry._counter_store.reset(user_id, name)
    return f"Reset {name} to 0."
