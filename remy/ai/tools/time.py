"""Time-related tool executors."""

from __future__ import annotations

import zoneinfo
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry


def exec_get_current_time(registry: ToolRegistry) -> str:
    """Return the current date and time in Australia/Canberra timezone."""
    tz = zoneinfo.ZoneInfo("Australia/Canberra")
    now = datetime.now(tz)
    return (
        f"Current date/time in Australia/Canberra:\n"
        f"  Date: {now.strftime('%A, %d %B %Y')}\n"
        f"  Time: {now.strftime('%I:%M %p')} ({now.strftime('%H:%M')} 24h)\n"
        f"  ISO:  {now.isoformat()}"
    )
