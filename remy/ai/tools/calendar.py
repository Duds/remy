"""Calendar tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_calendar_events(registry: ToolRegistry, inp: dict) -> str:
    """List upcoming Google Calendar events."""
    if registry._calendar is None:
        return (
            "Google Calendar not configured. "
            "Run scripts/setup_google_auth.py to set it up."
        )
    days = min(int(inp.get("days", 7)), 30)
    try:
        events = await registry._calendar.list_events(days=days)
    except Exception as e:
        return f"Could not fetch calendar events: {e}"

    if not events:
        period = "today" if days == 1 else f"the next {days} days"
        return f"No events scheduled for {period}."

    lines = [f"Calendar events (next {days} day{'s' if days != 1 else ''}):"]
    for e in events:
        lines.append(registry._calendar.format_event(e))
    return "\n".join(lines)


async def exec_create_calendar_event(registry: ToolRegistry, inp: dict) -> str:
    """Create a new event on Google Calendar."""
    if registry._calendar is None:
        return (
            "Google Calendar not configured. "
            "Run scripts/setup_google_auth.py to set it up."
        )
    title = inp.get("title", "").strip()
    date = inp.get("date", "").strip()
    time = inp.get("time", "").strip()
    duration = float(inp.get("duration_hours", 1.0))
    description = inp.get("description", "").strip()

    if not title or not date or not time:
        return "Cannot create event: title, date, and time are all required."

    try:
        event = await registry._calendar.create_event(title, date, time, duration, description)
    except ValueError as e:
        return f"Invalid date/time: {e}"
    except Exception as e:
        return f"Failed to create calendar event: {e}"

    link = event.get("htmlLink", "")
    return (
        f"✅ Calendar event created: {title}\n"
        f"Date: {date} at {time} ({duration}h)\n"
        f"Link: {link}"
    )
