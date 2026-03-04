"""
Callback query handlers for inline keyboard actions.

Central router for Telegram callback_data (Confirm/Cancel, suggested actions, etc.).
Dispatches by prefix: confirm_archive_*, cancel_archive_*, add_to_calendar_*, etc.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from .base import is_allowed

if TYPE_CHECKING:
    from ...google.gmail import GmailClient
    from ...google.calendar import CalendarClient

logger = logging.getLogger(__name__)

# Pending confirmations: token -> {user_id, action, payload, created_at}
# TTL 10 minutes; stale entries cleaned on access
_PENDING_TTL_SECONDS = 600
_pending_confirmations: dict[str, dict] = {}

# Suggested action payloads: token -> {user_id, callback_id, payload, created_at}
_pending_suggested: dict[str, dict] = {}

# Reminder snooze/done payloads: token -> {user_id, automation_id, label, chat_id,
# message_id, one_time, created_at}
_pending_reminders: dict[str, dict] = {}


def _clean_stale() -> None:
    """Remove expired pending confirmations."""
    now = time.time()
    stale = [
        t
        for t, v in _pending_confirmations.items()
        if now - v["created_at"] > _PENDING_TTL_SECONDS
    ]
    for t in stale:
        del _pending_confirmations[t]


def store_pending_archive(user_id: int, message_ids: list[str]) -> str:
    """Store pending archive confirmation. Returns token for callback_data."""
    _clean_stale()
    token = secrets.token_hex(8)
    _pending_confirmations[token] = {
        "user_id": user_id,
        "action": "archive",
        "payload": {"message_ids": message_ids},
        "created_at": time.time(),
    }
    return token


def make_archive_keyboard(token: str) -> InlineKeyboardMarkup:
    """Build [Confirm] [Cancel] inline keyboard for archive flow."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Confirm", callback_data=f"confirm_archive_{token}"
                ),
                InlineKeyboardButton("Cancel", callback_data=f"cancel_archive_{token}"),
            ],
        ]
    )


def _clean_stale_reminders() -> None:
    """Remove expired reminder payloads."""
    now = time.time()
    stale = [
        t
        for t, v in _pending_reminders.items()
        if now - v["created_at"] > _PENDING_TTL_SECONDS
    ]
    for t in stale:
        del _pending_reminders[t]


def store_reminder_payload(
    user_id: int,
    chat_id: int,
    label: str,
    automation_id: int = 0,
    one_time: bool = False,
) -> str:
    """Store reminder context for snooze/done callbacks. Returns token for callback_data."""
    _clean_stale_reminders()
    token = secrets.token_hex(6)  # 12 chars to keep callback_data under 64 bytes
    _pending_reminders[token] = {
        "user_id": user_id,
        "automation_id": automation_id,
        "label": label,
        "chat_id": chat_id,
        "one_time": one_time,
        "created_at": time.time(),
    }
    return token


