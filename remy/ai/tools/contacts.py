"""Contacts tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_search_contacts(registry: ToolRegistry, inp: dict) -> str:
    """Search Google Contacts for a person by name or email."""
    if registry._contacts is None:
        return (
            "Google Contacts not configured. "
            "Run scripts/setup_google_auth.py to set it up."
        )
    query = inp.get("query", "").strip()
    if not query:
        return "Please provide a name or email to search for."

    try:
        results = await registry._contacts.search_contacts(query, max_results=5)
    except Exception as e:
        return f"Could not search contacts: {e}"

    if not results:
        return f"No contacts found matching '{query}'."

    from ...google.contacts import _extract_name
    lines = [f"Contacts matching '{query}':"]
    for person in results:
        name = _extract_name(person) or "(no name)"
        emails = [e["value"] for e in person.get("emailAddresses", [])]
        phones = [p["value"] for p in person.get("phoneNumbers", [])]
        parts = [name]
        if emails:
            parts.append(f"📧 {emails[0]}")
        if phones:
            parts.append(f"📞 {phones[0]}")
        lines.append("• " + " | ".join(parts))
    return "\n".join(lines)


async def exec_upcoming_birthdays(registry: ToolRegistry, inp: dict) -> str:
    """Get upcoming birthdays from Google Contacts."""
    if registry._contacts is None:
        return (
            "Google Contacts not configured. "
            "Run scripts/setup_google_auth.py to set it up."
        )
    days = min(int(inp.get("days", 14)), 90)
    try:
        upcoming = await registry._contacts.get_upcoming_birthdays(days=days)
    except Exception as e:
        return f"Could not fetch birthdays: {e}"

    if not upcoming:
        return f"No birthdays in the next {days} days."

    from ...google.contacts import _extract_name
    lines = [f"Upcoming birthdays (next {days} days):"]
    for bday_date, person in upcoming[:10]:
        name = _extract_name(person) or "Someone"
        lines.append(f"• 🎂 {name} — {bday_date.strftime('%d %b')}")
    return "\n".join(lines)


async def exec_get_contact_details(registry: ToolRegistry, inp: dict) -> str:
    """Get full details for a contact."""
    if registry._contacts is None:
        return "Google Contacts not configured."

    name = inp.get("name", "").strip()
    if not name:
        return "Please provide a contact name."

    try:
        people = await registry._contacts.search_contacts(name, max_results=5)
    except Exception as e:
        return f"Search failed: {e}"

    if not people:
        return f"No contact found matching '{name}'."

    from ...google.contacts import format_contact, _extract_name

    top = people[0]
    resource_name = top.get("resourceName", "")
    try:
        if resource_name:
            top = await registry._contacts.get_contact(resource_name)
    except Exception as e:
        logger.debug("Failed to fetch full contact details: %s", e)

    lines = ["👤 Contact details:\n", format_contact(top, verbose=True)]
    if len(people) > 1:
        others = [_extract_name(p) or "?" for p in people[1:]]
        lines.append(f"\n_Also matched: {', '.join(others)}_")

    return "\n".join(lines)


async def exec_update_contact_note(registry: ToolRegistry, inp: dict) -> str:
    """Add or update a note on a contact in Google Contacts."""
    if registry._contacts is None:
        return "Google Contacts not configured."

    name = inp.get("name", "").strip()
    note = inp.get("note", "").strip()

    if not name:
        return "Please provide a contact name."
    if not note:
        return "Please provide a note to add."

    try:
        people = await registry._contacts.search_contacts(name, max_results=3)
    except Exception as e:
        return f"Search failed: {e}"

    if not people:
        return f"No contact matching '{name}'."

    from ...google.contacts import _extract_name

    person = people[0]
    resource_name = person.get("resourceName", "")
    contact_name = _extract_name(person) or name

    try:
        await registry._contacts.update_note(resource_name, note)
        return f"✅ Note updated for {contact_name}:\n_{note}_"
    except Exception as e:
        return f"Could not update note: {e}"


async def exec_find_sparse_contacts(registry: ToolRegistry) -> str:
    """Find contacts that are missing both email and phone number."""
    if registry._contacts is None:
        return "Google Contacts not configured."

    try:
        sparse = await registry._contacts.get_sparse_contacts(max_results=300)
    except Exception as e:
        return f"Could not scan contacts: {e}"

    if not sparse:
        return "✅ All contacts have at least an email or phone number."

    from ...google.contacts import _extract_name

    lines = [f"🗑 {len(sparse)} contact(s) with no email or phone:\n"]
    for p in sparse[:30]:
        name = _extract_name(p) or "(no name)"
        lines.append(f"• {name}")
    if len(sparse) > 30:
        lines.append(f"…and {len(sparse) - 30} more")
    lines.append("\nUse get_contact_details to review, or delete in Google Contacts.")

    return "\n".join(lines)
