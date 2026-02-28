"""
Memory and goal handlers.

Contains handlers for goals, plans, conversation management, and memory consolidation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized
from ..session import SessionManager

if TYPE_CHECKING:
    from ...memory.conversations import ConversationStore
    from ...memory.goals import GoalStore
    from ...memory.plans import PlanStore
    from ...memory.background_jobs import BackgroundJobStore
    from ..working_message import WorkingMessage

logger = logging.getLogger(__name__)


def make_memory_handlers(
    *,
    session_manager: SessionManager,
    conv_store: "ConversationStore",
    claude_client=None,
    goal_store: "GoalStore | None" = None,
    plan_store: "PlanStore | None" = None,
    job_store: "BackgroundJobStore | None" = None,
    scheduler_ref: dict | None = None,
):
    """
    Factory that returns memory and goal handlers.
    
    Returns a dict of command_name -> handler_function.
    """

    async def goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List your currently active goals."""
        if await reject_unauthorized(update):
            return
        if goal_store is None:
            await update.message.reply_text("Memory not available.")
            return
        user_id = update.effective_user.id
        goals = await goal_store.get_active(user_id, limit=15)
        if not goals:
            await update.message.reply_text(
                "You have no active goals yet. Tell me what you're working on!"
            )
            return
        lines = [f"• *{g['title']}*" + (f" — {g['description']}" if g.get("description") else "")
                 for g in goals]
        await update.message.reply_text(
            f"🎯 *Active goals* ({len(goals)}):\n\n" + "\n".join(lines),
            parse_mode="Markdown",
        )

    async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List your active plans with step progress."""
        if await reject_unauthorized(update):
            return
        if plan_store is None:
            await update.message.reply_text("Plan tracking not available.")
            return
        user_id = update.effective_user.id
        try:
            plans = await plan_store.list_plans(user_id, status="active")
        except Exception as e:
            await update.message.reply_text(f"Could not load plans: {e}")
            return

        if not plans:
            await update.message.reply_text(
                "No active plans. Tell me about a project and I'll help you track it!"
            )
            return

        lines = [f"📋 *Active plans* ({len(plans)}):"]
        lines.append("")

        for plan in plans:
            counts = plan.get("step_counts", {})
            done = counts.get("done", 0)
            in_progress = counts.get("in_progress", 0)
            pending = counts.get("pending", 0)
            blocked = counts.get("blocked", 0)
            total = plan.get("total_steps", 0)

            progress_parts = []
            if done:
                progress_parts.append(f"{done} done")
            if in_progress:
                progress_parts.append(f"{in_progress} in progress")
            if pending:
                progress_parts.append(f"{pending} pending")
            if blocked:
                progress_parts.append(f"{blocked} blocked")
            progress = ", ".join(progress_parts) if progress_parts else "no steps"

            lines.append(f"*{plan['title']}* (ID {plan['id']})")
            lines.append(f"  {total} steps — {progress}")
            lines.append(f"  Last activity: {plan['updated_at'][:10]}")
            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def delete_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete conversation history for privacy."""
        if await reject_unauthorized(update):
            return
        from .base import _task_start_times
        user_id = update.effective_user.id
        thread_id: int | None = getattr(update.message, "message_thread_id", None)
        session_key = SessionManager.get_session_key(user_id, thread_id)
        try:
            await conv_store.delete_session(user_id, session_key)
            _task_start_times.pop(user_id, None)
            await update.message.reply_text(
                "Conversation deleted. Starting fresh — new session begins now."
            )
        except Exception as e:
            logger.error("Failed to delete conversation for user %d: %s", user_id, e)
            await update.message.reply_text(f"Could not delete conversation: {e}")

    async def compact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Summarise and compress conversation history."""
        if await reject_unauthorized(update):
            return
        user_id = update.effective_user.id
        thread_id: int | None = getattr(update.message, "message_thread_id", None)
        session_key = SessionManager.get_session_key(user_id, thread_id)
        turns = await conv_store.get_recent_turns(user_id, session_key, limit=50)

        if not turns:
            await update.message.reply_text("No conversation to compact.")
            return

        if claude_client is None:
            await update.message.reply_text("Compact unavailable — no Claude client.")
            return

        await update.message.reply_text("Summarising conversation…")
        transcript = "\n".join(
            f"{t.role.upper()}: {t.content[:500]}" for t in turns
        )
        summary = await claude_client.complete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Summarise this conversation in 3-5 bullet points, "
                        f"preserving key facts, decisions, and context.\n\n{transcript}"
                    ),
                }
            ],
            system="You are a summarisation assistant. Be concise and factual.",
            max_tokens=512,
        )
        await conv_store.compact(user_id, session_key, summary)
        await update.message.reply_text(f"Conversation compacted.\n\n{summary}")

    async def consolidate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/consolidate — trigger end-of-day memory consolidation manually."""
        if await reject_unauthorized(update):
            return

        sched = scheduler_ref.get("proactive_scheduler") if scheduler_ref else None
        if sched is None:
            await update.message.reply_text("Scheduler not available.")
            return

        thread_id: int | None = getattr(update.message, "message_thread_id", None)
        user_id = update.effective_user.id

        from ..working_message import WorkingMessage
        from ...agents.background import BackgroundTaskRunner

        wm = WorkingMessage(context.bot, update.message.chat_id, thread_id=thread_id)
        await wm.start()

        async def _run_consolidation() -> str:
            result = await sched.run_memory_consolidation_now(user_id)
            if result.get("status") == "error":
                return f"❌ {result.get('message', 'Consolidation failed')}"

            facts = result.get("facts_stored", 0)
            goals = result.get("goals_stored", 0)

            if facts == 0 and goals == 0:
                return (
                    "✅ Memory consolidation complete.\n\n"
                    "No new facts or goals extracted from today's conversations. "
                    "Either nothing worth persisting was discussed, or the information "
                    "was already stored proactively during the conversation."
                )

            lines = ["✅ Memory consolidation complete:\n"]
            if facts > 0:
                lines.append(f"  Facts stored: {facts}")
            if goals > 0:
                lines.append(f"  Goals stored: {goals}")
            lines.append("\nUse /facts or /goals to review what was stored.")
            return "\n".join(lines)

        job_id = await job_store.create(user_id, "consolidate", "") if job_store else None
        runner = BackgroundTaskRunner(
            context.bot, update.message.chat_id,
            job_store=job_store, job_id=job_id,
            working_message=wm,
        )
        asyncio.create_task(runner.run(_run_consolidation(), label="consolidate"))

    return {
        "goals": goals_command,
        "plans": plans_command,
        "delete_conversation": delete_conversation_command,
        "compact": compact_command,
        "consolidate": consolidate_command,
    }
