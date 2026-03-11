"""
Core command handlers.

Contains handlers for basic commands: start, help, cancel, status, setmychat, briefing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized, _task_start_times
from ..session import SessionManager

if TYPE_CHECKING:
    from ...scheduler.proactive import ProactiveScheduler
    from ...ai.tools import ToolRegistry

logger = logging.getLogger(__name__)


def make_core_handlers(
    *,
    session_manager: SessionManager,
    tool_registry: "ToolRegistry | None" = None,
    proactive_scheduler: "ProactiveScheduler | None" = None,
    scheduler_ref: dict | None = None,
    automation_store=None,
    counter_store=None,
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

        text = (update.message.text or "").strip()
        if text.startswith("/start "):
            payload = text[len("/start "):].strip()
            if payload.startswith("reminder_"):
                try:
                    automation_id = int(payload[len("reminder_"):])
                except ValueError:
                    pass
                else:
                    user_id = update.effective_user.id
                    chat_id = update.effective_chat.id if update.effective_chat else 0
                    if automation_store is not None:
                        automation = await automation_store.get_for_user(
                            user_id, automation_id
                        )
                        if automation is not None:
                            from .callbacks import (
                                make_reminder_keyboard,
                                store_reminder_payload,
                            )
                            label = automation.get("label") or "Reminder"
                            # Substitute [count] with sobriety_streak for reminder deep links
                            display_label = label
                            if "[count]" in display_label and counter_store is not None:
                                try:
                                    row = await counter_store.get(
                                        user_id, "sobriety_streak"
                                    )
                                    value = row["value"] if row else 0
                                    display_label = display_label.replace(
                                        "[count]", str(value)
                                    )
                                except Exception as e:
                                    logger.debug(
                                        "Could not resolve [count] for deep link: %s",
                                        e,
                                    )
                                    display_label = display_label.replace(
                                        "[count]", "0"
                                    )
                            fire_at = automation.get("fire_at")
                            one_time = bool(fire_at)
                            if fire_at:
                                next_line = f"One-time: {fire_at}"
                            else:
                                next_line = "Recurring"
                            token = store_reminder_payload(
                                user_id=user_id,
                                chat_id=chat_id,
                                label=label,
                                automation_id=automation_id,
                                one_time=one_time,
                            )
                            keyboard = make_reminder_keyboard(token)
                            msg = f"🔔 *{display_label}*\n\nNext: {next_line}\n\nTap below to snooze or mark done."
                            try:
                                await update.message.reply_text(
                                    msg,
                                    reply_markup=keyboard,
                                    parse_mode="Markdown",
                                )
                            except Exception as e:
                                logger.debug("Reminder deep link reply failed: %s", e)
                                await update.message.reply_text(
                                    f"🔔 {display_label}\n\nNext: {next_line}",
                                    reply_markup=keyboard,
                                )
                            return
                    await update.message.reply_text(
                        "Reminder not found or no longer available."
                    )
                    return

        await update.message.reply_text(
            "Remy online. I'm your conversational AI assistant.\n\n"
            "*Commands:*\n"
            "  /help  — show this overview\n"
            "  /cancel  — stop current task\n"
            "  /briefing  — morning briefing now\n"
            "  /status  — backend health\n"
            "  /setmychat  — set proactive message chat\n"
            "  /compact  — compress conversation\n"
            "  /delete_conversation  — clear history\n"
            "  /board <topic>  — Board of Directors analysis\n"
            "  /logs  — diagnostics summary\n"
            "  /stats  — usage stats\n"
            "  /costs  — API cost summary\n"
            "  /diagnostics  — full self-check\n\n"
            "For calendar, email, goals, files, web search, and more — just ask in natural language."
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
        from ...config import save_primary_chat_id

        chat_id = update.effective_chat.id
        try:
            save_primary_chat_id(chat_id)
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

    return {
        "start": start_command,
        "help": help_command,
        "cancel": cancel_command,
        "status": status_command,
        "setmychat": setmychat_command,
        "briefing": briefing_command,
    }
