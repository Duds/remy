"""
Admin and analytics handlers.

Contains handlers for diagnostics, stats, logs, costs, jobs, and system administration.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from .base import reject_unauthorized
from ...config import settings
from ...diagnostics import get_error_summary, get_recent_logs

if TYPE_CHECKING:
    from ...analytics.analyzer import ConversationAnalyzer
    from ...memory.background_jobs import BackgroundJobStore
    from ...memory.database import DatabaseManager
    from ...diagnostics import DiagnosticsRunner

logger = logging.getLogger(__name__)


def make_admin_handlers(
    *,
    db: "DatabaseManager | None" = None,
    claude_client=None,
    conversation_analyzer: "ConversationAnalyzer | None" = None,
    job_store: "BackgroundJobStore | None" = None,
    diagnostics_runner: "DiagnosticsRunner | None" = None,
    scheduler_ref: dict | None = None,
    admin_client=None,
):
    """
    Factory that returns admin and analytics handlers.

    Returns a dict of command_name -> handler_function.
    """

    async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /logs          — recent errors and warnings summary
        /logs tail     — last 30 raw log lines
        /logs tail N   — last N raw log lines (max 100)
        /logs errors   — errors only
        """
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        args = context.args or []
        subcommand = args[0].lower() if args else "summary"

        if subcommand == "tail":
            try:
                n = min(int(args[1]), 100) if len(args) > 1 else 30
            except ValueError:
                n = 30
            raw = get_recent_logs(settings.logs_dir, lines=n)
            if len(raw) > 3800:
                raw = "…(truncated)\n" + raw[-3800:]
            await update.message.reply_text(
                f"📄 *Last {n} log lines:*\n\n```\n{raw}\n```",
                parse_mode="Markdown",
            )

        elif subcommand == "errors":
            summary = get_error_summary(settings.logs_dir, max_items=10)
            await update.message.reply_text(
                f"🔍 *Error summary:*\n\n{summary}",
                parse_mode="Markdown",
            )

        else:
            summary = get_error_summary(settings.logs_dir, max_items=5)
            tail = get_recent_logs(settings.logs_dir, lines=10)
            if len(tail) > 1500:
                tail = "…(truncated)\n" + tail[-1500:]
            await update.message.reply_text(
                f"🩺 *Diagnostics*\n\n{summary}\n\n"
                f"*Recent log tail:*\n```\n{tail}\n```\n\n"
                f"_/logs tail — full tail  |  /logs errors — errors only_",
                parse_mode="Markdown",
            )

    async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/stats [period] — conversation usage statistics."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if conversation_analyzer is None:
            await update.message.reply_text("Analytics not available.")
            return

        args = context.args or []
        period = args[0].lower() if args else "30d"
        valid_periods = {"7d", "30d", "90d", "all", "month"}
        if period not in valid_periods and not (
            period.endswith("d") and period[:-1].isdigit()
        ):
            await update.message.reply_text(
                "Usage: /stats [period]\nValid periods: 7d, 30d (default), 90d, all"
            )
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Calculating stats…")
        try:
            stats = await conversation_analyzer.get_stats(user_id, period)
            msg = conversation_analyzer.format_stats_message(stats)
            await sent.edit_text(msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Stats command failed for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not calculate stats: {exc}")

    async def costs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/costs [period] — estimated AI costs by provider and model."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if db is None:
            await update.message.reply_text("Analytics not available.")
            return

        from ...analytics.costs import CostAnalyzer

        args = context.args or []
        period = args[0].lower() if args else "30d"
        valid_periods = {"7d", "30d", "90d", "all", "month"}
        if period not in valid_periods and not (
            period.endswith("d") and period[:-1].isdigit()
        ):
            await update.message.reply_text(
                "Usage: /costs [period]\nValid periods: 7d, 30d (default), 90d, all"
            )
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Calculating costs…")
        try:
            cost_analyzer = CostAnalyzer(db)
            summary = await cost_analyzer.get_cost_summary(
                user_id, period, admin_client=admin_client
            )
            msg = cost_analyzer.format_cost_message(summary)
            await sent.edit_text(msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Costs command failed for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not calculate costs: {exc}")

    async def routing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/routing [period] — routing breakdown by category, classifier overhead, fallback rate."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if db is None:
            await update.message.reply_text("Analytics not available.")
            return

        from ...analytics.routing import RoutingAnalyzer

        args = context.args or []
        period = args[0].lower() if args else "30d"
        valid_periods = {"7d", "30d", "90d", "all", "month"}
        if period not in valid_periods and not (
            period.endswith("d") and period[:-1].isdigit()
        ):
            await update.message.reply_text(
                "Usage: /routing [period]\nValid periods: 7d, 30d (default), 90d, all"
            )
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Calculating routing…")
        try:
            routing_analyzer = RoutingAnalyzer(db)
            report = await routing_analyzer.get_routing_report(user_id, period)
            msg = routing_analyzer.format_routing_message(report)
            await sent.edit_text(msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Routing command failed for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not calculate routing: {exc}")

    async def goal_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/goal-status — goal tracking dashboard with age and staleness info."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if conversation_analyzer is None:
            await update.message.reply_text("Analytics not available.")
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Loading goal status…")
        try:
            active = await conversation_analyzer.get_active_goals_with_age(user_id)
            since = datetime.now(timezone.utc) - timedelta(days=30)
            completed = await conversation_analyzer.get_completed_goals_since(
                user_id, since
            )
            msg = conversation_analyzer.format_goal_status_message(active, completed)
            await sent.edit_text(msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Goal status command failed for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not load goal status: {exc}")

    async def retrospective_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/retrospective — generate a monthly retrospective using Claude."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if conversation_analyzer is None:
            await update.message.reply_text("Analytics not available.")
            return
        if claude_client is None:
            await update.message.reply_text("Claude client not available.")
            return

        user_id = update.effective_user.id
        thread_id: int | None = getattr(update.message, "message_thread_id", None)

        from ..working_message import WorkingMessage
        from ...agents.background import BackgroundTaskRunner

        wm = WorkingMessage(context.bot, update.message.chat_id, thread_id)
        await wm.start()

        async def _run_retrospective() -> str:
            return await conversation_analyzer.generate_retrospective(
                user_id, "month", claude_client
            )

        job_id = (
            await job_store.create(user_id, "retrospective", "") if job_store else None
        )
        runner = BackgroundTaskRunner(
            context.bot,
            update.message.chat_id,
            job_store=job_store,
            job_id=job_id,
            working_message=wm,
            thread_id=thread_id,
            chat_action=ChatAction.UPLOAD_DOCUMENT,
        )
        asyncio.create_task(runner.run(_run_retrospective(), label="retrospective"))

    async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/jobs — list recent background jobs with status and result snippets."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if job_store is None:
            await update.message.reply_text("Job tracking not available.")
            return

        user_id = update.effective_user.id
        jobs = await job_store.list_recent(user_id, limit=10)

        if not jobs:
            await update.message.reply_text("No background jobs yet.")
            return

        _STATUS_EMOJI = {"queued": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}
        lines = ["📋 *Recent background jobs:*\n"]
        for job in jobs:
            emoji = _STATUS_EMOJI.get(job["status"], "❓")
            started = job["created_at"][:16].replace("T", " ")
            snippet = ""
            if job["result_text"]:
                preview = job["result_text"][:80].replace("\n", " ")
                snippet = f"\n  _{preview}…_"
            lines.append(
                f"`#{job['id']}` {job['job_type']:14} {emoji} `{job['status']}`  {started}{snippet}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def reindex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/reindex — trigger file reindexing for home directory RAG."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        sched = scheduler_ref.get("proactive_scheduler") if scheduler_ref else None
        if sched is None:
            await update.message.reply_text("Scheduler not available.")
            return

        thread_id: int | None = getattr(update.message, "message_thread_id", None)

        from ..working_message import WorkingMessage
        from ...agents.background import BackgroundTaskRunner

        wm = WorkingMessage(context.bot, update.message.chat_id, thread_id)
        await wm.start()

        async def _run_reindex() -> str:
            stats = await sched.run_file_reindex_now()
            if stats.get("status") == "error":
                return f"❌ {stats.get('message', 'Reindex failed')}"
            if stats.get("status") == "disabled":
                return "File indexing is disabled in configuration."
            return (
                f"✅ File reindex complete:\n"
                f"  Files indexed: {stats.get('files_indexed', 0)}\n"
                f"  Chunks created: {stats.get('chunks_created', 0)}\n"
                f"  Files removed: {stats.get('files_removed', 0)}\n"
                f"  Files skipped: {stats.get('files_skipped', 0)}\n"
                f"  Errors: {stats.get('errors', 0)}"
            )

        job_id = (
            await job_store.create(update.effective_user.id, "reindex", "")
            if job_store
            else None
        )
        runner = BackgroundTaskRunner(
            context.bot,
            update.message.chat_id,
            job_store=job_store,
            job_id=job_id,
            working_message=wm,
            thread_id=thread_id,
            chat_action=ChatAction.UPLOAD_DOCUMENT,
        )
        asyncio.create_task(runner.run(_run_reindex(), label="reindex"))

    async def diagnostics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Run comprehensive self-diagnostics."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        await _run_diagnostics(update, diagnostics_runner, scheduler_ref)

    return {
        "logs": logs_command,
        "stats": stats_command,
        "costs": costs_command,
        "routing": routing_command,
        "goal-status": goal_status_command,
        "retrospective": retrospective_command,
        "jobs": jobs_command,
        "reindex": reindex_command,
        "diagnostics": diagnostics_command,
    }


async def _run_diagnostics(
    update: Update,
    diagnostics_runner: "DiagnosticsRunner | None" = None,
    scheduler_ref: dict | None = None,
) -> None:
    """Run comprehensive self-diagnostics and send results to user."""
    from ...diagnostics import format_diagnostics_output

    if update.message is None or update.effective_user is None:
        return
    await update.message.chat.send_action(ChatAction.TYPING)

    if diagnostics_runner is None:
        await update.message.reply_text("Diagnostics runner not available.")
        return

    try:
        result = await diagnostics_runner.run_all()
        output = format_diagnostics_output(result, settings.scheduler_timezone)

        logger.info(
            "Diagnostics complete: %s (%d checks, %.0fms)",
            result.overall_status.value,
            len(result.checks),
            result.total_duration_ms,
        )

        if len(output) > 4000:
            output = output[:4000] + "\n\n_(truncated)_"

        await update.message.reply_text(output, parse_mode="Markdown")

    except Exception as exc:
        logger.exception("Diagnostics failed")
        await update.message.reply_text(
            f"❌ Diagnostics failed: {type(exc).__name__}: {exc}"
        )
