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

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from typing import TYPE_CHECKING

from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import settings
from ..memory.facts import FactStore
from ..memory.goals import GoalStore
from ..utils.telegram_formatting import (
    format_telegram_message,
    is_entity_parse_error,
)
from .briefings import (
    MorningBriefingGenerator,
    AfternoonFocusGenerator,
    EveningCheckinGenerator,
    MonthlyRetrospectiveGenerator,
)
from .briefings.week_at_a_glance import generate_week_image

if TYPE_CHECKING:
    from telegram import Bot

try:
    from telegram.error import BadRequest
except ImportError:
    BadRequest = Exception  # noqa: A001

    from ..memory.knowledge import KnowledgeStore
    from ..bot.heartbeat_handler import HeartbeatHandler
    from ..delivery.queue import OutboundQueue
    from ..google.gmail import GmailClient
    from ..memory.automations import AutomationStore
    from ..memory.counters import CounterStore
    from ..memory.plans import PlanStore
    from ..memory.file_index import FileIndexer
    from ..ai.claude_client import ClaudeClient
    from ..ai.tools import ToolRegistry
    from ..bot.session import SessionManager
    from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)

# Default cron for the afternoon focus check-in (configurable via .env)
_AFTERNOON_CRON_DEFAULT = "0 14 * * *"

# Default cron for nightly file reindexing (03:00)
_REINDEX_CRON_DEFAULT = "0 3 * * *"

# Default cron for end-of-day memory consolidation (22:00)
_CONSOLIDATION_CRON_DEFAULT = "0 22 * * *"


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


def _cron_hour(cron_str: str) -> int:
    """Extract the hour (0–23) from a 5-field cron string."""
    parts = cron_str.split()
    if len(parts) < 2:
        return 0
    try:
        return int(parts[1])
    except ValueError:
        return 0


def _delivery_log_path() -> Path:
    """Path to the persistent delivery log for startup reconciliation."""
    return Path(settings.data_dir) / "proactive_delivery_log.json"