def make_reminder_keyboard(token: str) -> InlineKeyboardMarkup:
    """Build [Snooze 5m] [Snooze 15m] [Done] inline keyboard for reminder messages."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Snooze 5m", callback_data=f"snooze_5_{token}"),
                InlineKeyboardButton("Snooze 15m", callback_data=f"snooze_15_{token}"),
                InlineKeyboardButton("Done", callback_data=f"done_{token}"),
            ],
        ]
    )


def _clean_stale_suggested() -> None:
    """Remove expired suggested action payloads."""
    now = time.time()
    stale = [
        t
        for t, v in _pending_suggested.items()
        if now - v["created_at"] > _PENDING_TTL_SECONDS
    ]
    for t in stale:
        del _pending_suggested[t]


def store_suggested_payload(user_id: int, callback_id: str, payload: dict) -> str:
    """Store payload for a suggested action. Returns token for callback_data."""
    _clean_stale_suggested()
    token = secrets.token_hex(6)  # 12 chars to keep callback_data under 64 bytes
    _pending_suggested[token] = {
        "user_id": user_id,
        "callback_id": callback_id,
        "payload": payload,
        "created_at": time.time(),
    }
    return token


def make_suggested_actions_keyboard(
    actions: list[dict],
    user_id: int,
) -> InlineKeyboardMarkup | None:
    """
    Build inline keyboard from suggested_actions list.
    Each action: {label, callback_id, payload?}
    Returns None if actions empty or invalid.
    """
    if not actions or len(actions) > 4:
        return None

    buttons = []
    for act in actions:
        label = (act.get("label") or "")[:32]  # Telegram button text limit
        callback_id = act.get("callback_id")
        if not label or not callback_id:
            continue
        if callback_id not in (
            "add_to_calendar",
            "forward_to_cowork",
            "break_down",
            "dismiss",
        ):
            continue

        if callback_id == "dismiss":
            cb_data = "dismiss"
        else:
            payload = act.get("payload") or {}
            token = store_suggested_payload(user_id, callback_id, payload)
            cb_data = f"{callback_id}_{token}"

        if len(cb_data) <= 64:  # Telegram callback_data limit
            buttons.append(InlineKeyboardButton(label, callback_data=cb_data))

    if not buttons:
        return None
    # One row, max 4 buttons
    return InlineKeyboardMarkup([buttons[:4]])


def make_step_limit_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard for step-limit message: [Continue] [Break down] [Stop].
    Used when stream_with_tools hits max_iterations (US-step-limit-buttons).
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Continue", callback_data="step_limit_continue"),
                InlineKeyboardButton("Break down", callback_data="step_limit_break"),
                InlineKeyboardButton("Stop", callback_data="step_limit_stop"),
            ],
        ]
    )


def make_callback_handler(
    *,
    google_gmail: "GmailClient | None" = None,
    google_calendar: "CalendarClient | None" = None,
    relay_post_message=None,
    automation_store=None,
    scheduler_ref: dict | None = None,
    claude_client=None,
    tool_registry=None,
    session_manager=None,
    conv_store=None,
    db=None,
):
    """
    Factory that returns the callback query handler.

    Routes by callback_data prefix: confirm_archive_*, cancel_archive_*,
    add_to_calendar_*, forward_to_cowork_*, break_down_*, dismiss,
    snooze_5_*, snooze_15_*, done_*.
    """

    async def handle_callback(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or update.effective_user is None:
            return

        user_id = update.effective_user.id
        if user_id is None or not is_allowed(user_id):
            await query.answer()
            return

        data = query.data or ""
        await query.answer()

        if data.startswith("confirm_archive_"):
            token = data[len("confirm_archive_") :]
            _clean_stale()
            pending = _pending_confirmations.pop(token, None)
            if pending is None:
                logger.warning(
                    "Callback with unknown/stale archive token: %s", token[:8]
                )
                try:
                    await query.edit_message_text("Expired. Please try again.")
                except Exception as exc:
                    logger.debug("Edit message failed: %s", exc)
                return

            if pending["user_id"] != user_id:
                return

            message_ids = pending["payload"].get("message_ids", [])
            if not message_ids or google_gmail is None:
                try:
                    await query.edit_message_text(
                        "❌ Gmail not configured or no emails to archive."
                    )
                except Exception as exc:
                    logger.debug("Edit message failed: %s", exc)
                return

            try:
                n = await google_gmail.archive_messages(message_ids)
                await query.edit_message_text(f"✅ Archived {n} email(s).")
            except Exception as exc:
                logger.exception("Archive failed: %s", exc)
                try:
                    await query.edit_message_text(f"❌ Archive failed: {exc}")
                except Exception as edit_err:
                    logger.debug("Edit message failed: %s", edit_err)

        elif data.startswith("cancel_archive_"):
            token = data[len("cancel_archive_") :]
            _pending_confirmations.pop(token, None)
            try:
                await query.edit_message_text("Cancelled.")
            except Exception as e:
                logger.debug("Edit message failed: %s", e)

        elif data == "dismiss":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                logger.debug("Edit reply_markup failed: %s", e)

        elif data == "step_limit_continue":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.answer('Send "continue" to pick up where I left off.')
            except Exception as e:
                logger.debug("Step limit continue edit failed: %s", e)

        elif data == "step_limit_break":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.answer(
                    'Send "break this into smaller tasks" or use /breakdown.'
                )
            except Exception as e:
                logger.debug("Step limit break edit failed: %s", e)

        elif data == "step_limit_stop":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.answer()
            except Exception as e:
                logger.debug("Step limit stop edit failed: %s", e)

        elif data.startswith("add_to_calendar_"):
            token = data[len("add_to_calendar_") :]
            _clean_stale_suggested()
            pending = _pending_suggested.pop(token, None)
            if pending is None or pending["user_id"] != user_id:
                await query.answer("Expired.", show_alert=True)
                return
            payload = pending.get("payload") or {}
            title = payload.get("title") or "Event"
            when = payload.get("when") or ""
            if google_calendar and when:
                try:
                    dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                    await google_calendar.create_event(
                        title=title,
                        date_str=date_str,
                        time_str=time_str,
                    )
                    try:
                        await query.edit_message_text(f"✅ Added to calendar: {title}")
                    except Exception:
                        pass
                except Exception as e:
                    logger.exception("Add to calendar failed: %s", e)
                    try:
                        await query.edit_message_text(f"❌ Could not add: {e}")
                    except Exception:
                        pass
            else:
                try:
                    await query.edit_message_text("❌ Calendar not configured.")
                except Exception:
                    pass

        elif data.startswith("forward_to_cowork_"):
            token = data[len("forward_to_cowork_") :]
            _clean_stale_suggested()
            pending = _pending_suggested.pop(token, None)
            if pending is None or pending["user_id"] != user_id:
                await query.answer("Expired.", show_alert=True)
                return
            # Content: payload text, or message the button is attached to
            text = (pending.get("payload") or {}).get("text") if pending else ""
            if not text or not str(text).strip():
                msg = query.message
                text = (
                    getattr(msg, "text", None) or getattr(msg, "caption", None) or ""
                ).strip()
            text = (str(text)[:8000] or "Forwarded note.").strip()
            try:
                if relay_post_message is not None:
                    ok = await relay_post_message(content=text)
                else:
                    from ...config import settings
                    from ...relay import post_message_to_cowork

                    ok = await post_message_to_cowork(
                        content=text,
                        db_path=settings.relay_db_path_resolved,
                    )
                if ok is not None and ok:
                    if isinstance(ok, dict):
                        logger.info(
                            "Forward to cowork: relay message_id=%s",
                            ok.get("message_id"),
                        )
                    try:
                        await query.edit_message_text("✅ Sent to cowork.")
                    except Exception as e:
                        logger.warning(
                            "Forward to cowork: could not edit message to success state: %s",
                            e,
                        )
                else:
                    try:
                        await query.edit_message_text(
                            "❌ Could not send to cowork. Try again later."
                        )
                    except Exception as e:
                        logger.warning(
                            "Forward to cowork: could not edit message to error state: %s",
                            e,
                        )
            except Exception as e:
                logger.warning("Forward to cowork failed: %s", e)
                try:
                    await query.edit_message_text(
                        "❌ Could not send to cowork. Try again later."
                    )
                except Exception as edit_e:
                    logger.warning(
                        "Forward to cowork: could not edit message to error state: %s",
                        edit_e,
                    )

        elif data.startswith("break_down_"):
            token = data[len("break_down_") :]
            _clean_stale_suggested()
            pending = _pending_suggested.pop(token, None)
            if pending is None or pending["user_id"] != user_id:
                await query.answer("Expired.", show_alert=True)
                return
            topic = (pending.get("payload") or {}).get("topic") or "this"
            # Trigger breakdown via a synthetic message — we'd need chat handler access.
            # For now, edit to prompt and suggest /breakdown
            try:
                await query.edit_message_text(
                    f"Use /breakdown {topic} to break it down into steps."
                )
            except Exception:
                pass

        elif data.startswith("snooze_5_"):
            token = data[len("snooze_5_") :]
            _clean_stale_reminders()
            pending = _pending_reminders.pop(token, None)
            if pending is None or pending["user_id"] != user_id:
                await query.answer("Expired.", show_alert=True)
                return
            minutes = 5
            label = pending["label"]
            user_id_p = pending["user_id"]
            if automation_store is None or scheduler_ref is None:
                try:
                    await query.edit_message_text("❌ Snooze not available.")
                except Exception:
                    pass
                return
            from ...config import settings

            tz = ZoneInfo(settings.scheduler_timezone)
            fire_at = datetime.now(tz) + timedelta(minutes=minutes)
            fire_at_str = fire_at.isoformat()
            next_at = fire_at.strftime("%H:%M")
            try:
                new_id = await automation_store.add(
                    user_id_p, label, cron="", fire_at=fire_at_str
                )
                sched = scheduler_ref.get("proactive_scheduler")
                if sched is not None:
                    sched.add_automation(
                        new_id, user_id_p, label, "", fire_at=fire_at_str
                    )
                try:
                    await query.edit_message_text(
                        f"Snoozed — next reminder at {next_at}."
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.exception("Snooze failed: %s", e)
                try:
                    await query.edit_message_text(f"❌ Snooze failed: {e}")
                except Exception:
                    pass

        elif data.startswith("snooze_15_"):
            token = data[len("snooze_15_") :]
            _clean_stale_reminders()
            pending = _pending_reminders.pop(token, None)
            if pending is None or pending["user_id"] != user_id:
                await query.answer("Expired.", show_alert=True)
                return
            minutes = 15
            label = pending["label"]
            user_id_p = pending["user_id"]

            if automation_store is None or scheduler_ref is None:
                try:
                    await query.edit_message_text("❌ Snooze not available.")
                except Exception:
                    pass
                return

            from ...config import settings

            tz = ZoneInfo(settings.scheduler_timezone)
            fire_at = datetime.now(tz) + timedelta(minutes=minutes)
            fire_at_str = fire_at.isoformat()
            next_at = fire_at.strftime("%H:%M")
            try:
                new_id = await automation_store.add(
                    user_id_p, label, cron="", fire_at=fire_at_str
                )
                sched = scheduler_ref.get("proactive_scheduler")
                if sched is not None:
                    sched.add_automation(
                        new_id, user_id_p, label, "", fire_at=fire_at_str
                    )
                try:
                    await query.edit_message_text(
                        f"Snoozed — next reminder at {next_at}."
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.exception("Snooze failed: %s", e)
                try:
                    await query.edit_message_text(f"❌ Snooze failed: {e}")
                except Exception:
                    pass

        elif data.startswith("done_"):
            token = data[len("done_") :]
            _clean_stale_reminders()
            pending = _pending_reminders.pop(token, None)
            if pending is None or pending["user_id"] != user_id:
                await query.answer("Expired.", show_alert=True)
                return
            automation_id = pending.get("automation_id") or 0
            if not pending.get("one_time") and automation_id and automation_store:
                try:
                    await automation_store.update_last_run(automation_id)
                except Exception as e:
                    logger.debug("update_last_run failed: %s", e)
            try:
                await query.edit_message_text("Done ✓")
            except Exception:
                pass

        elif data.startswith("run_auto_"):
            # US-one-tap-automations: run automation on-demand via inline button
            suffix = data[len("run_auto_") :]
            if not suffix.isdigit():
                logger.warning("run_auto_ callback with invalid id: %s", suffix[:20])
                return
            automation_id = int(suffix)
            if (
                automation_store is None
                or claude_client is None
                or tool_registry is None
                or session_manager is None
                or conv_store is None
            ):
                try:
                    await query.edit_message_text("❌ Automation run not available.")
                except Exception:
                    pass
                return
            automation = await automation_store.get_by_id(automation_id)
            if automation is None:
                try:
                    await query.edit_message_text("No longer available.")
                except Exception:
                    pass
                return
            if automation.get("user_id") != user_id:
                return
            label = automation.get("label") or "Reminder"
            chat_id = getattr(query.message, "chat_id", None) if query.message else None
            if chat_id is None:
                return
            try:
                await query.edit_message_text(
                    f"⏰ Running *{label}*…",
                    parse_mode="Markdown",
                    reply_markup=None,
                )
            except Exception as e:
                logger.debug("Edit message for run_auto failed: %s", e)
            try:
                from ..pipeline import run_proactive_trigger

                await run_proactive_trigger(
                    label=label,
                    user_id=user_id,
                    chat_id=chat_id,
                    bot=context.bot,
                    claude_client=claude_client,
                    tool_registry=tool_registry,
                    session_manager=session_manager,
                    conv_store=conv_store,
                    db=db,
                    automation_id=automation_id,
                    one_time=False,
                )
            except Exception as e:
                logger.exception("run_proactive_trigger (on-demand) failed: %s", e)
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Could not run *{label}*: {e}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

        else:
            logger.warning("Unknown callback_data: %s", data[:50])

    return handle_callback
