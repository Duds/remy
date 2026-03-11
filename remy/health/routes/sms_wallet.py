"""SMS and Wallet webhook endpoints (US-sms-ingestion, US-google-wallet-monitoring)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from remy.config import get_settings

from ..context import HealthContext

logger = logging.getLogger(__name__)


def _should_notify_sms(sender: str, body: str, allowed_senders: list[str], keyword_filter: list[str]) -> bool:
    """True if this SMS should trigger a Telegram alert per config."""
    if allowed_senders and sender not in allowed_senders:
        return False
    if keyword_filter:
        body_lower = body.lower()
        if not any(kw.lower() in body_lower for kw in keyword_filter):
            return False
    return True


async def handle_sms_webhook(
    request: "aiohttp.web.Request", ctx: HealthContext
) -> "aiohttp.web.Response":
    """POST /webhook/sms — receive SMS from Android SMS Gateway. X-Secret required."""
    from aiohttp import web  # type: ignore[import]

    settings = get_settings()
    if not (settings.sms_webhook_secret or "").strip():
        return web.json_response(
            {"error": "SMS webhook not configured"}, status=404
        )

    secret = (request.headers.get("X-Secret") or "").strip()
    if secret != settings.sms_webhook_secret.strip():
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    sender = (payload.get("from") or payload.get("sender") or "unknown").strip()
    body = (payload.get("message") or payload.get("body") or "").strip()
    ts = (payload.get("receivedAt") or datetime.now(timezone.utc).isoformat()).strip()

    if ctx.sms_store is None:
        logger.warning("SMS webhook: sms_store not configured")
        return web.json_response({"error": "SMS store not available"}, status=503)

    await ctx.sms_store.save(sender, body, ts)

    if ctx.sms_wallet_bot is not None and ctx.sms_wallet_chat_id is not None:
        if _should_notify_sms(
            sender,
            body,
            settings.sms_allowed_senders,
            settings.sms_keyword_filter,
        ):
            preview = body[:200] + ("…" if len(body) > 200 else "")
            try:
                await ctx.sms_wallet_bot.send_message(
                    ctx.sms_wallet_chat_id,
                    f"📱 SMS from {sender}\n\"{preview}\"\nReceived: {ts}",
                )
            except Exception as e:
                logger.warning("SMS Telegram alert failed: %s", e)

    return web.Response(status=204)


async def handle_notification_webhook(
    request: "aiohttp.web.Request", ctx: HealthContext
) -> "aiohttp.web.Response":
    """POST /webhook/notification — Google Wallet (and future) notifications. X-Secret required."""
    from aiohttp import web  # type: ignore[import]

    settings = get_settings()
    if not (settings.sms_webhook_secret or "").strip():
        return web.json_response(
            {"error": "Notification webhook not configured"}, status=404
        )

    secret = (request.headers.get("X-Secret") or "").strip()
    if secret != settings.sms_webhook_secret.strip():
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    source = (data.get("source") or "unknown").strip()
    title = (data.get("title") or "").strip()
    text = (data.get("text") or "").strip()
    subtext = (data.get("subtext") or "").strip()
    ts = (data.get("timestamp") or datetime.now(timezone.utc).isoformat()).strip()

    if source == "google_wallet" and ctx.wallet_handler is not None:
        await ctx.wallet_handler.handle(title, text, subtext, ts)

    return web.Response(status=204)
