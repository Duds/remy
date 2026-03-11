"""Incoming webhook endpoint."""

from __future__ import annotations

import logging
import time

from remy.config import get_settings

from ..context import HealthContext

logger = logging.getLogger(__name__)


async def handle_incoming_webhook(
    request: "aiohttp.web.Request", ctx: HealthContext
) -> "aiohttp.web.Response":
    """POST /incoming — third-party webhooks (CI, Zapier). Actions: notify, remind, note."""
    from aiohttp import web  # type: ignore[import]

    settings = get_settings()
    if not (settings.remy_webhook_secret or "").strip():
        return web.json_response(
            {"error": "Incoming webhooks not configured"}, status=404
        )

    secret = (request.headers.get("X-Webhook-Secret") or "").strip()
    if secret != settings.remy_webhook_secret.strip():
        return web.json_response({"error": "Unauthorized"}, status=401)

    peername = request.remote or "unknown"
    now = time.time()
    if peername not in ctx.incoming_webhook_rate:
        ctx.incoming_webhook_rate[peername] = []
    times = ctx.incoming_webhook_rate[peername]
    times.append(now)
    times[:] = [t for t in times if now - t < 60]
    if len(times) > ctx.incoming_webhook_rate_limit:
        return web.json_response(
            {"error": "Rate limit exceeded — try again later"}, status=429
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    action = (body.get("action") or "").strip().lower()
    if action not in ("notify", "remind", "note"):
        return web.json_response(
            {"error": "Missing or invalid 'action'. Use: notify, remind, note"},
            status=400,
        )

    if action == "notify":
        message = (body.get("message") or "").strip()
        if not message:
            return web.json_response(
                {"error": "Missing 'message' for notify"}, status=400
            )
        source = (body.get("source") or "").strip()
        if source:
            message = f"[{source}] {message}"
        get_chat_id = ctx.incoming_get_chat_id
        chat_id = get_chat_id() if get_chat_id else None
        if ctx.incoming_bot is None or chat_id is None:
            return web.json_response(
                {"error": "Bot or primary chat not available"}, status=503
            )
        try:
            await ctx.incoming_bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.warning("Incoming webhook notify failed: %s", e)
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"status": "ok"})

    if action == "remind":
        label = (body.get("label") or "").strip() or "Webhook reminder"
        fire_at = (body.get("fire_at") or "").strip()
        if not fire_at:
            return web.json_response(
                {"error": "Missing 'fire_at' for remind"}, status=400
            )
        user_id = ctx.incoming_webhook_user_id
        store = ctx.incoming_automation_store
        if user_id is None or store is None:
            return web.json_response(
                {"error": "Webhook user or automation store not available"}, status=503
            )
        try:
            await store.add(
                user_id=user_id,
                label=label,
                cron="",
                fire_at=fire_at,
                mediated=False,
            )
        except Exception as e:
            logger.warning("Incoming webhook remind failed: %s", e)
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"status": "ok"})

    if action == "note":
        return web.json_response(
            {"status": "ok", "message": "Note action not yet implemented"}
        )

    return web.json_response({"error": "Unknown action"}, status=400)
