"""Evaluative heartbeat handler — gathers context, calls model, delivers or HEARTBEAT_OK.

SAD v7: runs tool queries (goals, calendar, email, reminders), passes results to model
with merged HEARTBEAT.md config; if response is HEARTBEAT_OK, exit silently; else enqueue
message to primary chat and return outcome for heartbeat_log.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..scheduler.heartbeat_config import HEARTBEAT_OK_RESPONSE, load_heartbeat_config

if TYPE_CHECKING:
    from ..memory.automations import AutomationStore
    from ..memory.counters import CounterStore
    from ..memory.goals import GoalStore
    from ..memory.plans import PlanStore
    from ..delivery.queue import OutboundQueue
    from ..google.calendar import CalendarClient
    from ..google.gmail import GmailClient
    from telegram import Bot

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatResult:
    """Result of a heartbeat evaluation."""

    outcome: str  # "HEARTBEAT_OK" | "delivered"
    content: str | None = None
    items_checked: dict[str, str] = field(default_factory=dict)
    items_surfaced: dict[str, str] = field(default_factory=dict)
    model: str = ""
    tokens_used: int = 0
    duration_ms: int = 0


class HeartbeatHandler:
    """Runs heartbeat evaluation: gather context, call model, deliver or suppress."""

    def __init__(
        self,
        goal_store: "GoalStore | None" = None,
        plan_store: "PlanStore | None" = None,
        calendar_client: "CalendarClient | None" = None,
        gmail_client: "GmailClient | None" = None,
        automation_store: "AutomationStore | None" = None,
        counter_store: "CounterStore | None" = None,
        claude_client=None,  # ClaudeClient
        outbound_queue: "OutboundQueue | None" = None,
        bot: "Bot | None" = None,
    ) -> None:
        self._goal_store = goal_store
        self._plan_store = plan_store
        self._calendar = calendar_client
        self._gmail = gmail_client
        self._automation_store = automation_store
        self._counter_store = counter_store
        self._claude = claude_client
        self._queue = outbound_queue
        self._bot = bot

    async def run(
        self,
        user_id: int,
        chat_id: int,
        config_text: str | None = None,
        current_local_time: str | None = None,
        already_surfaced_today: str | None = None,
        agent_tasks_context: str | None = None,
    ) -> HeartbeatResult:
        """Gather context, evaluate with model, return result (and optionally enqueue message)."""
        t0 = time.monotonic()
        items_checked: dict[str, str] = {}
        config = config_text or load_heartbeat_config()

        if current_local_time:
            items_checked["current_time"] = current_local_time
        if already_surfaced_today:
            items_checked["already_surfaced_today"] = already_surfaced_today

        # Goals
        if self._goal_store:
            try:
                goals = await self._goal_store.get_active(user_id, limit=20)
                if goals:
                    lines = [
                        f"• {g.get('title', '')} (ID {g.get('id')})" for g in goals
                    ]
                    items_checked["goals"] = "Active goals:\n" + "\n".join(lines)
                else:
                    items_checked["goals"] = "No active goals."
            except Exception as e:
                items_checked["goals"] = f"Error: {e}"
        else:
            items_checked["goals"] = "Goal store not available."

        # Calendar (next 1 day as proxy for "next 90 minutes" + buffer)
        if self._calendar:
            try:
                events = await self._calendar.list_events(days=1, max_results=15)
                if events:
                    lines = []
                    for ev in events[:10]:
                        start = (ev.get("start") or {}).get("dateTime") or (
                            ev.get("start") or {}
                        ).get("date", "?")
                        summary = ev.get("summary", "No title")
                        lines.append(f"• {summary} — {start}")
                    items_checked["calendar"] = "Upcoming events:\n" + "\n".join(lines)
                else:
                    items_checked["calendar"] = "No upcoming events."
            except Exception as e:
                items_checked["calendar"] = f"Error: {e}"
        else:
            items_checked["calendar"] = "Calendar not available."

        # Email (unread count — all mail, not just inbox)
        if self._gmail:
            try:
                count = await self._gmail.get_unread_count(label_ids=[None])
                items_checked["email"] = f"Unread count (all mail): {count}."
            except Exception as e:
                items_checked["email"] = f"Error: {e}"
        else:
            items_checked["email"] = "Gmail not available."

        # Reminders
        if self._automation_store:
            try:
                rows = await self._automation_store.get_all(user_id)
                if rows:
                    lines = [
                        f"• [{r.get('id')}] {r.get('label', '')}" for r in rows[:15]
                    ]
                    items_checked["reminders"] = "Scheduled reminders:\n" + "\n".join(
                        lines
                    )
                else:
                    items_checked["reminders"] = "No scheduled reminders."
            except Exception as e:
                items_checked["reminders"] = f"Error: {e}"
        else:
            items_checked["reminders"] = "Reminders not available."

        # Agent Tasks (sub-agent system — SAD v10 §11.9)
        if agent_tasks_context:
            items_checked["agent_tasks"] = agent_tasks_context

        # Counters (e.g. sobriety streak)
        if self._counter_store:
            try:
                counters = await self._counter_store.get_all_for_inject(user_id)
                if counters:
                    lines = [
                        f"• {c['name']}: {c['value']} {c.get('unit', 'days')}"
                        for c in counters
                    ]
                    items_checked["counters"] = "Counters:\n" + "\n".join(lines)
                else:
                    items_checked["counters"] = "No counters set."
            except Exception as e:
                items_checked["counters"] = f"Error: {e}"
        else:
            items_checked["counters"] = "Counters not available."

        context_block = "\n\n".join(f"## {k}\n{v}" for k, v in items_checked.items())
        prompt = (
            f"{config}\n\n---\n\n## Current state\n\n{context_block}\n\n"
            "Evaluate the above. If nothing warrants contacting the user, respond with exactly: HEARTBEAT_OK\n"
            "Otherwise, respond with a single brief message to send (no HEARTBEAT_OK)."
        )

        outcome = HEARTBEAT_OK_RESPONSE
        content: str | None = None
        items_surfaced: dict[str, str] = {}
        model_used = ""
        tokens_used = 0

        if self._claude:
            try:
                from ..config import settings

                response = await self._claude.complete(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are the evaluative heartbeat. Be concise. Reply HEARTBEAT_OK or one short message.",
                    model=getattr(
                        settings,
                        "heartbeat_model_tier2",
                        "claude-sonnet-4-20250514",
                    ),
                    max_tokens=512,
                )
                response = (response or "").strip()
                model_used = getattr(
                    settings, "heartbeat_model_tier2", "claude-sonnet-4-20250514"
                )
                if (
                    response.upper() == HEARTBEAT_OK_RESPONSE
                    or HEARTBEAT_OK_RESPONSE in response.upper()
                ):
                    outcome = HEARTBEAT_OK_RESPONSE
                else:
                    outcome = "delivered"
                    content = response[:4000]
                    items_surfaced = {
                        "message": (content[:200] + "…")
                        if len(content) > 200
                        else content
                    }
                    from ..delivery.send import send_via_queue_or_bot

                    sent = await send_via_queue_or_bot(
                        queue=self._queue,
                        bot=self._bot,
                        chat_id=chat_id,
                        text=content,
                    )
                    if not sent:
                        logger.warning(
                            "Heartbeat: could not enqueue or send message to chat %d",
                            chat_id,
                        )
            except Exception as e:
                logger.exception("Heartbeat model call failed: %s", e)
                outcome = HEARTBEAT_OK_RESPONSE
        else:
            logger.warning("No Claude client for heartbeat — skipping evaluation")
            outcome = HEARTBEAT_OK_RESPONSE

        duration_ms = int((time.monotonic() - t0) * 1000)
        return HeartbeatResult(
            outcome=outcome,
            content=content,
            items_checked=items_checked,
            items_surfaced=items_surfaced,
            model=model_used,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
        )
