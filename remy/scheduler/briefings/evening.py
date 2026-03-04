"""
Evening check-in generator.

Produces the evening nudge about goals that haven't been mentioned recently.
Supports both template output (generate) and structured context for mediated
delivery via compose_proactive_message (US-remy-mediated-reminders).
"""

import logging
from typing import TYPE_CHECKING, Any

from .base import BriefingGenerator

if TYPE_CHECKING:
    from ...memory.conversations import ConversationStore

logger = logging.getLogger(__name__)


class EveningCheckinGenerator(BriefingGenerator):
    """
    Generates the evening check-in content.

    Includes:
    - Goals not updated within the stale threshold (default 3 days)

    Returns empty string if no stale goals, indicating no message should be sent.
    """

    def __init__(
        self,
        *args,
        stale_days: int = 3,
        conv_store: "ConversationStore | None" = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._stale_days = stale_days
        self._conv_store = conv_store

    async def _get_to_surface_and_calendar(
        self,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Return (goals to surface in check-in, calendar summary string).
        If nothing to surface, returns ([], "").
        """
        stale_goals = await self._get_stale_goals(days=self._stale_days)
        if not stale_goals:
            return [], ""

        if self._conv_store is not None:
            mentioned_today = await self._conv_store.get_goal_titles_mentioned_today(
                self._user_id, [g["title"] for g in stale_goals]
            )
            to_surface = [g for g in stale_goals if g["title"] not in mentioned_today]
        else:
            to_surface = stale_goals

        if not to_surface:
            return [], ""

        calendar_summary = ""
        if self._calendar is not None:
            try:
                events = await self._calendar.list_events(days=1)
                if events:
                    event_lines = [self._calendar.format_event(e) for e in events[:5]]
                    calendar_summary = "Today's events: " + ", ".join(event_lines)
                else:
                    calendar_summary = "Nothing scheduled."
            except Exception as e:
                logger.debug("Could not load calendar for evening check-in: %s", e)

        return to_surface, calendar_summary

    async def generate_structured(self) -> dict[str, Any] | None:
        """
        Return structured context for mediated delivery (compose_proactive_message).
        Returns None when there is nothing to surface (no message should be sent).
        """
        to_surface, calendar_summary = await self._get_to_surface_and_calendar()
        if not to_surface:
            return None
        return {
            "evening_checkin": True,
            "stale_goals": [
                {"id": g.get("id"), "title": g.get("title", "")} for g in to_surface
            ],
            "calendar_summary": calendar_summary or None,
        }

    async def generate(self) -> str:
        """Generate the evening check-in content. Returns empty if no stale goals."""
        to_surface, calendar_summary = await self._get_to_surface_and_calendar()
        if not to_surface:
            return ""

        stale_lines = [f"• *{g['title']}*" for g in to_surface]
        goals_text = "\n".join(stale_lines)

        msg = (
            f"🌙 *Evening check-in*\n\n"
            f"You haven't mentioned these goals in a while:\n{goals_text}\n\n"
            f"Still working on them? Let me know how it's going."
        )

        if calendar_summary:
            msg += f"\n\n _Context: {calendar_summary}_"

        return msg