def _load_delivery_log() -> dict[str, str]:
    """Load the delivery log: {job_id: date_str}."""
    path = _delivery_log_path()
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _record_delivery(job_id: str) -> None:
    """Record that a job fired today (for startup reconciliation)."""
    path = _delivery_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = _load_delivery_log()
    tz = ZoneInfo(settings.scheduler_timezone)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    log[job_id] = today
    try:
        with open(path, "w") as f:
            json.dump(log, f, indent=0)
    except OSError as e:
        logger.warning("Could not write delivery log: %s", e)


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
        calendar_client=None,  # remy.google.calendar.CalendarClient | None
        contacts_client=None,  # remy.google.contacts.ContactsClient | None
        gmail_client: "GmailClient | None" = None,
        automation_store: "AutomationStore | None" = None,
        claude_client: "ClaudeClient | None" = None,
        conversation_analyzer=None,  # remy.analytics.analyzer.ConversationAnalyzer | None
        session_manager: "SessionManager | None" = None,
        conv_store: "ConversationStore | None" = None,
        tool_registry: "ToolRegistry | None" = None,
        db=None,
        plan_store: "PlanStore | None" = None,
        file_indexer: "FileIndexer | None" = None,
        outbound_queue: "OutboundQueue | None" = None,
        heartbeat_handler: "HeartbeatHandler | None" = None,
        counter_store: "CounterStore | None" = None,
        knowledge_store: "KnowledgeStore | None" = None,
    ) -> None:
        self._bot = bot
        self._outbound_queue = outbound_queue
        self._heartbeat_handler = heartbeat_handler
        self._counter_store = counter_store
        self._goal_store = goal_store
        self._fact_store = fact_store
        self._knowledge_store = knowledge_store
        self._calendar = calendar_client
        self._contacts = contacts_client
        self._gmail = gmail_client
        self._automation_store = automation_store
        self._claude_client = claude_client
        self._conversation_analyzer = conversation_analyzer
        self._session_manager = session_manager
        self._conv_store = conv_store
        self._tool_registry = tool_registry
        self._db = db
        self._plan_store = plan_store
        self._file_indexer = file_indexer
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Register built-in jobs and start the scheduler."""
        heartbeat_enabled = getattr(settings, "heartbeat_enabled", True)

        heartbeat_ready = (
            heartbeat_enabled
            and self._heartbeat_handler is not None
            and self._db is not None
        )
        if heartbeat_ready:
            # Heartbeat mode: only evaluative heartbeat; never register legacy crons.
            try:
                heartbeat_cron = getattr(settings, "heartbeat_cron", "*/30 * * * *")
                heartbeat_trigger = _parse_cron(heartbeat_cron)
                from .heartbeat import run_heartbeat_job

                def _primary_user_id() -> int | None:
                    users = getattr(settings, "telegram_allowed_users", None) or []
                    return int(users[0]) if users else None

                async def _heartbeat_job() -> None:
                    await run_heartbeat_job(
                        self._heartbeat_handler,
                        self._db,
                        _read_primary_chat_id,
                        _primary_user_id,
                    )

                self._scheduler.add_job(
                    _heartbeat_job,
                    trigger=heartbeat_trigger,
                    id="evaluative_heartbeat",
                    replace_existing=True,
                    misfire_grace_time=600,
                    coalesce=True,
                )
                logger.info(
                    "Proactive scheduler: evaluative heartbeat only (cron: %s); legacy briefing/check-in crons disabled",
                    heartbeat_cron,
                )
            except ValueError as e:
                logger.error("Invalid heartbeat cron, scheduler not started: %s", e)
                return
        else:
            if heartbeat_enabled:
                logger.warning(
                    "HEARTBEAT_ENABLED=true but heartbeat_handler or db is None — "
                    "falling back to legacy briefing/check-in crons. Check initialisation."
                )
            try:
                briefing_trigger = _parse_cron(settings.briefing_cron)
                checkin_trigger = _parse_cron(settings.checkin_cron)
                afternoon_cron = getattr(
                    settings, "afternoon_cron", _AFTERNOON_CRON_DEFAULT
                )
                afternoon_trigger = _parse_cron(afternoon_cron)
                afternoon_check_trigger = _parse_cron(settings.afternoon_check_cron)
            except ValueError as e:
                logger.error("Invalid cron config, scheduler not started: %s", e)
                return

            self._scheduler.add_job(
                self._morning_briefing,
                trigger=briefing_trigger,
                id="morning_briefing",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
            )
            self._scheduler.add_job(
                self._afternoon_focus,
                trigger=afternoon_trigger,
                id="afternoon_focus",
                replace_existing=True,
                misfire_grace_time=7200,
                coalesce=True,
            )
            self._scheduler.add_job(
                self._evening_checkin,
                trigger=checkin_trigger,
                id="evening_checkin",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
            )
            self._scheduler.add_job(
                self._afternoon_check,
                trigger=afternoon_check_trigger,
                id="afternoon_check",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
            )
            # Rich media: week-at-a-glance image Monday 07:15 (US-rich-media-briefing-summaries)
            self._scheduler.add_job(
                self._week_at_a_glance_briefing,
                trigger=CronTrigger(
                    minute=15,
                    hour=7,
                    day_of_week="mon",
                    timezone=settings.scheduler_timezone,
                ),
                id="week_at_a_glance",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
            )
            logger.info(
                "Proactive scheduler: legacy briefing/check-in crons (heartbeat not active)"
            )
        # Monthly retrospective — fires on the last day of each month at 18:00
        self._scheduler.add_job(
            self._monthly_retrospective,
            trigger=CronTrigger(
                day="last",
                hour=18,
                minute=0,
                timezone=settings.scheduler_timezone,
            ),
            id="monthly_retrospective",
            replace_existing=True,
            misfire_grace_time=3600,  # 1-hour grace for a monthly job
            coalesce=True,
        )

        # Nightly file reindexing (if file indexer is configured)
        if self._file_indexer is not None and self._file_indexer.enabled:
            reindex_cron = getattr(settings, "rag_reindex_cron", _REINDEX_CRON_DEFAULT)
            try:
                reindex_trigger = _parse_cron(reindex_cron)
                self._scheduler.add_job(
                    self._reindex_files,
                    trigger=reindex_trigger,
                    id="reindex_files",
                    replace_existing=True,
                    misfire_grace_time=7200,
                    coalesce=True,
                )
                logger.info("File reindex job scheduled: %s", reindex_cron)
            except ValueError as e:
                logger.warning(
                    "Invalid reindex cron %r, job not scheduled: %s", reindex_cron, e
                )

        # End-of-day memory consolidation (22:00 by default)
        consolidation_cron = getattr(
            settings, "consolidation_cron", _CONSOLIDATION_CRON_DEFAULT
        )
        try:
            consolidation_trigger = _parse_cron(consolidation_cron)
            self._scheduler.add_job(
                self._end_of_day_consolidation,
                trigger=consolidation_trigger,
                id="end_of_day_consolidation",
                replace_existing=True,
                misfire_grace_time=7200,
                coalesce=True,
            )
            logger.info("Memory consolidation job scheduled: %s", consolidation_cron)
        except ValueError as e:
            logger.warning(
                "Invalid consolidation cron %r, job not scheduled: %s",
                consolidation_cron,
                e,
            )

        # Counter daily auto-increment (00:01 user TZ) — e.g. sobriety_streak +1 each day
        if self._counter_store is not None:
            from zoneinfo import ZoneInfo

            from ..memory.counters import AUTO_INCREMENT_DAILY_COUNTERS

            counter_store = self._counter_store

            def _primary_user_id() -> int | None:
                users = getattr(settings, "telegram_allowed_users", None) or []
                return int(users[0]) if users else None

            async def _counter_daily_increment() -> None:
                user_id = _primary_user_id()
                if user_id is None:
                    return
                tz = ZoneInfo(settings.scheduler_timezone)
                for name in AUTO_INCREMENT_DAILY_COUNTERS:
                    await counter_store.increment_daily_if_new_day(user_id, name, tz=tz)

            self._scheduler.add_job(
                _counter_daily_increment,
                trigger=CronTrigger(
                    minute=1,
                    hour=0,
                    timezone=settings.scheduler_timezone,
                ),
                id="counter_daily_increment",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
            )
            logger.info(
                "Counter daily auto-increment scheduled at 00:01 (%s)",
                settings.scheduler_timezone,
            )

        # Bug 11: log at ERROR when a job is missed by >60s (event-loop congestion signal)
        def _on_job_missed(event: JobExecutionEvent) -> None:
            scheduled = getattr(event, "scheduled_run_time", None)
            if scheduled is None:
                logger.error(
                    "APScheduler job missed: job_id=%s (no scheduled_run_time)",
                    event.job_id,
                )
                return
            now = datetime.now(
                scheduled.tzinfo if getattr(scheduled, "tzinfo", None) else timezone.utc
            )
            delta = (now - scheduled).total_seconds()
            if delta >= 60:
                logger.error(
                    "APScheduler job missed by %.0fs (event loop congestion): job_id=%s scheduled_run_time=%s",
                    delta,
                    event.job_id,
                    scheduled,
                )
            else:
                logger.warning(
                    "APScheduler job missed by %.0fs: job_id=%s",
                    delta,
                    event.job_id,
                )

        self._scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
        self._scheduler.start()
        if heartbeat_ready:
            logger.info(
                "Proactive scheduler started — evaluative heartbeat (tz: %s)",
                settings.scheduler_timezone,
            )
        else:
            afternoon_cron = getattr(
                settings, "afternoon_cron", _AFTERNOON_CRON_DEFAULT
            )
            logger.info(
                "Proactive scheduler started — briefing: %s, afternoon: %s, check-in: %s, afternoon_check: %s (tz: %s)",
                settings.briefing_cron,
                afternoon_cron,
                settings.checkin_cron,
                settings.afternoon_check_cron,
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
                row["id"],
                row["user_id"],
                row["label"],
                row["cron"],
                fire_at=row.get("fire_at"),
                mediated=bool(row.get("mediated", 0)),
            )
        if rows:
            logger.info("Loaded %d user automation(s) into scheduler", len(rows))

    async def run_startup_reconciliation(self) -> None:
        """
        On startup, fire any daily jobs (afternoon, evening, consolidation) that
        should have run today but were missed because the bot was down.

        Uses a persistent delivery log to avoid double-firing. If the current time
        is past a job's scheduled hour and we have no delivery record for today,
        fire it now (with a short delay to let the bot fully initialise).
        """
        if _read_primary_chat_id() is None:
            return

        tz = ZoneInfo(settings.scheduler_timezone)
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        current_hour = now.hour
        log = _load_delivery_log()

        afternoon_cron = getattr(settings, "afternoon_cron", _AFTERNOON_CRON_DEFAULT)
        consolidation_cron = getattr(
            settings, "consolidation_cron", _CONSOLIDATION_CRON_DEFAULT
        )

        jobs_to_fire: list[tuple[str, str]] = []  # (job_id, delay_reason)
        heartbeat_enabled = getattr(settings, "heartbeat_enabled", True)
        heartbeat_ready = (
            heartbeat_enabled
            and self._heartbeat_handler is not None
            and self._db is not None
        )
        if not heartbeat_ready:
            if (
                current_hour >= _cron_hour(afternoon_cron)
                and log.get("afternoon_focus") != today
            ):
                jobs_to_fire.append(("afternoon_focus", "afternoon focus missed"))
            if (
                current_hour >= _cron_hour(settings.checkin_cron)
                and log.get("evening_checkin") != today
            ):
                jobs_to_fire.append(("evening_checkin", "evening check-in missed"))
            if (
                current_hour >= _cron_hour(settings.afternoon_check_cron)
                and log.get("afternoon_check") != today
            ):
                jobs_to_fire.append(("afternoon_check", "afternoon check missed"))
        if (
            current_hour >= _cron_hour(consolidation_cron)
            and log.get("end_of_day_consolidation") != today
        ):
            jobs_to_fire.append(
                ("end_of_day_consolidation", "memory consolidation missed")
            )

        if not jobs_to_fire:
            return

        logger.info(
            "Startup reconciliation: firing %d missed job(s): %s",
            len(jobs_to_fire),
            [j[0] for j in jobs_to_fire],
        )

        # Short delay so the bot is fully ready
        await asyncio.sleep(5)

        for job_id, delay_reason in jobs_to_fire:
            try:
                if job_id == "afternoon_focus":
                    await self._afternoon_focus()
                elif job_id == "evening_checkin":
                    await self._evening_checkin()
                elif job_id == "afternoon_check":
                    await self._afternoon_check()
                elif job_id == "end_of_day_consolidation":
                    await self._end_of_day_consolidation()
            except Exception as e:
                logger.warning(
                    "Startup reconciliation: %s failed: %s",
                    delay_reason,
                    e,
                )

    def add_automation(
        self,
        automation_id: int,
        user_id: int,
        label: str,
        cron: str,
        fire_at: str | None = None,
        mediated: bool = False,
    ) -> None:
        """Register a single automation job.

        For recurring reminders pass a 5-field *cron* string.
        For one-time reminders pass a *fire_at* ISO 8601 datetime string.
        When *mediated* is True, the reminder is composed by Claude at fire time.
        """
        self._register_automation_job(
            automation_id, user_id, label, cron, fire_at=fire_at, mediated=mediated
        )

    def remove_automation(self, automation_id: int) -> None:
        """Remove an automation job from the scheduler."""
        job_id = f"automation_{automation_id}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("Removed automation job %s", job_id)
        except Exception as e:
            logger.debug(
                "Job %s not found in scheduler (may have been restarted): %s", job_id, e
            )

    def _register_automation_job(
        self,
        automation_id: int,
        user_id: int,
        label: str,
        cron: str,
        fire_at: str | None = None,
        mediated: bool = False,
    ) -> None:
        job_id = f"automation_{automation_id}"

        if fire_at:
            try:
                run_date = datetime.fromisoformat(fire_at)
            except ValueError as e:
                logger.warning(
                    "Skipping one-time automation %d — invalid fire_at %r: %s",
                    automation_id,
                    fire_at,
                    e,
                )
                return
            trigger = DateTrigger(
                run_date=run_date, timezone=settings.scheduler_timezone
            )
            one_time = True
            logger.debug(
                "Registered one-time automation job %s (fire_at: %s)", job_id, fire_at
            )
        else:
            try:
                trigger = _parse_cron(cron)
            except ValueError as e:
                logger.warning(
                    "Skipping automation %d — invalid cron %r: %s",
                    automation_id,
                    cron,
                    e,
                )
                return
            one_time = False
            logger.debug(
                "Registered recurring automation job %s (cron: %s)", job_id, cron
            )

        async def _job():
            await self._run_automation(
                automation_id, user_id, label, one_time=one_time, mediated=mediated
            )

        self._scheduler.add_job(
            _job,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

    async def _run_automation(
        self,
        automation_id: int,
        user_id: int,
        label: str,
        one_time: bool = False,
        mediated: bool = False,
    ) -> None:
        """Fire a user-defined automation. Mediated: full Claude pipeline; else direct send."""
        logger.info(
            "Automation %d dispatching (one_time=%s, mediated=%s, label=%r)",
            automation_id,
            one_time,
            mediated,
            label,
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
                    logger.info(
                        "Deleted one-time automation %d before firing", automation_id
                    )
                except Exception as e:
                    logger.warning(
                        "Could not delete one-time automation %d: %s",
                        automation_id,
                        e,
                    )
                # Log the completed reminder as a memory fact for future reference
                await self._log_completed_reminder(user_id, label)
            else:
                try:
                    await self._automation_store.update_last_run(automation_id)
                except Exception as e:
                    logger.warning(
                        "Could not update last_run for automation %d: %s",
                        automation_id,
                        e,
                    )

        # Mediated path: full Claude pipeline (context-aware message at fire time).
        # Non-mediated: send stored label directly (logistical/alarm reminders).
        session_manager = self._session_manager
        conv_store = self._conv_store
        tool_registry = self._tool_registry
        claude_client = self._claude_client
        pipeline_available = (
            mediated
            and session_manager is not None
            and conv_store is not None
            and tool_registry is not None
            and claude_client is not None
        )
        if pipeline_available:
            assert claude_client is not None
            assert tool_registry is not None
            assert session_manager is not None
            assert conv_store is not None
            try:
                from ..bot.pipeline import compose_proactive_message

                await compose_proactive_message(
                    label=label,
                    user_id=user_id,
                    chat_id=chat_id,
                    bot=self._bot,
                    claude_client=claude_client,
                    tool_registry=tool_registry,
                    session_manager=session_manager,
                    conv_store=conv_store,
                    db=self._db,
                    automation_id=0 if one_time else automation_id,
                    one_time=one_time,
                )
                return
            except Exception as e:
                logger.warning(
                    "Proactive pipeline failed for automation %d, falling back to raw send: %s",
                    automation_id,
                    e,
                )

        # Fallback: raw string send with snooze/done buttons
        user_ids = settings.telegram_allowed_users
        uid = user_ids[0] if user_ids else user_id
        await self._send_reminder(
            chat_id=chat_id,
            text=f"⏰ *Reminder:* {label}",
            user_id=uid,
            label=label,
            automation_id=automation_id if not one_time else 0,
            one_time=one_time,
        )

    async def _log_completed_reminder(self, user_id: int, label: str) -> None:
        """Store a fact recording that a one-time reminder was completed.

        This gives Remy a persistent history of completed tasks/reminders,
        preventing stale reminders and enabling "what reminders have I had?" queries.
        Phase 1.4: prefer KnowledgeStore; fall back to FactStore only when knowledge_store is None.
        """
        if self._knowledge_store is None and self._fact_store is None:
            logger.debug("Cannot log completed reminder — no store configured")
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fact_content = f"Reminder completed: {label} ({today})"

        try:
            if self._knowledge_store is not None:
                await self._knowledge_store.add_item(
                    user_id, "fact", fact_content, {"category": "other"}
                )
            elif self._fact_store is not None:
                await self._fact_store.add(user_id, fact_content, category="other")
            logger.info(
                "Logged completed one-time reminder as fact for user %d: %s",
                user_id,
                label[:50],
            )
        except Exception as e:
            logger.warning(
                "Could not log completed reminder as fact: %s",
                e,
            )

    async def _send(self, chat_id: int, text: str) -> None:
        """Send a message via queue (when available) or bot, swallowing errors."""
        from ..delivery.send import send_via_queue_or_bot

        formatted = format_telegram_message(text)
        ok = await send_via_queue_or_bot(
            queue=self._outbound_queue,
            bot=self._bot,
            chat_id=chat_id,
            text=formatted,
            parse_mode="MarkdownV2",
        )
        if ok:
            logger.info(
                "Proactive send succeeded (chat %d, %d chars)", chat_id, len(text)
            )
            return
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
            logger.info(
                "Proactive send succeeded (plain text fallback, chat %d)", chat_id
            )
        except Exception as e:
            logger.warning("Proactive send failed (chat %d): %s", chat_id, e)

    async def _send_reminder(
        self,
        chat_id: int,
        text: str,
        user_id: int,
        label: str,
        automation_id: int = 0,
        one_time: bool = False,
    ) -> None:
        """Send a reminder message with [Snooze 5m] [Snooze 15m] [Done] inline keyboard."""
        from ..bot.handlers.callbacks import (
            make_reminder_keyboard,
            store_reminder_payload,
        )

        token = store_reminder_payload(
            user_id=user_id,
            chat_id=chat_id,
            label=label,
            automation_id=automation_id,
            one_time=one_time,
        )
        keyboard = make_reminder_keyboard(token)
        try:
            formatted = format_telegram_message(text)
            await self._bot.send_message(
                chat_id=chat_id,
                text=formatted,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
            logger.info(
                "Proactive reminder sent (chat %d, %d chars, with snooze/done buttons)",
                chat_id,
                len(text),
            )
        except BadRequest as e:
            if is_entity_parse_error(e):
                logger.debug(
                    "MarkdownV2 entity parse error on reminder, falling back to plain: %s",
                    e,
                )
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                )
                logger.info(
                    "Proactive reminder sent (plain text fallback, chat %d)", chat_id
                )
            except Exception as e2:
                logger.warning(
                    "Proactive reminder send failed (chat %d): %s", chat_id, e2
                )
        except Exception as e:
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                )
                logger.info(
                    "Proactive reminder sent (plain text fallback, chat %d)", chat_id
                )
            except Exception as e2:
                logger.warning(
                    "Proactive reminder send failed (chat %d): %s", chat_id, e2
                )

    async def _morning_briefing(self) -> None:
        """07:00 job — send a summary of active goals, calendar, birthdays, downloads.

        US-conversational-briefing-via-remy: tries Claude-composed briefing first;
        falls back to template if Claude fails or is unavailable.
        """
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Morning briefing skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            logger.debug("Morning briefing skipped — no allowed users configured")
            return

        user_id = user_ids[0]
        logger.info("Sending morning briefing to chat %d", chat_id)

        generator = MorningBriefingGenerator(
            user_id=user_id,
            goal_store=self._goal_store,
            plan_store=self._plan_store,
            fact_store=self._fact_store,
            calendar=self._calendar,
            contacts=self._contacts,
            gmail=self._gmail,
            file_indexer=self._file_indexer,
            claude=self._claude_client,
        )

        # Try Claude-composed briefing first (US-conversational-briefing-via-remy).
        # Uses shared compose_proactive_message helper (US-remy-mediated-reminders).
        if (
            self._claude_client is not None
            and self._tool_registry is not None
            and self._session_manager is not None
            and self._conv_store is not None
        ):
            try:
                payload = await generator.generate_structured()
                from ..bot.pipeline import compose_proactive_message

                await compose_proactive_message(
                    label="Morning briefing",
                    user_id=user_id,
                    chat_id=chat_id,
                    bot=self._bot,
                    claude_client=self._claude_client,
                    tool_registry=self._tool_registry,
                    session_manager=self._session_manager,
                    conv_store=self._conv_store,
                    db=self._db,
                    context=payload,
                )
                _record_delivery("morning_briefing")
                return
            except Exception as e:
                logger.warning(
                    "Claude morning briefing failed, falling back to template: %s", e
                )

        # Fallback: template-generated briefing
        content = await generator.generate()
        await self._send(chat_id, content)
        _record_delivery("morning_briefing")

    async def _week_at_a_glance_briefing(self) -> None:
        """Monday 07:15 — send week-at-a-glance image with caption (US-rich-media-briefing-summaries)."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Week-at-a-glance skipped — no primary chat ID set")
            return
        user_ids = settings.telegram_allowed_users
        if not user_ids:
            logger.debug("Week-at-a-glance skipped — no allowed users configured")
            return
        user_id = user_ids[0]
        goals_text = ""
        if self._goal_store:
            goals = await self._goal_store.get_active(user_id, limit=10)
            goals_text = ", ".join((g.get("title") or "") for g in goals)
        tz_name = getattr(settings, "scheduler_timezone", "Australia/Sydney")
        png_bytes, caption = generate_week_image(
            goals_text=goals_text,
            tz_name=tz_name,
        )
        if png_bytes and caption:
            try:
                await self._bot.send_photo(
                    chat_id=chat_id,
                    photo=png_bytes,
                    caption=caption,
                )
                _record_delivery("week_at_a_glance")
                logger.info("Week-at-a-glance sent to chat %d", chat_id)
            except Exception as e:
                logger.warning("Week-at-a-glance send_photo failed: %s", e)
                await self._send(chat_id, caption or "Week ahead.")
                _record_delivery("week_at_a_glance")
        else:
            await self._send(chat_id, caption or "Week ahead.")
            _record_delivery("week_at_a_glance")

    async def _afternoon_focus(self) -> None:
        """
        14:00 (or CHECKIN_CRON) job — ADHD body-double mid-day / 5pm check-in.

        Picks the single most important active goal and sends a gentle focus nudge,
        optionally paired with today's remaining calendar events.
        Mediated (US-remy-mediated-reminders).
        """
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Afternoon focus skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        user_id = user_ids[0]
        generator = AfternoonFocusGenerator(
            user_id=user_id,
            goal_store=self._goal_store,
            calendar=self._calendar,
        )

        # Mediated path: Claude composes at fire time (US-remy-mediated-reminders).
        if (
            self._claude_client is not None
            and self._tool_registry is not None
            and self._session_manager is not None
            and self._conv_store is not None
        ):
            try:
                payload = await generator.generate_structured()
                from ..bot.pipeline import compose_proactive_message

                await compose_proactive_message(
                    label="Afternoon focus check-in",
                    user_id=user_id,
                    chat_id=chat_id,
                    bot=self._bot,
                    claude_client=self._claude_client,
                    tool_registry=self._tool_registry,
                    session_manager=self._session_manager,
                    conv_store=self._conv_store,
                    db=self._db,
                    context=payload,
                )
                _record_delivery("afternoon_focus")
                return
            except Exception as e:
                logger.warning(
                    "Claude afternoon focus failed, falling back to template: %s", e
                )

        # Fallback: template-generated message
        content = await generator.generate()
        await self._send(chat_id, content)
        _record_delivery("afternoon_focus")

    async def _evening_checkin(self) -> None:
        """19:00 job — nudge about goals that haven't been mentioned recently. Mediated (US-remy-mediated-reminders)."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Evening check-in skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        user_id = user_ids[0]
        generator = EveningCheckinGenerator(
            user_id=user_id,
            goal_store=self._goal_store,
            stale_days=settings.stale_goal_days,
            conv_store=self._conv_store,
            calendar=self._calendar,
        )

        # Mediated path: Claude composes at fire time (US-remy-mediated-reminders).
        if (
            self._claude_client is not None
            and self._tool_registry is not None
            and self._session_manager is not None
            and self._conv_store is not None
        ):
            try:
                payload = await generator.generate_structured()
                if payload is not None:
                    # Bug 12: inject live counters (e.g. sobriety_streak) at fire time
                    if self._counter_store is not None:
                        try:
                            counters = await self._counter_store.get_all_for_inject(
                                user_id
                            )
                            if counters:
                                payload["counters"] = counters
                        except Exception as e:
                            logger.debug(
                                "Evening check-in: could not load counters: %s", e
                            )
                    from ..bot.pipeline import compose_proactive_message

                    await compose_proactive_message(
                        label="Evening check-in",
                        user_id=user_id,
                        chat_id=chat_id,
                        bot=self._bot,
                        claude_client=self._claude_client,
                        tool_registry=self._tool_registry,
                        session_manager=self._session_manager,
                        conv_store=self._conv_store,
                        db=self._db,
                        context=payload,
                    )
                    _record_delivery("evening_checkin")
                    return
            except Exception as e:
                logger.warning(
                    "Claude evening check-in failed, falling back to template: %s", e
                )

        # Fallback: template-generated message
        content = await generator.generate()
        if not content:
            return
        logger.info("Sending evening check-in to chat %d", chat_id)
        await self._send(chat_id, content)
        _record_delivery("evening_checkin")

    async def _afternoon_check(self) -> None:
        """
        17:00 (afternoon_check_cron) — afternoon check-in.

        Mediated only: compassionate, context-relevant message (US-remy-mediated-reminders).
        Always routed through Remy.
        """
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Afternoon check skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        user_id = user_ids[0]
        context: dict = {"afternoon_check": True, "goals": [], "calendar_summary": None}
        if self._goal_store is not None:
            goals = await self._goal_store.get_active(user_id, limit=5)
            context["goals"] = [{"title": g.get("title")} for g in goals]
        if self._calendar is not None:
            try:
                events = await self._calendar.list_events(days=1)
                if events:
                    context["calendar_summary"] = ", ".join(
                        self._calendar.format_event(e) for e in events[:5]
                    )
                else:
                    context["calendar_summary"] = "Nothing scheduled."
            except Exception as e:
                logger.debug("Could not load calendar for afternoon check: %s", e)

        if (
            self._claude_client is None
            or self._tool_registry is None
            or self._session_manager is None
            or self._conv_store is None
        ):
            logger.warning(
                "Afternoon check skipped — mediated path required but dependencies missing"
            )
            return

        try:
            from ..bot.pipeline import compose_proactive_message

            await compose_proactive_message(
                label="Afternoon check-in",
                user_id=user_id,
                chat_id=chat_id,
                bot=self._bot,
                claude_client=self._claude_client,
                tool_registry=self._tool_registry,
                session_manager=self._session_manager,
                conv_store=self._conv_store,
                db=self._db,
                context=context,
            )
            _record_delivery("afternoon_check")
        except Exception as e:
            logger.error("Afternoon check failed: %s", e)

    async def _monthly_retrospective(self) -> None:
        """Last-day-of-month job — generate and send a monthly retrospective."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Monthly retrospective skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        generator = MonthlyRetrospectiveGenerator(
            user_id=user_ids[0],
            claude=self._claude_client,
            conversation_analyzer=self._conversation_analyzer,
        )
        content = await generator.generate()
        if not content:
            return

        logger.info("Sending monthly retrospective to chat %d", chat_id)
        await self._send(chat_id, content)

    async def _reindex_files(self) -> None:
        """Nightly job — run incremental file indexing for home directory RAG."""
        if self._file_indexer is None:
            logger.debug("File reindex skipped — file indexer not configured")
            return

        if not self._file_indexer.enabled:
            logger.debug("File reindex skipped — file indexer disabled")
            return

        logger.info("Starting nightly file reindex...")
        try:
            stats = await self._file_indexer.run_incremental()
            logger.info(
                "Nightly file reindex complete: %d files indexed, %d chunks created, "
                "%d files removed, %d errors",
                stats.get("files_indexed", 0),
                stats.get("chunks_created", 0),
                stats.get("files_removed", 0),
                stats.get("errors", 0),
            )
        except Exception as e:
            logger.error("Nightly file reindex failed: %s", e)

    async def _end_of_day_consolidation(self) -> None:
        """
        22:00 job — review the day's conversations and extract facts/goals to persist.

        Uses Claude to analyse conversation history and identify:
        - Completed tasks worth recording
        - Personal updates (health, work, relationships)
        - Decisions and preferences
        - Plans and commitments

        Stores extracted items via the knowledge store, avoiding duplicates
        through semantic deduplication.
        """
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Memory consolidation skipped — no primary chat ID set")
            return

        if self._conv_store is None:
            logger.debug(
                "Memory consolidation skipped — conversation store not configured"
            )
            return

        if self._claude_client is None:
            logger.debug("Memory consolidation skipped — Claude client not configured")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            logger.debug("Memory consolidation skipped — no allowed users configured")
            return

        logger.info("Starting end-of-day memory consolidation")

        for user_id in user_ids:
            try:
                result = await self._consolidate_user_memory(user_id)
                if (
                    result.get("facts_stored", 0) > 0
                    or result.get("goals_stored", 0) > 0
                ):
                    logger.info(
                        "Memory consolidation for user %d: %d facts, %d goals stored",
                        user_id,
                        result.get("facts_stored", 0),
                        result.get("goals_stored", 0),
                    )
            except Exception as e:
                logger.error("Memory consolidation failed for user %d: %s", user_id, e)

        _record_delivery("end_of_day_consolidation")

    async def _consolidate_user_memory(self, user_id: int) -> dict:
        """
        Consolidate a single user's conversations into persistent memory.

        Returns dict with facts_stored and goals_stored counts.
        """
        if self._conv_store is None:
            return {"facts_stored": 0, "goals_stored": 0}
        turns = await self._conv_store.get_today_messages(user_id)
        if not turns:
            logger.debug("No conversations today for user %d", user_id)
            return {"facts_stored": 0, "goals_stored": 0}

        # Build conversation transcript for Claude
        transcript_lines = []
        for turn in turns:
            role_label = "Dale" if turn.role == "user" else "Remy"
            content = turn.content
            # Skip tool turns and compacted summaries
            if content.startswith("__TOOL_TURN__:") or content.startswith(
                "[COMPACTED SUMMARY]"
            ):
                continue
            # Truncate very long messages
            if len(content) > 500:
                content = content[:500] + "..."
            transcript_lines.append(f"{role_label}: {content}")

        if not transcript_lines:
            return {"facts_stored": 0, "goals_stored": 0}

        transcript = "\n".join(transcript_lines[-50:])  # Last 50 exchanges max

        # Ask Claude to extract persistable information
        prompt = (
            "Review this conversation between Dale and his AI assistant Remy from today.\n\n"
            f"CONVERSATION:\n{transcript}\n\n"
            "Extract any information worth persisting to long-term memory. Look for:\n"
            "1. Completed tasks or resolved items (e.g. 'tyre's done', 'finished the report')\n"
            "2. Personal updates (health, work, relationships, living situation)\n"
            "3. Decisions made (e.g. 'going with CommBank', 'decided to take the job')\n"
            "4. People's plans or whereabouts (e.g. 'Alex is away this weekend')\n"
            "5. New goals or commitments mentioned\n\n"
            "Respond in JSON format:\n"
            "{\n"
            '  "facts": [\n'
            '    {"content": "fact text", "category": "category_name"}\n'
            "  ],\n"
            '  "goals": [\n'
            '    {"title": "goal title", "description": "optional description"}\n'
            "  ]\n"
            "}\n\n"
            "Categories: name, location, occupation, health, medical, finance, hobby, "
            "relationship, preference, deadline, project, other.\n\n"
            "Only include genuinely useful information. Skip:\n"
            "- Trivial chat ('it's hot today')\n"
            "- Information already stored (assume Remy stores facts proactively)\n"
            "- Temporary states that will change soon\n\n"
            'If nothing worth storing, return: {"facts": [], "goals": []}'
        )

        if self._claude_client is None:
            return {"facts_stored": 0, "goals_stored": 0}
        try:
            response = await self._claude_client.complete(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a memory extraction assistant. Extract only genuinely useful "
                    "long-term information from conversations. Be conservative — only extract "
                    "facts that would be valuable to remember in future conversations. "
                    "Respond only with valid JSON."
                ),
                model=settings.model_simple,  # Use Haiku for cost efficiency
                max_tokens=1000,
            )
        except Exception as e:
            logger.error("Claude consolidation call failed: %s", e)
            return {"facts_stored": 0, "goals_stored": 0}

        # Parse Claude's response
        import json

        try:
            # Handle response that might have markdown code blocks
            response_text = response if isinstance(response, str) else str(response)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            data = json.loads(response_text.strip())
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("Could not parse consolidation response: %s", e)
            return {"facts_stored": 0, "goals_stored": 0}

        facts_stored = 0
        goals_stored = 0

        # Store extracted facts (Phase 1.4: prefer KnowledgeStore)
        facts = data.get("facts", [])
        store_facts = self._knowledge_store is not None or self._fact_store is not None
        if facts and store_facts:
            for fact in facts[:10]:  # Cap at 10 facts per day
                content = fact.get("content", "").strip()
                category = fact.get("category", "other").strip().lower()
                if not content:
                    continue
                try:
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if today not in content:
                        content = f"{content} ({today})"
                    if self._knowledge_store is not None:
                        await self._knowledge_store.add_item(
                            user_id, "fact", content, {"category": category}
                        )
                    elif self._fact_store is not None:
                        await self._fact_store.add(user_id, content, category)
                    facts_stored += 1
                    logger.debug("Consolidated fact: [%s] %s", category, content[:50])
                except Exception as e:
                    logger.warning("Could not store consolidated fact: %s", e)

        # Store extracted goals (Phase 1.4: prefer KnowledgeStore)
        goals = data.get("goals", [])
        store_goals = self._knowledge_store is not None or self._goal_store is not None
        if goals and store_goals:
            for goal in goals[:5]:  # Cap at 5 goals per day
                title = goal.get("title", "").strip()
                description = goal.get("description", "").strip() or None
                if not title:
                    continue
                try:
                    if self._knowledge_store is not None:
                        metadata = {"status": "active"}
                        if description:
                            metadata["description"] = description
                        await self._knowledge_store.add_item(
                            user_id, "goal", title, metadata
                        )
                    else:
                        await self._goal_store.add(user_id, title, description)
                    goals_stored += 1
                    logger.debug("Consolidated goal: %s", title[:50])
                except Exception as e:
                    logger.warning("Could not store consolidated goal: %s", e)

        return {"facts_stored": facts_stored, "goals_stored": goals_stored}

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

    async def run_file_reindex_now(self) -> dict:
        """Trigger file reindexing immediately (e.g. via /reindex command).

        Returns stats dict with files_indexed, chunks_created, etc.
        """
        if self._file_indexer is None:
            return {"status": "error", "message": "File indexer not configured"}
        if not self._file_indexer.enabled:
            return {"status": "error", "message": "File indexer disabled"}
        return await self._file_indexer.run_incremental()

    async def run_memory_consolidation_now(self, user_id: int | None = None) -> dict:
        """
        Trigger memory consolidation immediately (e.g. via /consolidate command).

        Args:
            user_id: Specific user to consolidate. If None, consolidates all allowed users.

        Returns:
            Dict with total facts_stored and goals_stored counts.
        """
        if self._conv_store is None:
            return {"status": "error", "message": "Conversation store not configured"}
        if self._claude_client is None:
            return {"status": "error", "message": "Claude client not configured"}

        user_ids = [user_id] if user_id else settings.telegram_allowed_users
        if not user_ids:
            return {"status": "error", "message": "No users to consolidate"}

        total_facts = 0
        total_goals = 0

        for uid in user_ids:
            try:
                result = await self._consolidate_user_memory(uid)
                total_facts += result.get("facts_stored", 0)
                total_goals += result.get("goals_stored", 0)
            except Exception as e:
                logger.error("Consolidation failed for user %d: %s", uid, e)

        return {
            "status": "success",
            "facts_stored": total_facts,
            "goals_stored": total_goals,
        }
