"""Gmail tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from ...ai.input_validator import sanitize_memory_injection
from ...google.gmail import PRIMARY_TABS_LABEL_IDS

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


def _scope_to_label_ids_and_description(
    scope: str,
) -> tuple[list[str | None] | None, str]:
    """Map read_emails scope to (label_ids for GmailClient, human scope description)."""
    scope = (scope or "inbox").strip().lower()
    if scope == "inbox" or not scope:
        return None, "Inbox"
    if scope == "primary_tabs":
        return cast(
            list[str | None], PRIMARY_TABS_LABEL_IDS
        ), "Inbox, Promotions, and Updates"
    if scope == "all_mail":
        return cast(list[str | None], [None]), "all mail"
    return None, "Inbox"


async def exec_read_emails(registry: ToolRegistry, inp: dict) -> str:
    """Fetch unread emails from Gmail, optionally beyond Inbox."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    summary_only = bool(inp.get("summary_only", False))
    limit = min(int(inp.get("limit", 5)), 20)
    label_ids, scope_desc = _scope_to_label_ids_and_description(
        inp.get("scope") or "inbox"
    )

    try:
        if summary_only:
            data = await registry._gmail.get_unread_summary(label_ids=label_ids)
            count = data.get("count", 0)
            senders = data.get("senders", [])
            if not count:
                return f"No unread emails in {scope_desc}."
            sender_str = ", ".join(senders[:5]) if senders else "various"
            return f"Unread in {scope_desc}: {count}\nTop senders: {sender_str}"
        emails = await registry._gmail.get_unread(limit=limit, label_ids=label_ids)
        if not emails:
            return f"No unread emails in {scope_desc}."
        lines = [f"Unread in {scope_desc} ({len(emails)} shown):"]
        for m in emails:
            subj = sanitize_memory_injection(m.get("subject", "(no subject)"))
            sender = sanitize_memory_injection(m.get("from_addr", "unknown"))
            snippet = sanitize_memory_injection((m.get("snippet") or "")[:150])
            lines.append(f"• From: {sender}\n  Subject: {subj}\n  {snippet}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Could not fetch emails: {e}"


async def exec_search_gmail(registry: ToolRegistry, inp: dict) -> str:
    """Search Gmail using standard Gmail query syntax."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    query = str(inp.get("query", "")).strip()
    if not query:
        return "Please provide a search query."
    max_results = min(int(inp.get("max_results", 10)), 20)
    include_body = bool(inp.get("include_body", False))
    label_names: list[str] | None = inp.get("labels")
    label_ids = None
    if label_names:
        try:
            label_ids = await registry._gmail.resolve_label_ids(label_names)
        except ValueError as e:
            return str(e)
    try:
        emails = await registry._gmail.search(
            query,
            max_results=max_results,
            include_body=include_body,
            label_ids=label_ids,
        )
        scope = f" in {', '.join(label_names)}" if label_names else ""
        if not emails:
            return f"No emails found for query: {query}{scope}"
        lines = [f"Search results for '{query}'{scope} ({len(emails)} found):"]
        for m in emails:
            subj = sanitize_memory_injection(m.get("subject", "(no subject)"))
            sender = sanitize_memory_injection(m.get("from_addr", "unknown"))
            date = m.get("date", "")
            mid = m.get("id", "")
            snippet = sanitize_memory_injection((m.get("snippet") or "")[:150])
            entry = (
                f"• [{mid}] {date}\n  From: {sender}\n  Subject: {subj}\n  {snippet}"
            )
            if include_body and m.get("body"):
                body = sanitize_memory_injection(m["body"])
                entry += f"\n\n  [Body]\n{body}"
            lines.append(entry)
        return "\n\n".join(lines)
    except Exception as e:
        return f"Gmail search failed: {e}"


async def exec_read_email(registry: ToolRegistry, inp: dict) -> str:
    """Read a single email in full, including its body."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    message_id = str(inp.get("message_id", "")).strip()
    if not message_id:
        return "Please provide a message_id."
    try:
        m = await registry._gmail.get_message(message_id, include_body=True)
        subj = sanitize_memory_injection(m.get("subject", "(no subject)"))
        sender = sanitize_memory_injection(m.get("from_addr", "unknown"))
        to = sanitize_memory_injection(m.get("to", ""))
        date = m.get("date", "")
        labels = ", ".join(m.get("labels", []))
        body = sanitize_memory_injection(m.get("body", m.get("snippet", "")))
        return (
            f"Email [{message_id}]\n"
            f"From:    {sender}\n"
            f"To:      {to}\n"
            f"Date:    {date}\n"
            f"Subject: {subj}\n"
            f"Labels:  {labels}\n\n"
            f"[Body]\n{body}"
        )
    except Exception as e:
        return f"Could not read email {message_id}: {e}"


async def exec_list_gmail_labels(registry: ToolRegistry, inp: dict) -> str:
    """List all Gmail labels."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    try:
        labels = await registry._gmail.list_labels()
        system = [lb for lb in labels if lb["type"] == "system"]
        user = [lb for lb in labels if lb["type"] != "system"]
        lines = ["Gmail labels:"]
        if system:
            lines.append("\nSystem labels:")
            for lb in sorted(system, key=lambda x: x["name"]):
                lines.append(f"  {lb['id']:20s}  {lb['name']}")
        if user:
            lines.append("\nUser labels:")
            for lb in sorted(user, key=lambda x: x["name"]):
                lines.append(f"  {lb['id']:20s}  {lb['name']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not list labels: {e}"


async def exec_label_emails(registry: ToolRegistry, inp: dict) -> str:
    """Add or remove Gmail labels on one or more messages."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    message_ids = inp.get("message_ids", [])
    add_labels = inp.get("add_labels", [])
    remove_labels = inp.get("remove_labels", [])
    if not message_ids:
        return "Please provide message_ids."
    if not add_labels and not remove_labels:
        return "Please provide add_labels or remove_labels (or both)."
    try:
        count = await registry._gmail.modify_labels(
            message_ids,
            add_label_ids=add_labels or None,
            remove_label_ids=remove_labels or None,
        )
        parts = []
        if add_labels:
            parts.append(f"added {add_labels}")
        if remove_labels:
            parts.append(f"removed {remove_labels}")
        return f"Updated {count} message(s): {', '.join(parts)}."
    except Exception as e:
        return f"Label update failed: {e}"


async def exec_create_gmail_label(registry: ToolRegistry, inp: dict) -> str:
    """Create a new Gmail label."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    name = inp.get("name", "").strip()
    if not name:
        return "Please provide a label name."
    try:
        result = await registry._gmail.create_label(name)
        return (
            f"✅ Label created: **{result['name']}** (ID: `{result['id']}`)\n"
            f"Use label_emails with this ID to apply it to messages."
        )
    except Exception as e:
        return f"Could not create label: {e}"


async def exec_create_email_draft(registry: ToolRegistry, inp: dict) -> str:
    """Compose an email and save it to Gmail Drafts."""
    if registry._gmail is None:
        return "Gmail not configured. Run scripts/setup_google_auth.py to set it up."
    to = str(inp.get("to", "")).strip()
    subject = str(inp.get("subject", "")).strip()
    body = str(inp.get("body", "")).strip()
    cc = str(inp.get("cc", "")).strip() or None
    if not to or not subject or not body:
        return "Draft requires 'to', 'subject', and 'body'."
    try:
        result = await registry._gmail.create_draft(
            to=to, subject=subject, body=body, cc=cc
        )
        return (
            f"✅ Draft saved to Gmail Drafts.\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"Draft ID: {result['id']}\n"
            f"Open Gmail to review and send."
        )
    except Exception as e:
        return f"Could not create draft: {e}"


async def exec_classify_promotional_emails(registry: ToolRegistry, inp: dict) -> str:
    """Find promotional and newsletter emails in the inbox."""
    if registry._gmail is None:
        return "Gmail not configured."

    limit = min(int(inp.get("limit", 30)), 100)

    err: Exception | None = None
    try:
        promos = await registry._gmail.classify_promotional(limit=limit)
    except Exception as e:
        err = e
    if err is not None:
        return f"Gmail error: {err}"

    if not promos:
        return "✅ No promotional emails detected."

    lines = [f"🗑 {len(promos)} promotional email(s) found:\n"]
    for item in promos[:10]:
        lines.append(f"• {item['subject'][:80]}\n  _From: {item['from_addr'][:60]}_")
    if len(promos) > 10:
        lines.append(f"…and {len(promos) - 10} more")
    lines.append(
        "\nTo archive these, use the /gmail_classify command which offers a confirmation prompt."
    )

    return "\n".join(lines)
