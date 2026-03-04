"""
Afternoon focus generator.

Produces the mid-day ADHD body-double check-in with top priority goal
and remaining calendar events. Supports mediated delivery (US-remy-mediated-reminders).
"""

import logging
from typing import Any

from .base import BriefingGenerator

logger = logging.getLogger(__name__)


class AfternoonFocusGenerator(BriefingGenerator):
    """
    Generates the afternoon focus check-in content.

    Includes:
    - Top priority active goal
    - Remaining calendar events for today
    - Encouragement message
    """

    async def _get_context_data(self) -> tuple[str | None, list[str]]:
        """Return (top_goal_title or None, list of remaining calendar event strings)."""
        goals = await self._get_active_goals(limit=5)
        top_goal = goals[0]["title"] if goals else None
        calendar_lines: list[str] = []
        if self._calendar is not None:
            try:
                events = await self._calendar.list_events(days=1)
                if events:
                    calendar_lines = [
                        self._calendar.format_event(e) for e in events[:3]
                    ]
            except Exception as e:
                logger.debug("Could not load calendar for afternoon focus: %s", e)
        return top_goal, calendar_lines

    async def generate_structured(self) -> dict[str, Any]:
        """Return structured context for mediated delivery (compose_proactive_message)."""
        top_goal, calendar_lines = await self._get_context_data()
        return {
            "afternoon_checkin": True,
            "top_goal": top_goal,
            "remaining_calendar": calendar_lines,
        }

    async def generate(self) -> str:
        """Generate the afternoon focus check-in content."""
        sections: list[str] = ["🎯 *Afternoon focus check-in*"]

        goal_section = await self._build_goal_section()
        sections.append(goal_section)

        calendar_section = await self._build_remaining_calendar_section()
        if calendar_section:
            sections.append(calendar_section)

        sections.append("_3 focused hours before end of day — you've got this._")

        return "\n\n".join(sections)

    async def _build_goal_section(self) -> str:
        """Build the top priority goal section."""
        goals = await self._get_active_goals(limit=5)
        if not goals:
            return (
                "You haven't set any goals yet — tell me what you're working on "
                "and I'll help you stay focused."
            )

        top_goal = goals[0]["title"]
        return f"Your top priority right now: *{top_goal}*\nHow's it going?"

    async def _build_remaining_calendar_section(self) -> str:
        """Build remaining calendar events section."""
        if self._calendar is None:
            return ""
        try:
            events = await self._calendar.list_events(days=1)
            if not events:
                return ""

            remaining = events[:3]
            if not remaining:
                return ""

            lines = [self._calendar.format_event(e) for e in remaining]
            return "📅 *Still on today's schedule:*\n" + "\n".join(lines)
        except Exception as e:
            logger.debug("Could not load calendar for afternoon focus: %s", e)
            return ""
