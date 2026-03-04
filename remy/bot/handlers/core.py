"""
Core command handlers.

Contains handlers for basic commands: start, help, cancel, status, setmychat, briefing.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized, _task_start_times
from ..session import SessionManager
from ...config import settings

if TYPE_CHECKING:
    from ...scheduler.proactive import ProactiveScheduler
    from ...ai.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def make_core_handlers(
    *,
    session_manager: SessionManager,
    tool_registry: "ToolRegistry | None" = None,
    proactive_scheduler: "ProactiveScheduler | None" = None,
    scheduler_ref: dict | None = None,
):
    """
    Factory that returns core command handlers.

    Returns a dict of command_name -> handler_function.
    """

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        await update.message.reply_text(
            "Remy online.\n\n"
            "Commands:\n"
            "  /help      — show this list\n"
            "  /cancel    — stop current task\n"
            "  /compact   — summarise and compress conversation\n"
            "  /delete_conversation — delete conversation history for privacy\n"
            "  /status    — check backend status\n"
            "  /goals     — list your active goals\n"
            "  /plans     — list your active plans with step progress\n"
            "  /read <path> — read a text file (Projects/Documents/Downloads)\n"
            "  /write <path> — write text to a file (you'll be prompted for content)\n"
            "  /ls <dir> — list files in a directory\n"
            "  /find <pattern> — search filenames under allowed bases\n"
            "  /set_project <path> — mark current project (stored in memory)\n"
            "  /project_status — show currently tracked project(s)\n"
            "  /scan_downloads — check ~/Downloads for clutter\n"
            "  /organize <path> — Claude suggests how to organise a directory\n"
            "  /clean <path>    — Claude suggests DELETE/ARCHIVE/KEEP per file\n"
            "  /logs      — diagnostics summary (errors + tail)\n"
            "  /logs tail [N] — last N raw log lines (default 30)\n"
            "  /logs errors   — errors and warnings only\n"
            "  /calendar [days] — upcoming calendar events (default 7 days)\n"
            "  /calendar-today  — today's schedule at a glance\n"
            "  /schedule <title> <YYYY-MM-DD> <HH:MM> — create a calendar event\n"
            "  /gmail-unread [N] — show N unread emails (default 5)\n"
            "  /gmail-unread-summary — total count + top senders\n"
            "  /gmail-classify — find promotional/newsletter emails\n"
            "  /gmail-search <query> — search all Gmail (supports from:, subject:, label:, etc.)\n"
            "  /gmail-read <id> — read the full body of an email by ID\n"
            "  /gmail-labels — list all Gmail labels and their IDs\n"
            "  /gmail-create-label <name> — create a label (use Parent/Child for nested)\n"
            "  /gdoc <url-or-id> — read a Google Doc\n"
            "  /gdoc-append <url-or-id> <text> — append text to a Google Doc\n"
            "  /contacts [query] — list or search Google Contacts\n"
            "  /contacts-birthday [days] — upcoming birthdays (default 14 days)\n"
            "  /contacts-details <name> — full contact card\n"
            "  /contacts-note <name> <note> — add/update a note on a contact\n"
            "  /contacts-prune — find contacts missing email + phone\n"
            "  /search <query>  — DuckDuckGo web search\n"
            "  /research <topic> — search + Claude synthesis\n"
            "  /save-url <url> [note] — save a bookmark\n"
            "  /bookmarks [filter] — list saved bookmarks\n"
            "  /grocery-list [add/done/clear] — grocery list (show IDs, done <id>)\n"
            "  /price-check <item> — search for current prices\n"
            "  /briefing  — get your morning briefing now\n"
            "  /relay     — show pending relay inbox from cowork\n"
            "  /setmychat — set this chat for proactive messages\n"
            "  /board <topic> — convene the Board of Directors\n"
            "  /schedule_daily [HH:MM] <task>        — remind me daily\n"
            "  /schedule_weekly [day] [HH:MM] <task> — remind me weekly\n"
            "  /list_automations — show scheduled reminders\n"
            "  /unschedule <id>  — remove a scheduled reminder\n"
            "  /breakdown <task> — break a task into actionable steps\n"
            "  /stats [period]   — usage stats (7d, 30d, 90d, all)\n"
            "  /goal-status      — goal tracking dashboard\n"
            "  /retrospective    — generate monthly retrospective\n"
            "  /consolidate      — extract memories from today's chats\n"
            "  /diagnostics      — comprehensive self-diagnostics\n\n"
            "Send a voice message to transcribe and process it.\n"
            "Just send me a message to get started."
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.effective_user is None:
            return
        await start_command(update, context)

    async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        user_id = update.effective_user.id
        session_manager.request_cancel(user_id)
        _task_start_times.pop(user_id, None)
        await update.message.reply_text("Stopping current task…")

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        if tool_registry is not None:
            status_text = await tool_registry.dispatch(
                "check_status", {}, update.effective_user.id
            )
            await update.message.reply_text(status_text)
        else:
            await update.message.reply_text(
                "Status check not available — tool registry not configured."
            )

    async def setmychat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if update.effective_chat is None:
            return
        chat_id = str(update.effective_chat.id)
        path = settings.primary_chat_file
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            with open(path, "w") as f:
                f.write(chat_id)
            await update.message.reply_text(
                f"This chat is now set for proactive messages. (ID: {chat_id})"
            )
        except OSError as exc:
            await update.message.reply_text(f"Could not save: {exc}")

    async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger the morning briefing right now."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if _sched is None:
            await update.message.reply_text("Proactive scheduler not running.")
            return
        await update.message.reply_text("Sending briefing…")
        await _sched.send_morning_briefing_now()

    async def relay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending relay inbox: unread messages and pending tasks from cowork."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        user_id = update.effective_user.id
        if tool_registry is None:
            await update.message.reply_text(
                "Relay not available — tool registry not configured."
            )
            return
        try:
            msg_result = await tool_registry.dispatch(
                "relay_get_messages",
                {"unread_only": True, "mark_read": False, "limit": 20},
                user_id,
            )
            task_result = await tool_registry.dispatch(
                "relay_get_tasks",
                {"status": "pending", "limit": 20},
                user_id,
            )
        except Exception as exc:
            await update.message.reply_text(f"Relay unavailable — {exc}")
            return

        import json

        parts = []
        try:
            msg_data = json.loads(msg_result)
            messages = msg_data.get("messages") or []
            unread = msg_data.get("unread_count", 0)
            if unread == 0 and not messages:
                task_data = json.loads(task_result)
                tasks = task_data.get("tasks") or []
                pending = task_data.get("pending_count", 0)
                if pending == 0 and not tasks:
                    await update.message.reply_text(
                        "Relay inbox is clear — nothing from cowork."
                    )
                    return
            if messages or unread > 0:
                parts.append(f"📬 *{unread} unread message(s) from cowork:*")
                for m in (messages or [])[:10]:
                    from_agent = m.get("from_agent") or "cowork"
                    content = (m.get("content") or "").strip()[:200]
                    if len((m.get("content") or "")) > 200:
                        content += "…"
                    parts.append(f"• _{from_agent}:_\n{content}")
                if unread > 10:
                    parts.append(f"_…and {unread - 10} more_")
            task_data = json.loads(task_result)
            tasks = task_data.get("tasks") or []
            pending = task_data.get("pending_count", 0)
            if tasks or pending > 0:
                parts.append(f"\n📋 *{pending} pending task(s):*")
                for t in (tasks or [])[:10]:
                    tid = t.get("id") or "?"
                    task_type = t.get("task_type") or "general"
                    desc = (t.get("description") or "")[:150]
                    if len((t.get("description") or "")) > 150:
                        desc += "…"
                    parts.append(f"• `{tid}` — {task_type}: {desc}")
                if pending > 10:
                    parts.append(f"_…and {pending - 10} more_")
            await update.message.reply_text("\n".join(parts))
        except (json.JSONDecodeError, KeyError) as exc:
            await update.message.reply_text(f"Could not read relay — {exc}")

    return {
        "start": start_command,
        "help": help_command,
        "cancel": cancel_command,
        "status": status_command,
        "setmychat": setmychat_command,
        "briefing": briefing_command,
        "relay": relay_command,
    }
