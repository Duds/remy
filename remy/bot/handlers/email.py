"""
Gmail handlers.

Contains handlers for Gmail operations: reading, searching, classifying, and labelling emails.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized, google_not_configured
from .callbacks import store_pending_archive, make_archive_keyboard
from ...google.gmail import PRIMARY_TABS_LABEL_IDS

if TYPE_CHECKING:
    from ...google.gmail import GmailClient

logger = logging.getLogger(__name__)


def make_email_handlers(
    *,
    google_gmail: "GmailClient | None" = None,
):
    """
    Factory that returns Gmail handlers.

    Returns a dict of command_name -> handler_function.
    """

    async def gmail_unread_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-unread [limit=5] [--tabs|--all] — show unread emails (Inbox by default)."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        args = list(context.args or [])
        use_tabs = "--tabs" in args
        use_all = "--all" in args
        if use_tabs:
            args = [a for a in args if a != "--tabs"]
        if use_all:
            args = [a for a in args if a != "--all"]
        try:
            limit = int(args[0]) if args else 5
            limit = max(1, min(limit, 20))
        except (ValueError, IndexError):
            limit = 5
        if use_all:
            label_ids: list[str | None] | None = cast(list[str | None], [None])
            scope_label = "all mail"
        elif use_tabs:
            label_ids = cast(list[str | None], PRIMARY_TABS_LABEL_IDS)
            scope_label = "Inbox, Promotions, and Updates"
        else:
            label_ids = None
            scope_label = "Inbox"
        await update.message.reply_text("📬 Fetching unread emails…")
        err: Exception | None = None
        try:
            emails = await google_gmail.get_unread(limit=limit, label_ids=label_ids)
        except Exception as exc:
            err = exc
        if err is not None:
            await update.message.reply_text(f"❌ Gmail error: {err}")
            return
        if not emails:
            await update.message.reply_text(f"📬 No unread emails in {scope_label}.")
            return
        lines = [f"📬 *Unread in {scope_label} ({len(emails)} shown):*\n"]
        for i, email in enumerate(emails, 1):
            subject = email["subject"][:80]
            sender = email["from_addr"][:60]
            snippet = email["snippet"][:120].replace("\n", " ")
            lines.append(f"*{i}.* {subject}\n   From: {sender}\n   _{snippet}_\n")
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def gmail_unread_summary_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """/gmail-unread-summary [--tabs|--all] — total unread count and top senders."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        args = list(context.args or [])
        use_tabs = "--tabs" in args
        use_all = "--all" in args
        if use_all:
            label_ids: list[str | None] | None = cast(list[str | None], [None])
            scope_label = "all mail"
        elif use_tabs:
            label_ids = cast(list[str | None], PRIMARY_TABS_LABEL_IDS)
            scope_label = "Inbox, Promotions, and Updates"
        else:
            label_ids = None
            scope_label = "Inbox"
        await update.message.reply_text(f"📬 Checking {scope_label}…")
        err: Exception | None = None
        try:
            summary = await google_gmail.get_unread_summary(label_ids=label_ids)
        except Exception as exc:
            err = exc
        if err is not None:
            await update.message.reply_text(f"❌ Gmail error: {err}")
            return
        count = summary["count"]
        if count == 0:
            await update.message.reply_text(f"📬 No unread emails in {scope_label}.")
            return
        senders = summary["senders"]
        sender_lines = "\n".join(f"  • {s}" for s in senders[:8])
        await update.message.reply_text(
            f"📬 *{count} unread in {scope_label}*\n\nTop senders:\n{sender_lines}",
            parse_mode="Markdown",
        )

    async def gmail_classify_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """/gmail-classify — identify promotional/newsletter emails and offer to archive."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        await update.message.reply_text("🔍 Scanning inbox for promotional emails…")
        err: Exception | None = None
        try:
            promos = await google_gmail.classify_promotional(limit=30)
        except Exception as exc:
            err = exc
        if err is not None:
            await update.message.reply_text(f"❌ Gmail error: {err}")
            return
        if not promos:
            await update.message.reply_text("✅ No promotional emails detected.")
            return
        user_id = update.effective_user.id
        message_ids = [p["id"] for p in promos]
        token = store_pending_archive(user_id, message_ids)
        lines = [f"🗑 *{len(promos)} promotional email(s) found:*\n"]
        for item in promos[:10]:
            lines.append(
                f"• {item['subject'][:80]}\n  _From: {item['from_addr'][:60]}_"
            )
        if len(promos) > 10:
            lines.append(f"…and {len(promos) - 10} more")
        lines.append(f"\nTap [Confirm] to archive all {len(promos)} emails.")
        keyboard = make_archive_keyboard(token)
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    async def gmail_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-search <query> — search all Gmail with Gmail query syntax."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        if not context.args:
            await update.message.reply_text(
                "Usage: `/gmail-search <query>`\n"
                "Examples:\n"
                "  `/gmail-search from:kathryn hockey`\n"
                "  `/gmail-search subject:invoice after:2025/1/1`\n"
                "  `/gmail-search label:ALL_MAIL is:unread`",
                parse_mode="Markdown",
            )
            return
        query = " ".join(context.args)
        await update.message.reply_text(
            f"🔍 Searching for `{query}`…", parse_mode="Markdown"
        )
        err: Exception | None = None
        try:
            emails = await google_gmail.search(query, max_results=10)
        except Exception as exc:
            err = exc
        if err is not None:
            await update.message.reply_text(f"❌ Gmail error: {err}")
            return
        if not emails:
            await update.message.reply_text(f"No emails found for: {query}")
            return
        lines = [f"📬 *{len(emails)} result(s) for* `{query}`:\n"]
        for email in emails:
            mid = email["id"]
            lines.append(
                f"• `{mid}`\n"
                f"  *{email['subject'][:80]}*\n"
                f"  From: {email['from_addr'][:60]}\n"
                f"  {email['date'][:30]}"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

    async def gmail_read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-read <message-id> — read the full body of a specific email."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        if not context.args:
            await update.message.reply_text(
                "Usage: `/gmail-read <message-id>`", parse_mode="Markdown"
            )
            return
        message_id = context.args[0]
        await update.message.reply_text("📖 Fetching email…")
        err: Exception | None = None
        try:
            from ...ai.input_validator import sanitize_memory_injection

            m = await google_gmail.get_message(message_id, include_body=True)
            subj = sanitize_memory_injection(m.get("subject", "(no subject)"))
            sender = sanitize_memory_injection(m.get("from_addr", ""))
            date = m.get("date", "")
            body = sanitize_memory_injection(m.get("body") or m.get("snippet", ""))
            text = f"*{subj}*\nFrom: {sender}\nDate: {date}\n\n{body}"
            if len(text) > 4000:
                text = text[:3990] + "\n\n…_(truncated)_"
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as exc:
            err = exc
            await update.message.reply_text(f"❌ Gmail error: {err}")

    async def gmail_labels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-labels — list all Gmail labels and their IDs."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        err: Exception | None = None
        try:
            labels = await google_gmail.list_labels()
            user_labels = [lb for lb in labels if lb["type"] != "system"]
            sys_labels = [lb for lb in labels if lb["type"] == "system"]
            lines = ["*Gmail Labels*\n"]
            if user_labels:
                lines.append("*Custom:*")
                for lb in sorted(user_labels, key=lambda x: x["name"]):
                    lines.append(f"  `{lb['id']}` — {lb['name']}")
            lines.append("\n*System:*")
            for lb in sorted(sys_labels, key=lambda x: x["name"]):
                lines.append(f"  `{lb['id']}` — {lb['name']}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as exc:
            err = exc
            await update.message.reply_text(f"❌ Gmail error: {err}")

    async def gmail_create_label_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """/gmail-create-label <name> — create a Gmail label (use Parent/Child for nested)."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(google_not_configured("Gmail"))
            return
        if not context.args:
            await update.message.reply_text(
                "Usage: `/gmail_create_label <label name>`\n"
                "Use slash for nested labels, e.g. `4-Personal & Family/Hockey`",
                parse_mode="Markdown",
            )
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.message.reply_text("Please provide a label name.")
            return
        await update.message.reply_text(
            f"🏷 Creating label _{name}_…", parse_mode="Markdown"
        )
        try:
            result = await google_gmail.create_label(name)
            await update.message.reply_text(
                f"✅ Label created: **{result['name']}** (ID: `{result['id']}`)\n"
                "Use label_emails or /gmail-search to apply it to messages.",
                parse_mode="Markdown",
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ Could not create label: {exc}")

    return {
        "gmail-unread": gmail_unread_command,
        "gmail-unread-summary": gmail_unread_summary_command,
        "gmail-classify": gmail_classify_command,
        "gmail-search": gmail_search_command,
        "gmail-read": gmail_read_command,
        "gmail-labels": gmail_labels_command,
        "gmail-create-label": gmail_create_label_command,
    }
