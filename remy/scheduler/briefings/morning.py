"""
Morning briefing generator.

Produces the daily morning summary including goals, calendar, birthdays,
downloads cleanup suggestions, and stale plan steps.

Supports two modes:
- generate(): template-based string (fallback)
- generate_structured(): compact dict for Claude composition (US-conversational-briefing-via-remy)
"""

import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...config import settings
from ...google.gmail import PRIMARY_TABS_LABEL_IDS
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

        relay_section = await self._build_relay_section()
        if relay_section:
            sections.append(relay_section)

        return "\n\n".join(sections)

    async def generate_structured(self) -> dict[str, Any]:
        """Generate a compact structured payload for Claude composition.

        US-conversational-briefing-via-remy: token-efficient dict for
        run_proactive_trigger context. Dates in ISO for parsing; locale hints for output.
        """
        tz_name = getattr(settings, "scheduler_timezone", "Australia/Sydney")
        tz: ZoneInfo | timezone = timezone.utc
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            pass
        today = datetime.now(tz).date()
        date_str = today.strftime("%Y-%m-%d")

        payload: dict[str, Any] = {"date": date_str, "locale": "Australia"}

        goals = await self._get_active_goals(limit=10)
        payload["goals"] = [
            {"title": g.get("title", ""), "desc": g.get("description")} for g in goals
        ]

        if self._calendar:
            try:
                events = await self._calendar.list_events(days=1)
                cal_items: list[dict[str, Any]] = []
                for e in events[:10]:
                    title = e.get("summary", "(no title)")
                    start = e.get("start", {})
                    url = e.get("htmlLink", "")
                    when_iso: str | None = None
                    if start.get("dateTime"):
                        try:
                            dt = datetime.fromisoformat(start["dateTime"])
                            when_iso = dt.strftime("%Y-%m-%dT%H:%M:00")
                            cal_items.append(
                                {
                                    "time": dt.strftime("%H:%M"),
                                    "title": title,
                                    "url": url or "",
                                    "when": when_iso,
                                }
                            )
                        except Exception:
                            cal_items.append(
                                {"time": "?", "title": title, "url": url or ""}
                            )
                    else:
                        date_val = start.get("date", "")
                        try:
                            if date_val:
                                d = date.fromisoformat(date_val)
                                when_iso = f"{date_val}T09:00:00"
                                cal_items.append(
                                    {
                                        "date": d.strftime("%d %b"),
                                        "title": title,
                                        "url": url or "",
                                        "when": when_iso,
                                    }
                                )
                            else:
                                cal_items.append(
                                    {"date": "?", "title": title, "url": url or ""}
                                )
                        except ValueError:
                            cal_items.append(
                                {"date": date_val, "title": title, "url": url or ""}
                            )
                payload["calendar"] = cal_items
            except Exception as e:
                logger.debug("Could not load calendar for structured briefing: %s", e)
                payload["calendar"] = []
        else:
            payload["calendar"] = []

        # US-proactive-buttons-decisions-only: events to add (not yet on calendar).
        # Pipeline attaches [Add to calendar] only for suggested_events. Leave empty
        # until we have a source (e.g. calendar-invite emails, meeting requests).
        payload["suggested_events"] = []

        if self._fact_store:
            try:
                project_facts = await self._fact_store.get_by_category(
                    self._user_id, "project"
                )
                payload["projects"] = [
                    pf.get("content", "")[:80]
                    for pf in project_facts[:5]
                    if pf.get("content")
                ]
            except Exception as e:
                logger.debug("Could not load projects for structured briefing: %s", e)
                payload["projects"] = []
        else:
            payload["projects"] = []

        downloads = Path.home() / "Downloads"
        if downloads.exists():
            old_files = [
                f.name
                for f in downloads.iterdir()
                if f.is_file() and f.stat().st_mtime < time.time() - 7 * 86400
            ]
            payload["downloads"] = old_files[:10]
        else:
            payload["downloads"] = []

        if self._contacts:
            try:
                from ...google.contacts import _extract_name

                upcoming = await self._contacts.get_upcoming_birthdays(days=7)
                payload["birthdays"] = [
                    {"name": _extract_name(p) or "Someone", "date": d.strftime("%d %b")}
                    for d, p in upcoming[:5]
                ]
            except Exception as e:
                logger.debug("Could not load birthdays for structured briefing: %s", e)
                payload["birthdays"] = []
        else:
            payload["birthdays"] = []

        if self._plan_store:
            try:
                stale = await self._plan_store.stale_steps(self._user_id, days=7)
                stale_items: list[dict[str, Any]] = []
                for step in stale[:5]:
                    days_stale = 7
                    try:
                        updated = datetime.fromisoformat(
                            step["step_updated_at"]
                        ).replace(tzinfo=timezone.utc)
                        days_stale = (datetime.now(timezone.utc) - updated).days
                    except (ValueError, KeyError):
                        pass
                    stale_items.append(
                        {
                            "plan": step.get("plan_title", "?"),
                            "step": step.get("step_title", "?"),
                            "days": days_stale,
                        }
                    )
                payload["stale_plans"] = stale_items
            except Exception as e:
                logger.debug(
                    "Could not load stale plans for structured briefing: %s", e
                )
                payload["stale_plans"] = []
        else:
            payload["stale_plans"] = []

        # Unread email (US-gmail-check-all-mail): scope from settings
        scope = getattr(settings, "briefing_email_scope", "inbox_only") or "inbox_only"
        if self._gmail:
            try:
                if scope == "all_mail":
                    label_ids: list[str | None] | None = cast(list[str | None], [None])
                    scope_desc = "all mail"
                elif scope == "primary_tabs":
                    label_ids = cast(list[str | None], PRIMARY_TABS_LABEL_IDS)
                    scope_desc = "Inbox, Promotions, and Updates"
                else:
                    label_ids = None
                    scope_desc = "Inbox"
                data = await self._gmail.get_unread_summary(label_ids=label_ids)
                payload["unread_email"] = {
                    "count": data.get("count", 0),
                    "senders": data.get("senders", [])[:5],
                    "scope": scope_desc,
                }
            except Exception as e:
                logger.debug("Could not load unread email for briefing: %s", e)
                payload["unread_email"] = {"count": 0, "senders": [], "scope": ""}
        else:
            payload["unread_email"] = {"count": 0, "senders": [], "scope": ""}

        # Relay inbox (US-claude-desktop-relay, US-relay-shared-backend)
        try:
            from ...relay.client import get_messages_for_remy, get_tasks_for_remy

            _, unread = await get_messages_for_remy(
                agent="remy",
                unread_only=True,
                mark_read=False,
                limit=1,
                db_path=settings.relay_db_path_resolved,
            )
            _, pending = await get_tasks_for_remy(
                agent="remy",
                status="pending",
                limit=1,
                db_path=settings.relay_db_path_resolved,
            )
            payload["relay_unread"] = unread
            payload["relay_pending"] = pending
        except Exception:
            payload["relay_unread"] = 0
            payload["relay_pending"] = 0

        return payload

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
        return (
            f"Here's what you're working on:\n{goals_text}\n\nMake it count today. 💪"
        )

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
            project_facts = await self._fact_store.get_by_category(
                self._user_id, "project"
            )
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
            f.name
            for f in downloads.iterdir()
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
                updated = datetime.fromisoformat(step["step_updated_at"]).replace(
                    tzinfo=timezone.utc
                )
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

    async def _build_relay_section(self) -> str:
        """One-liner if there are unread relay messages or pending tasks from cowork (US-relay-shared-backend)."""
        try:
            from ...config import settings
            from ...relay.client import get_messages_for_remy, get_tasks_for_remy

            messages, unread = await get_messages_for_remy(
                agent="remy",
                unread_only=True,
                mark_read=False,
                limit=5,
                db_path=settings.relay_db_path_resolved,
            )
            tasks, pending = await get_tasks_for_remy(
                agent="remy",
                status="pending",
                limit=5,
                db_path=settings.relay_db_path_resolved,
            )
        except Exception:
            return ""
        lines = []
        if unread > 0:
            lines.append(f"📬 {unread} unread message(s) from cowork.")
        if pending > 0:
            lines.append(f"📋 {pending} pending task(s) from cowork.")
        return "\n".join(lines) if lines else ""
