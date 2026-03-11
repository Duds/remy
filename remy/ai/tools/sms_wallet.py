"""SMS and Wallet tool executors (US-sms-ingestion, US-google-wallet-monitoring)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry


async def exec_get_sms_messages(
    registry: "ToolRegistry", inp: dict, user_id: int
) -> str:
    """Return recent SMS messages from the webhook store."""
    if registry._sms_store is None:
        return "SMS ingestion is not configured. Set SMS_WEBHOOK_SECRET to enable."
    hours = inp.get("hours", 24)
    try:
        messages = await registry._sms_store.recent(hours=hours)
    except Exception as e:
        return f"Could not fetch SMS messages: {e}"
    if not messages:
        return f"No SMS messages in the last {hours} hours."
    lines = []
    for m in messages:
        body_preview = (m["body"] or "")[:100].replace("\n", " ")
        if len((m["body"] or "")) > 100:
            body_preview += "…"
        lines.append(
            f"From {m['sender']} at {m['received_at']}\n  {body_preview}"
        )
    return "\n\n".join(lines)


async def exec_get_wallet_transactions(
    registry: "ToolRegistry", inp: dict, user_id: int
) -> str:
    """Return recent Google Wallet transactions."""
    if registry._wallet_store is None:
        return (
            "Wallet notifications are not configured. "
            "Set SMS_WEBHOOK_SECRET and Tasker to enable."
        )
    hours = inp.get("hours", 24)
    limit = inp.get("limit", 20)
    try:
        transactions = await registry._wallet_store.recent(hours=hours, limit=limit)
    except Exception as e:
        return f"Could not fetch wallet transactions: {e}"
    if not transactions:
        return f"No Wallet transactions in the last {hours} hours."
    lines = []
    for t in transactions:
        amount = t.get("amount") or "—"
        merchant = (t.get("merchant") or "").strip() or "Unknown"
        ts = t.get("occurred_at", "")
        lines.append(f"{ts[:19]}  {merchant}  {amount}")
    return "\n".join(lines)
