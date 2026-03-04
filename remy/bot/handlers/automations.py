"""
Automation and task handlers.

Contains handlers for scheduled reminders, task breakdown, and the Board of Directors.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .base import reject_unauthorized
from .callbacks import make_run_again_keyboard
from ..session import SessionManager
from ...utils.telegram_formatting import format_telegram_message

if TYPE_CHECKING:
    from ...agents.subagent_runner import SubagentRunner
    from ...memory.automations import AutomationStore
    from ...memory.background_jobs import BackgroundJobStore
    from ...memory.injector import MemoryInjector
    from ...scheduler.proactive import ProactiveScheduler

logger = logging.getLogger(__name__)


def make_automation_handlers(
    *,
    claude_client=None,
    subagent_runner: "SubagentRunner | None" = None,
    memory_injector: "MemoryInjector | None" = None,
    automation_store: "AutomationStore | None" = None,
    job_store: "BackgroundJobStore | None" = None,
    proactive_scheduler: "ProactiveScheduler | None" = None,
    scheduler_ref: dict | None = None,
):
    """
    Factory that returns automation and task handlers.

    Returns a dict of command_name -> handler_function.
    """

    def _parse_schedule_args(
        args: list[str], default_dow: str = "*"
    ) -> tuple[str, str, bool]:
        """
        Parse optional [day] [HH:MM] and --mediated from a /schedule-* command's args.
        Returns (cron_str, label, mediated). --mediated means Remy composes at fire time.
        """
        remaining = list(args)
        hour = "9"
        minute = "0"
        dow = default_dow
        mediated = "--mediated" in remaining
        if mediated:
            remaining = [a for a in remaining if a != "--mediated"]

        _DOW_MAP = {
            "mon": "1",
            "tue": "2",
            "wed": "3",
            "thu": "4",
            "fri": "5",
            "sat": "6",
            "sun": "0",
        }
        if remaining and remaining[0].lower() in _DOW_MAP:
            dow = _DOW_MAP[remaining.pop(0).lower()]

        if remaining and ":" in remaining[0]:
            parts = remaining.pop(0).split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hour = parts[0].lstrip("0") or "0"
                minute = parts[1].lstrip("0") or "0"

        label = " ".join(remaining).strip()
        cron = f"{minute} {hour} * * {dow}"
        return cron, label, mediated

    async def schedule_daily_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        /schedule-daily [HH:MM] <task>
        Create a daily reminder. HH:MM is optional (defaults to 09:00).
        """
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if automation_store is None or _sched is None:
            await update.message.reply_text(
                "Automation not available — scheduler not configured."
            )
            return

        cron, label, mediated = _parse_schedule_args(context.args or [])
        if not label:
            await update.message.reply_text(
                "Usage: /schedule_daily [HH:MM] [--mediated] <task>\n"
                "Example: /schedule_daily 08:30 review my goals\n"
                "Add --mediated for Remy to compose the message at fire time."
            )
            return

        user_id = update.effective_user.id
        try:
            automation_id = await automation_store.add(
                user_id, label, cron, mediated=mediated
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ Failed to save automation: {exc}")
            return

        _sched.add_automation(automation_id, user_id, label, cron, mediated=mediated)
        minute, hour = cron.split()[0], cron.split()[1]
        time_str = f"{int(hour):02d}:{int(minute):02d}"
        delivery = " (mediated)" if mediated else ""
        await update.message.reply_text(
            f"✅ Daily reminder set (ID {automation_id})\n"
            f"*{label}*\nFires every day at {time_str}{delivery}.",
            parse_mode="Markdown",
        )

    async def schedule_weekly_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        /schedule-weekly [day] [HH:MM] <task>
        Create a weekly reminder. Day defaults to Monday, time to 09:00.
        """
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if automation_store is None or _sched is None:
            await update.message.reply_text(
                "Automation not available — scheduler not configured."
            )
            return

        cron, label, mediated = _parse_schedule_args(
            context.args or [], default_dow="1"
        )
        if not label:
            await update.message.reply_text(
                "Usage: /schedule_weekly [day] [HH:MM] [--mediated] <task>\n"
                "Example: /schedule_weekly fri 09:00 weekly review\n"
                "Add --mediated for Remy to compose the message at fire time."
            )
            return

        user_id = update.effective_user.id
        try:
            automation_id = await automation_store.add(
                user_id, label, cron, mediated=mediated
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ Failed to save automation: {exc}")
            return

        _sched.add_automation(automation_id, user_id, label, cron, mediated=mediated)
        _DOW_NAMES = {
            "0": "Sun",
            "1": "Mon",
            "2": "Tue",
            "3": "Wed",
            "4": "Thu",
            "5": "Fri",
            "6": "Sat",
            "*": "every day",
        }
        minute, hour, _, _, dow = cron.split()
        time_str = f"{int(hour):02d}:{int(minute):02d}"
        day_str = _DOW_NAMES.get(dow, dow)
        delivery = " (mediated)" if mediated else ""
        await update.message.reply_text(
            f"✅ Weekly reminder set (ID {automation_id})\n"
            f"*{label}*\nFires every {day_str} at {time_str}{delivery}.",
            parse_mode="Markdown",
        )

    async def list_automations_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """/list-automations — show scheduled reminders with inline [Run] buttons (US-one-tap-automations)."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        if automation_store is None:
            await update.message.reply_text("Automation not available.")
            return

        user_id = update.effective_user.id
        rows = await automation_store.get_all(user_id)

        if not rows:
            await update.message.reply_text(
                "No automations scheduled.\n"
                "Use /schedule_daily or /schedule_weekly to create one."
            )
            return

        _DOW_NAMES = {
            "0": "Sun",
            "1": "Mon",
            "2": "Tue",
            "3": "Wed",
            "4": "Thu",
            "5": "Fri",
            "6": "Sat",
            "*": "daily",
        }
        lines = ["⏰ *Scheduled reminders:*\n"]
        for row in rows:
            cron = row.get("cron") or ""
            cron_parts = cron.split() if cron else ["0", "9", "*", "*", "*"]
            minute = cron_parts[0] if len(cron_parts) > 0 else "0"
            hour = cron_parts[1] if len(cron_parts) > 1 else "9"
            dow = cron_parts[4] if len(cron_parts) > 4 else "*"
            time_str = f"{int(hour):02d}:{int(minute):02d}"
            freq = "daily" if dow == "*" else f"every {_DOW_NAMES.get(dow, dow)}"
            last = row.get("last_run_at") or "never"
            delivery = "mediated" if row.get("mediated") else "direct"
            lines.append(
                f"*[{row['id']}]* {row['label']}\n  ↳ {freq} at {time_str} | last run: {last} ({delivery})"
            )

        lines.append("\nTap a button to run now. Use /unschedule <id> to remove.")

        # Inline keyboard: one button per automation (label truncated to 32 chars per Telegram limit)
        buttons = [
            [
                InlineKeyboardButton(
                    (r["label"] or "Run")[:32], callback_data=f"run_auto_{r['id']}"
                )
            ]
            for r in rows
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    async def unschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/unschedule <id> — remove a scheduled reminder by its ID."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if automation_store is None or _sched is None:
            await update.message.reply_text("Automation not available.")
            return

        args = context.args or []
        if not args or not args[0].isdigit():
            await update.message.reply_text(
                "Usage: /unschedule <id>\nUse /list_automations to see IDs."
            )
            return

        automation_id = int(args[0])
        user_id = update.effective_user.id

        removed = await automation_store.remove(user_id, automation_id)
        if not removed:
            await update.message.reply_text(
                f"❌ No automation with ID {automation_id} found (or it doesn't belong to you)."
            )
            return

        _sched.remove_automation(automation_id)
        await update.message.reply_text(f"✅ Reminder {automation_id} removed.")

    async def breakdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/breakdown <task> — break a task into 5 clear, actionable steps."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        task = " ".join(context.args or []).strip()
        if not task:
            await update.message.reply_text(
                "Usage: /breakdown <task>\n"
                "Example: /breakdown organise my Projects folder"
            )
            return

        if claude_client is None:
            await update.message.reply_text("Breakdown unavailable — no Claude client.")
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Breaking it down…")

        user_id = update.effective_user.id
        context_block = ""
        if memory_injector is not None:
            try:
                full_prompt = await memory_injector.build_system_prompt(
                    user_id, task, ""
                )
                if "<memory>" in full_prompt:
                    start = full_prompt.index("<memory>")
                    end = full_prompt.index("</memory>") + len("</memory>")
                    context_block = full_prompt[start:end]
            except Exception as exc:
                logger.debug("Breakdown memory injection failed: %s", exc)

        system = (
            "You are an ADHD-friendly task coach. When given a task, break it down into "
            "exactly 5 clear, concrete, actionable steps. Each step should be completable "
            "in under 30 minutes. Number them 1–5. Be specific and encouraging. "
            "After the steps, add one brief motivational sentence."
        )
        if context_block:
            system += f"\n\nUser context:\n{context_block}"

        try:
            response = await claude_client.complete(
                messages=[{"role": "user", "content": f"Break down this task: {task}"}],
                system=system,
                max_tokens=600,
            )
        except Exception as exc:
            logger.error("Breakdown error for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not break down task: {exc}")
            return

        plan_text = response if isinstance(response, str) else str(response)
        await sent.edit_text(
            format_telegram_message(f"📋 *Breaking down:* _{task}_\n\n{plan_text}"),
            parse_mode="MarkdownV2",
        )

    async def board_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/board <topic> — convene the Board of Directors on a topic.

        Validates input, creates job, shows working state, invokes the subagent
        runner, and returns. The runner delivers the result when the subagent
        completes (see US-subagents-next-plan.md).
        """
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        if subagent_runner is None:
            await update.message.reply_text(
                "Board of Directors not available — subagent runner not configured."
            )
            return

        topic = " ".join(context.args or []).strip()
        if not topic:
            await update.message.reply_text(
                "Usage: /board <topic>\n\n"
                "Example: /board What should I focus on this quarter?"
            )
            return

        user_id = update.effective_user.id
        thread_id: int | None = getattr(update.message, "message_thread_id", None)
        session_key = SessionManager.get_session_key(user_id, thread_id)

        user_context = ""
        if memory_injector is not None:
            try:
                full_prompt = await memory_injector.build_system_prompt(
                    user_id, topic, ""
                )
                if "<memory>" in full_prompt:
                    start = full_prompt.index("<memory>")
                    end = full_prompt.index("</memory>") + len("</memory>")
                    user_context = full_prompt[start:end]
            except Exception as exc:
                logger.warning("Board memory injection failed: %s", exc)

        from ..working_message import WorkingMessage
        from ...agents.background import BackgroundTaskRunner

        wm = WorkingMessage(context.bot, update.message.chat_id, thread_id)
        await wm.start()

        job_id = await job_store.create(user_id, "board", topic) if job_store else None
        run_again_markup = make_run_again_keyboard("board", {"topic": topic}, user_id)
        background_runner = BackgroundTaskRunner(
            context.bot,
            update.message.chat_id,
            job_store=job_store,
            job_id=job_id,
            working_message=wm,
            thread_id=thread_id,
            chat_action=ChatAction.UPLOAD_DOCUMENT,
            run_again_markup=run_again_markup,
        )
        try:
            subagent_runner.start_board(
                background_runner,
                topic=topic,
                user_context=user_context,
                user_id=user_id,
                session_key=session_key,
            )
        except RuntimeError as e:
            await wm.stop()
            await update.message.reply_text(str(e))

    return {
        "schedule-daily": schedule_daily_command,
        "schedule-weekly": schedule_weekly_command,
        "list-automations": list_automations_command,
        "unschedule": unschedule_command,
        "breakdown": breakdown_command,
        "board": board_command,
    }
