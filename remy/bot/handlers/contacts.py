"""
Google Contacts handlers.

Contains handlers for contacts operations: listing, searching, birthdays, and notes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized, google_not_configured

if TYPE_CHECKING:
    from ...google.contacts import ContactsClient

logger = logging.getLogger(__name__)


def make_contacts_handlers(
    *,
    google_contacts: "ContactsClient | None" = None,
):
    """
    Factory that returns Google Contacts handlers.
    
    Returns a dict of command_name -> handler_function.
    """

    async def contacts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts [query] — list all contacts or search by name/email."""
        if await reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(google_not_configured("Contacts"))
            return
        query = " ".join(context.args).strip() if context.args else ""
        if query:
            await update.message.reply_text(f"🔍 Searching contacts for _{query}_…", parse_mode="Markdown")
            try:
                people = await google_contacts.search_contacts(query, max_results=10)
            except Exception as e:
                await update.message.reply_text(f"❌ Contacts search failed: {e}")
                return
            if not people:
                await update.message.reply_text(f"No contacts matching _{query}_.", parse_mode="Markdown")
                return
        else:
            await update.message.reply_text("📋 Fetching contacts…")
            try:
                people = await google_contacts.list_contacts(max_results=50)
            except Exception as e:
                await update.message.reply_text(f"❌ Could not fetch contacts: {e}")
                return
            if not people:
                await update.message.reply_text("No contacts found.")
                return

        from ...google.contacts import format_contact
        lines = [f"👥 *{len(people)} contact(s):*\n"]
        for p in people[:20]:
            lines.append(format_contact(p))
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def contacts_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-birthday [days=14] — upcoming birthdays."""
        if await reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(google_not_configured("Contacts"))
            return
        try:
            days = int(context.args[0]) if context.args else 14
            days = max(1, min(days, 90))
        except (ValueError, IndexError):
            days = 14
        await update.message.reply_text(f"🎂 Checking birthdays in the next {days} days…")
        try:
            upcoming = await google_contacts.get_upcoming_birthdays(days=days)
        except Exception as e:
            await update.message.reply_text(f"❌ Could not fetch birthdays: {e}")
            return
        if not upcoming:
            await update.message.reply_text(f"🎂 No birthdays in the next {days} days.")
            return
        from ...google.contacts import _extract_name
        lines = [f"🎂 *Upcoming birthdays (next {days} days):*\n"]
        for bday_date, person in upcoming:
            name = _extract_name(person) or "(unknown)"
            yr = f" {bday_date.year}" if bday_date.year != 1900 else ""
            lines.append(f"• *{name}* — {bday_date.strftime('%d %b')}{yr}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def contacts_details_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-details <name> — full details for a contact."""
        if await reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(google_not_configured("Contacts"))
            return
        if not context.args:
            await update.message.reply_text("Usage: /contacts-details <name>")
            return
        query = " ".join(context.args)
        try:
            people = await google_contacts.search_contacts(query, max_results=5)
        except Exception as e:
            await update.message.reply_text(f"❌ Search failed: {e}")
            return
        if not people:
            await update.message.reply_text(f"No contact found matching _{query}_.", parse_mode="Markdown")
            return
        from ...google.contacts import format_contact, _extract_name
        top = people[0]
        resource_name = top.get("resourceName", "")
        try:
            if resource_name:
                top = await google_contacts.get_contact(resource_name)
        except Exception as e:
            logger.debug("Failed to fetch full contact details, using search result: %s", e)
        lines = [f"👤 *Contact details:*\n", format_contact(top, verbose=True)]
        if len(people) > 1:
            others = [_extract_name(p) or "?" for p in people[1:]]
            lines.append(f"\n_Also matched: {', '.join(others)}_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def contacts_note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-note <name> <note> — add/update a note on a contact."""
        if await reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(google_not_configured("Contacts"))
            return
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /contacts-note <name> <note text>")
            return
        name_query = context.args[0]
        note_text = " ".join(context.args[1:])
        try:
            people = await google_contacts.search_contacts(name_query, max_results=3)
        except Exception as e:
            await update.message.reply_text(f"❌ Search failed: {e}")
            return
        if not people:
            await update.message.reply_text(
                f"No contact matching _{name_query}_.\n"
                "Usage: /contacts-note <first-name> <note text>",
                parse_mode="Markdown",
            )
            return
        from ...google.contacts import _extract_name
        person = people[0]
        resource_name = person.get("resourceName", "")
        name = _extract_name(person) or name_query
        try:
            await google_contacts.update_note(resource_name, note_text)
            await update.message.reply_text(
                f"✅ Note updated for *{name}*:\n_{note_text}_",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Could not update note: {e}")

    async def contacts_prune_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-prune — list contacts with no email and no phone (candidates for deletion)."""
        if await reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(google_not_configured("Contacts"))
            return
        await update.message.reply_text("🔍 Scanning for sparse contacts…")
        try:
            sparse = await google_contacts.get_sparse_contacts(max_results=300)
        except Exception as e:
            await update.message.reply_text(f"❌ Could not scan contacts: {e}")
            return
        if not sparse:
            await update.message.reply_text("✅ All contacts have at least an email or phone number.")
            return
        from ...google.contacts import _extract_name
        lines = [f"🗑 *{len(sparse)} contact(s) with no email or phone:*\n"]
        for p in sparse[:30]:
            name = _extract_name(p) or "(no name)"
            lines.append(f"• {name}")
        if len(sparse) > 30:
            lines.append(f"…and {len(sparse) - 30} more")
        lines.append("\n_Use /contacts-details <name> to review, or delete in Google Contacts._")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    return {
        "contacts": contacts_command,
        "contacts-birthday": contacts_birthday_command,
        "contacts-details": contacts_details_command,
        "contacts-note": contacts_note_command,
        "contacts-prune": contacts_prune_command,
    }
