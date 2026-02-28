"""
Proactive scheduler — sends unsolicited messages to Dale based on time and context.

Three built-in jobs:
  1. Morning briefing   (default 07:00 AEST) — goals, calendar, birthdays, downloads
  2. Afternoon focus    (default 14:00 AEST) — mid-day ADHD body-double nudge
  3. Evening check-in   (default 19:00 AEST) — nudges on goals not mentioned for N days

Plus user-defined automation jobs stored in the automations table.

Uses APScheduler AsyncIOScheduler so it runs inside the existing asyncio event loop
without spawning threads.

Primary chat ID is read from `data/primary_chat_id.txt` (written by /setmychat).
If that file doesn't exist, the scheduler runs silently.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from ..config import settings
from ..memory.facts import FactStore
from ..memory.goals import GoalStore

if TYPE_CHECKING:
    from telegram import Bot
    from ..memory.automations import AutomationStore
    from ..ai.claude_client import ClaudeClient
    from ..ai.tool_registry import ToolRegistry
    from ..bot.session import SessionManager
    from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)

# Goals not updated within this many days trigger an evening nudge
_STALE_GOAL_DAYS = 3

# Default cron for the afternoon focus check-in (configurable via .env)
_AFTERNOON_CRON_DEFAULT = "0 14 * * *"


def _read_primary_chat_id() -> int | None:
    """Read the primary chat ID saved by /setmychat. Returns None if not set."""
    try:
        with open(settings.primary_chat_file) as f:
            raw = f.read().strip()
            return int(raw) if raw else None
    except (FileNotFoundError, ValueError):
        return None


def _parse_cron(cron_str: str) -> CronTrigger:
    """Parse a 5-field cron string into an APScheduler CronTrigger."""
    parts = cron_str.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron string (expected 5 fields): {cron_str!r}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=settings.scheduler_timezone,
    )


class ProactiveScheduler:
    """
    Wraps APScheduler and schedules the morning briefing, afternoon focus,
    evening check-in, and any user-defined automation jobs.

    Usage:
        scheduler = ProactiveScheduler(bot, goal_store, automation_store=store)
        scheduler.start()
        await scheduler.load_user_automations()
        # ... bot runs ...
        scheduler.stop()
    """

    def __init__(
        self,
        bot: "Bot",
        goal_store: GoalStore,
        fact_store: FactStore | None = None,
        calendar_client=None,   # remy.google.calendar.CalendarClient | None
        contacts_client=None,   # remy.google.contacts.ContactsClient | None
        automation_store: "AutomationStore | None" = None,
        claude_client: "ClaudeClient | None" = None,
        conversation_analyzer=None,     # remy.analytics.analyzer.ConversationAnalyzer | None
        session_manager: "SessionManager | None" = None,
        conv_store: "ConversationStore | None" = None,
        tool_registry: "ToolRegistry | None" = None,
        db=None,
    ) -> None:
        self._bot = bot
        self._goal_store = goal_store
        self._fact_store = fact_store
        self._calendar = calendar_client
        self._contacts = contacts_client
        self._automation_store = automation_store
        self._claude_client = claude_client
        self._conversation_analyzer = conversation_analyzer
        self._session_manager = session_manager
        self._conv_store = conv_store
        self._tool_registry = tool_registry
        self._db = db
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Register built-in jobs and start the scheduler."""
        try:
            briefing_trigger = _parse_cron(settings.briefing_cron)
            checkin_trigger = _parse_cron(settings.checkin_cron)
            afternoon_cron = getattr(settings, "afternoon_cron", _AFTERNOON_CRON_DEFAULT)
            afternoon_trigger = _parse_cron(afternoon_cron)
        except ValueError as e:
            logger.error("Invalid cron config, scheduler not started: %s", e)
            return

        self._scheduler.add_job(
            self._morning_briefing,
            trigger=briefing_trigger,
            id="morning_briefing",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self._scheduler.add_job(
            self._afternoon_focus,
            trigger=afternoon_trigger,
            id="afternoon_focus",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self._scheduler.add_job(
            self._evening_checkin,
            trigger=checkin_trigger,
            id="evening_checkin",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        # Monthly retrospective — fires on the last day of each month at 18:00
        self._scheduler.add_job(
            self._monthly_retrospective,
            trigger=CronTrigger(
                day="last", hour=18, minute=0,
                timezone=settings.scheduler_timezone,
            ),
            id="monthly_retrospective",
            replace_existing=True,
            misfire_grace_time=3600,  # 1-hour grace for a monthly job
        )
        self._scheduler.start()
        logger.info(
            "Proactive scheduler started — briefing: %s, afternoon: %s, check-in: %s (tz: %s)",
            settings.briefing_cron,
            afternoon_cron,
            settings.checkin_cron,
            settings.scheduler_timezone,
        )

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Proactive scheduler stopped")

    async def load_user_automations(self) -> None:
        """
        Load all user-defined automations from the database and register them
        as APScheduler jobs. Called once after the DB is initialised.
        """
        if self._automation_store is None:
            return
        try:
            rows = await self._automation_store.get_all_for_scheduler()
        except Exception as e:
            logger.warning("Could not load user automations: %s", e)
            return

        for row in rows:
            self._register_automation_job(
                row["id"], row["user_id"], row["label"], row["cron"],
                fire_at=row.get("fire_at"),
            )
        if rows:
            logger.info("Loaded %d user automation(s) into scheduler", len(rows))

    def add_automation(
        self, automation_id: int, user_id: int, label: str, cron: str,
        fire_at: str | None = None,
    ) -> None:
        """Register a single automation job.

        For recurring reminders pass a 5-field *cron* string.
        For one-time reminders pass a *fire_at* ISO 8601 datetime string.
        """
        self._register_automation_job(automation_id, user_id, label, cron, fire_at=fire_at)

    def remove_automation(self, automation_id: int) -> None:
        """Remove an automation job from the scheduler."""
        job_id = f"automation_{automation_id}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("Removed automation job %s", job_id)
        except Exception:
            pass  # Job may not exist in scheduler (e.g. if scheduler was restarted)

    def _register_automation_job(
        self, automation_id: int, user_id: int, label: str, cron: str,
        fire_at: str | None = None,
    ) -> None:
        job_id = f"automation_{automation_id}"

        if fire_at:
            try:
                run_date = datetime.fromisoformat(fire_at)
            except ValueError as e:
                logger.warning(
                    "Skipping one-time automation %d — invalid fire_at %r: %s",
                    automation_id, fire_at, e,
                )
                return
            trigger = DateTrigger(run_date=run_date, timezone=settings.scheduler_timezone)
            one_time = True
            logger.debug("Registered one-time automation job %s (fire_at: %s)", job_id, fire_at)
        else:
            try:
                trigger = _parse_cron(cron)
            except ValueError as e:
                logger.warning(
                    "Skipping automation %d — invalid cron %r: %s", automation_id, cron, e,
                )
                return
            one_time = False
            logger.debug("Registered recurring automation job %s (cron: %s)", job_id, cron)

        async def _job():
            await self._run_automation(automation_id, user_id, label, one_time=one_time)

        self._scheduler.add_job(
            _job,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
        )

    async def _run_automation(
        self, automation_id: int, user_id: int, label: str, one_time: bool = False
    ) -> None:
        """Fire a user-defined automation through the full Claude pipeline."""
        logger.info(
            "Automation %d dispatching (one_time=%s, label=%r)", automation_id, one_time, label
        )
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.warning(
                "Automation %d skipped — primary_chat_id.txt not found. "
                "Run /setmychat in Telegram to register a chat.",
                automation_id,
            )
            return

        logger.info("Automation %d firing to chat %d", automation_id, chat_id)

        # Perform DB cleanup BEFORE sending to avoid double-firing on crashes
        if self._automation_store is not None:
            if one_time:
                try:
                    await self._automation_store.delete(automation_id)
                    logger.info("Deleted one-time automation %d before firing", automation_id)
                except Exception as e:
                    logger.warning(
                        "Could not delete one-time automation %d: %s", automation_id, e,
                    )
            else:
                try:
                    await self._automation_store.update_last_run(automation_id)
                except Exception as e:
                    logger.warning(
                        "Could not update last_run for automation %d: %s", automation_id, e,
                    )

        # Agentic path: invoke the full Claude pipeline so Remy can reason,
        # call tools, and respond meaningfully rather than echoing the label.
        pipeline_available = (
            self._session_manager is not None
            and self._conv_store is not None
            and self._tool_registry is not None
            and self._claude_client is not None
        )
        if pipeline_available:
            try:
                from ..bot.pipeline import run_proactive_trigger
                await run_proactive_trigger(
                    label=label,
                    user_id=user_id,
                    chat_id=chat_id,
                    bot=self._bot,
                    claude_client=self._claude_client,
                    tool_registry=self._tool_registry,
                    session_manager=self._session_manager,
                    conv_store=self._conv_store,
                    db=self._db,
                )
                return
            except Exception as e:
                logger.warning(
                    "Proactive pipeline failed for automation %d, falling back to raw send: %s",
                    automation_id, e,
                )

        # Fallback: raw string send (pipeline unavailable or errored)
        await self._send(chat_id, f"⏰ *Reminder:* {label}")

    async def _send(self, chat_id: int, text: str) -> None:
        """Send a message, swallowing errors so a bad send never kills the scheduler."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            logger.info("Proactive send succeeded (chat %d, %d chars)", chat_id, len(text))
        except Exception as e:
            logger.warning("Proactive send failed (chat %d): %s", chat_id, e)

    async def _morning_briefing(self) -> None:
        """07:00 job — send a summary of active goals, calendar, birthdays, downloads."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Morning briefing skipped — no primary chat ID set")
            return

        logger.info("Sending morning briefing to chat %d", chat_id)

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            logger.debug("Morning briefing skipped — no allowed users configured")
            return

        all_goal_lines: list[str] = []
        for uid in user_ids:
            goals = await self._goal_store.get_active(uid, limit=10)
            for g in goals:
                line = f"• *{g['title']}*"
                if g.get("description"):
                    line += f" — {g['description']}"
                all_goal_lines.append(line)

        now = datetime.now(timezone.utc).strftime("%A, %d %B")
        extras = []
        extras.append(f"☀️ *Good morning, Dale!* — {now}")

        if all_goal_lines:
            goals_text = "\n".join(all_goal_lines)
            extras.append(f"Here's what you're working on:\n{goals_text}\n\nMake it count today. 💪")
        else:
            extras.append(
                "You have no active goals tracked yet. "
                "Tell me what you're working on and I'll help you stay on track."
            )

        # Today's calendar events
        if self._calendar is not None:
            try:
                events = await self._calendar.list_events(days=1)
                if events:
                    event_lines = [self._calendar.format_event(e) for e in events[:5]]
                    suffix = f"\n_({len(events) - 5} more)_" if len(events) > 5 else ""
                    extras.append("📅 *Today's calendar:*\n" + "\n".join(event_lines) + suffix)
                else:
                    extras.append("📅 *Today's calendar:* Nothing scheduled.")
            except Exception as e:
                logger.debug("Could not load calendar for briefing: %s", e)

        # Include tracked projects (personal bot — use first user's facts)
        if self._fact_store is not None and user_ids:
            try:
                project_facts = await self._fact_store.get_by_category(user_ids[0], "project")
                if project_facts:
                    project_lines = [f"• `{pf['content']}`" for pf in project_facts[:3]]
                    extras.append("📁 *Tracked projects:*\n" + "\n".join(project_lines))
            except Exception as e:
                logger.debug("Could not load project facts for briefing: %s", e)

        # Upcoming birthdays (next 7 days)
        if self._contacts is not None:
            try:
                from ..google.contacts import _extract_name
                upcoming = await self._contacts.get_upcoming_birthdays(days=7)
                if upcoming:
                    bday_lines = []
                    for bday_date, person in upcoming[:5]:
                        name = _extract_name(person) or "Someone"
                        bday_lines.append(f"• 🎂 *{name}* — {bday_date.strftime('%d %b')}")
                    extras.append("*Upcoming birthdays:*\n" + "\n".join(bday_lines))
            except Exception as e:
                logger.debug("Could not load birthdays for briefing: %s", e)

        # Downloads cleanup suggestion
        downloads_msg = await self._downloads_suggestion()
        if downloads_msg:
            extras.append("\n" + downloads_msg)

        message = "\n\n".join(extras)
        await self._send(chat_id, message)

    async def _afternoon_focus(self) -> None:
        """
        14:00 job — ADHD body-double mid-day check-in.

        Picks the single most important active goal and sends a gentle focus nudge,
        optionally paired with today's remaining calendar events.
        """
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Afternoon focus skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        # Grab top active goal
        top_goal: str | None = None
        try:
            goals = await self._goal_store.get_active(user_ids[0], limit=5)
            if goals:
                top_goal = goals[0]["title"]
        except Exception as e:
            logger.debug("Could not load goals for afternoon focus: %s", e)

        extras = ["🎯 *Afternoon focus check-in*"]

        if top_goal:
            extras.append(f"Your top priority right now: *{top_goal}*\nHow's it going?")
        else:
            extras.append(
                "You haven't set any goals yet — tell me what you're working on "
                "and I'll help you stay focused."
            )

        # Remaining calendar events today
        if self._calendar is not None:
            try:
                events = await self._calendar.list_events(days=1)
                now_utc = datetime.now(timezone.utc)
                # Filter to events that haven't started yet (basic heuristic: check title)
                remaining = events[:3] if events else []
                if remaining:
                    lines = [self._calendar.format_event(e) for e in remaining]
                    extras.append("📅 *Still on today's schedule:*\n" + "\n".join(lines))
            except Exception as e:
                logger.debug("Could not load calendar for afternoon focus: %s", e)

        extras.append("_3 focused hours before end of day — you've got this._")
        await self._send(chat_id, "\n\n".join(extras))

    async def _downloads_suggestion(self) -> str:
        """Return a short message suggesting cleanup of ~/Downloads."""
        from pathlib import Path
        downloads = Path.home() / "Downloads"
        if not downloads.exists():
            return ""
        old = [
            f.name for f in downloads.iterdir()
            if f.is_file() and f.stat().st_mtime < time.time() - 7 * 86400
        ]
        if not old:
            return ""
        lines = "\n".join(old[:10])
        if len(old) > 10:
            lines += f"\n…and {len(old) - 10} more files"
        return f"🧹 *Downloads cleanup suggestion*\nThese files are older than a week:\n{lines}"

    async def _evening_checkin(self) -> None:
        """19:00 job — nudge about goals that haven't been mentioned recently."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Evening check-in skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        stale_lines: list[str] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=_STALE_GOAL_DAYS)

        for uid in user_ids:
            goals = await self._goal_store.get_active(uid, limit=10)
            for g in goals:
                ts_str = g.get("updated_at") or g.get("created_at", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        stale_lines.append(f"• *{g['title']}*")
                except ValueError:
                    continue

        if not stale_lines:
            logger.debug("Evening check-in: no stale goals, skipping send")
            return

        goals_text = "\n".join(stale_lines)
        message = (
            f"🌙 *Evening check-in*\n\n"
            f"You haven't mentioned these goals in a while:\n{goals_text}\n\n"
            f"Still working on them? Let me know how it's going."
        )
        logger.info(
            "Sending evening check-in to chat %d (%d stale goals)",
            chat_id, len(stale_lines),
        )
        await self._send(chat_id, message)

    async def _monthly_retrospective(self) -> None:
        """Last-day-of-month job — generate and send a monthly retrospective."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Monthly retrospective skipped — no primary chat ID set")
            return
        if self._conversation_analyzer is None or self._claude_client is None:
            logger.debug("Monthly retrospective skipped — analytics or Claude not configured")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        logger.info("Sending monthly retrospective to chat %d", chat_id)
        try:
            retro = await self._conversation_analyzer.generate_retrospective(
                user_ids[0], "month", self._claude_client
            )
            if len(retro) > 4000:
                retro = retro[:4000] + "…"
            await self._send(chat_id, retro)
        except Exception as e:
            logger.error("Monthly retrospective job failed: %s", e)

    # ------------------------------------------------------------------ #
    # Manual triggers (for /briefing etc.)                                 #
    # ------------------------------------------------------------------ #

    async def send_morning_briefing_now(self) -> None:
        """Trigger the morning briefing immediately (e.g. via /briefing command)."""
        await self._morning_briefing()

    async def send_evening_checkin_now(self) -> None:
        """Trigger the evening check-in immediately."""
        await self._evening_checkin()

    async def send_afternoon_focus_now(self) -> None:
        """Trigger the afternoon focus check-in immediately."""
        await self._afternoon_focus()

    async def send_monthly_retrospective_now(self) -> None:
        """Trigger the monthly retrospective immediately (e.g. via /retrospective command)."""
        await self._monthly_retrospective()
