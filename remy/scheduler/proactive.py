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
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from ..config import settings
from ..memory.facts import FactStore
from ..memory.goals import GoalStore
from .briefings import (
    MorningBriefingGenerator,
    AfternoonFocusGenerator,
    EveningCheckinGenerator,
    MonthlyRetrospectiveGenerator,
)

if TYPE_CHECKING:
    from telegram import Bot
    from ..memory.automations import AutomationStore
    from ..memory.plans import PlanStore
    from ..memory.file_index import FileIndexer
    from ..ai.claude_client import ClaudeClient
    from ..ai.tool_registry import ToolRegistry
    from ..bot.session import SessionManager
    from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)

# Goals not updated within this many days trigger an evening nudge
_STALE_GOAL_DAYS = 3

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
        plan_store: "PlanStore | None" = None,
        file_indexer: "FileIndexer | None" = None,
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
        self._plan_store = plan_store
        self._file_indexer = file_indexer
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
                    misfire_grace_time=3600,
                )
                logger.info("File reindex job scheduled: %s", reindex_cron)
            except ValueError as e:
                logger.warning("Invalid reindex cron %r, job not scheduled: %s", reindex_cron, e)

        # End-of-day memory consolidation (22:00 by default)
        consolidation_cron = getattr(settings, "consolidation_cron", _CONSOLIDATION_CRON_DEFAULT)
        try:
            consolidation_trigger = _parse_cron(consolidation_cron)
            self._scheduler.add_job(
                self._end_of_day_consolidation,
                trigger=consolidation_trigger,
                id="end_of_day_consolidation",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info("Memory consolidation job scheduled: %s", consolidation_cron)
        except ValueError as e:
            logger.warning("Invalid consolidation cron %r, job not scheduled: %s", consolidation_cron, e)

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
        except Exception as e:
            logger.debug("Job %s not found in scheduler (may have been restarted): %s", job_id, e)

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
                # Log the completed reminder as a memory fact for future reference
                await self._log_completed_reminder(user_id, label)
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

    async def _log_completed_reminder(self, user_id: int, label: str) -> None:
        """Store a fact recording that a one-time reminder was completed.

        This gives Remy a persistent history of completed tasks/reminders,
        preventing stale reminders and enabling "what reminders have I had?" queries.
        """
        if self._fact_store is None:
            logger.debug("Cannot log completed reminder — fact_store not configured")
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fact_content = f"Reminder completed: {label} ({today})"

        try:
            await self._fact_store.add(user_id, fact_content, category="other")
            logger.info(
                "Logged completed one-time reminder as fact for user %d: %s",
                user_id, label[:50],
            )
        except Exception as e:
            logger.warning(
                "Could not log completed reminder as fact: %s", e,
            )

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

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            logger.debug("Morning briefing skipped — no allowed users configured")
            return

        logger.info("Sending morning briefing to chat %d", chat_id)

        generator = MorningBriefingGenerator(
            user_id=user_ids[0],
            goal_store=self._goal_store,
            plan_store=self._plan_store,
            fact_store=self._fact_store,
            calendar=self._calendar,
            contacts=self._contacts,
            file_indexer=self._file_indexer,
            claude=self._claude_client,
        )
        content = await generator.generate()
        await self._send(chat_id, content)

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

        generator = AfternoonFocusGenerator(
            user_id=user_ids[0],
            goal_store=self._goal_store,
            calendar=self._calendar,
        )
        content = await generator.generate()
        await self._send(chat_id, content)

    async def _evening_checkin(self) -> None:
        """19:00 job — nudge about goals that haven't been mentioned recently."""
        chat_id = _read_primary_chat_id()
        if chat_id is None:
            logger.debug("Evening check-in skipped — no primary chat ID set")
            return

        user_ids = settings.telegram_allowed_users
        if not user_ids:
            return

        generator = EveningCheckinGenerator(
            user_id=user_ids[0],
            goal_store=self._goal_store,
            stale_days=_STALE_GOAL_DAYS,
        )
        content = await generator.generate()
        if not content:
            return

        logger.info("Sending evening check-in to chat %d", chat_id)
        await self._send(chat_id, content)

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
            logger.debug("Memory consolidation skipped — conversation store not configured")
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
                if result.get("facts_stored", 0) > 0 or result.get("goals_stored", 0) > 0:
                    logger.info(
                        "Memory consolidation for user %d: %d facts, %d goals stored",
                        user_id, result.get("facts_stored", 0), result.get("goals_stored", 0),
                    )
            except Exception as e:
                logger.error("Memory consolidation failed for user %d: %s", user_id, e)

    async def _consolidate_user_memory(self, user_id: int) -> dict:
        """
        Consolidate a single user's conversations into persistent memory.

        Returns dict with facts_stored and goals_stored counts.
        """
        from ..memory.knowledge import KnowledgeStore

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
            if content.startswith("__TOOL_TURN__:") or content.startswith("[COMPACTED SUMMARY]"):
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
            "If nothing worth storing, return: {\"facts\": [], \"goals\": []}"
        )

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

        # Store extracted facts
        facts = data.get("facts", [])
        if facts and self._fact_store is not None:
            for fact in facts[:10]:  # Cap at 10 facts per day
                content = fact.get("content", "").strip()
                category = fact.get("category", "other").strip().lower()
                if not content:
                    continue
                try:
                    # Add date context to the fact
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if today not in content:
                        content = f"{content} ({today})"
                    await self._fact_store.add(user_id, content, category)
                    facts_stored += 1
                    logger.debug("Consolidated fact: [%s] %s", category, content[:50])
                except Exception as e:
                    logger.warning("Could not store consolidated fact: %s", e)

        # Store extracted goals
        goals = data.get("goals", [])
        if goals and self._goal_store is not None:
            for goal in goals[:5]:  # Cap at 5 goals per day
                title = goal.get("title", "").strip()
                description = goal.get("description", "").strip() or None
                if not title:
                    continue
                try:
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
