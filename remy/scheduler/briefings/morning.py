"""
Morning briefing generator.

Produces the daily morning summary including goals, calendar, birthdays,
downloads cleanup suggestions, and stale plan steps.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BriefingGenerator

logger = logging.getLogger(__name__)


class MorningBriefingGenerator(BriefingGenerator):
    """
    Generates the morning briefing content.

    Includes:
    - Active goals
    - Today's calendar events
    - Tracked projects
    - Upcoming birthdays
    - Downloads cleanup suggestions
    - Stale plan steps needing attention
    """

    async def generate(self) -> str:
        """Generate the morning briefing content."""
        sections: list[str] = []

        date_header = self._format_date_header()
        sections.append(f"☀️ *Good morning, Dale!* — {date_header}")

        goals_section = await self._build_goals_section()
        sections.append(goals_section)

        calendar_section = await self._build_calendar_section()
        if calendar_section:
            sections.append(calendar_section)

        projects_section = await self._build_projects_section()
        if projects_section:
            sections.append(projects_section)

        birthdays_section = await self._build_birthdays_section()
        if birthdays_section:
            sections.append(birthdays_section)

        downloads_section = await self._build_downloads_section()
        if downloads_section:
            sections.append("\n" + downloads_section)

        stale_plans_section = await self._build_stale_plans_section()
        if stale_plans_section:
            sections.append(stale_plans_section)

        return "\n\n".join(sections)

    async def _build_goals_section(self) -> str:
        """Build the active goals section."""
        goals = await self._get_active_goals(limit=10)
        if not goals:
            return (
                "You have no active goals tracked yet. "
                "Tell me what you're working on and I'll help you stay on track."
            )

        goal_lines: list[str] = []
        for g in goals:
            line = f"• *{g['title']}*"
            if g.get("description"):
                line += f" — {g['description']}"
            goal_lines.append(line)

        goals_text = "\n".join(goal_lines)
        return f"Here's what you're working on:\n{goals_text}\n\nMake it count today. 💪"

    async def _build_calendar_section(self) -> str:
        """Build today's calendar events section."""
        if self._calendar is None:
            return ""
        try:
            events = await self._calendar.list_events(days=1)
            if not events:
                return "📅 *Today's calendar:* Nothing scheduled."

            event_lines = [self._calendar.format_event(e) for e in events[:5]]
            suffix = f"\n_({len(events) - 5} more)_" if len(events) > 5 else ""
            return "📅 *Today's calendar:*\n" + "\n".join(event_lines) + suffix
        except Exception as e:
            logger.debug("Could not load calendar for briefing: %s", e)
            return ""

    async def _build_projects_section(self) -> str:
        """Build tracked projects section from facts."""
        if self._fact_store is None:
            return ""
        try:
            project_facts = await self._fact_store.get_by_category(self._user_id, "project")
            if not project_facts:
                return ""

            project_lines = [f"• `{pf['content']}`" for pf in project_facts[:3]]
            return "📁 *Tracked projects:*\n" + "\n".join(project_lines)
        except Exception as e:
            logger.debug("Could not load project facts for briefing: %s", e)
            return ""

    async def _build_birthdays_section(self) -> str:
        """Build upcoming birthdays section."""
        if self._contacts is None:
            return ""
        try:
            from ...google.contacts import _extract_name
            upcoming = await self._contacts.get_upcoming_birthdays(days=7)
            if not upcoming:
                return ""

            bday_lines: list[str] = []
            for bday_date, person in upcoming[:5]:
                name = _extract_name(person) or "Someone"
                bday_lines.append(f"• 🎂 *{name}* — {bday_date.strftime('%d %b')}")
            return "*Upcoming birthdays:*\n" + "\n".join(bday_lines)
        except Exception as e:
            logger.debug("Could not load birthdays for briefing: %s", e)
            return ""

    async def _build_downloads_section(self) -> str:
        """Build downloads cleanup suggestion section."""
        downloads = Path.home() / "Downloads"
        if not downloads.exists():
            return ""

        old_files = [
            f.name for f in downloads.iterdir()
            if f.is_file() and f.stat().st_mtime < time.time() - 7 * 86400
        ]
        if not old_files:
            return ""

        lines = "\n".join(old_files[:10])
        if len(old_files) > 10:
            lines += f"\n…and {len(old_files) - 10} more files"
        return f"🧹 *Downloads cleanup suggestion*\nThese files are older than a week:\n{lines}"

    async def _build_stale_plans_section(self) -> str:
        """Build stale plan steps section."""
        if self._plan_store is None:
            return ""
        try:
            stale = await self._plan_store.stale_steps(self._user_id, days=7)
        except Exception as e:
            logger.debug("Could not load stale plan steps: %s", e)
            return ""

        if not stale:
            return ""

        lines = ["📋 *Plans needing attention:*"]
        for step in stale[:5]:
            days_stale = 7
            try:
                updated = datetime.fromisoformat(step["step_updated_at"]).replace(tzinfo=timezone.utc)
                days_stale = (datetime.now(timezone.utc) - updated).days
            except (ValueError, KeyError):
                pass

            line = f"• *{step['plan_title']}* — Step {step.get('step_title', '?')}"
            if step.get("last_attempt_outcome"):
                line += f" (last attempt: {step['last_attempt_outcome']})"
            line += f" — {days_stale} days since activity"
            lines.append(line)

        if len(stale) > 5:
            lines.append(f"_…and {len(stale) - 5} more steps_")

        return "\n".join(lines)
