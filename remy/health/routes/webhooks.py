"""Webhook subscription endpoints."""

from __future__ import annotations

from ..context import HealthContext
from ..utils import check_token


async def handle_webhook_subscribe(
    request: "aiohttp.web.Request", ctx: HealthContext
) -> "aiohttp.web.Response":
    """POST /webhooks/subscribe — register a webhook URL for an event."""
    from aiohttp import web  # type: ignore[import]

    if not check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    if ctx.webhook_manager is None:
        return web.json_response(
            {"error": "Webhook manager not available"}, status=503
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    event = str(body.get("event", "")).strip()
    url = str(body.get("url", "")).strip()
    if not event or not url:
        return web.json_response(
            {"error": "event and url are required"}, status=400
        )

    try:
        sub = await ctx.webhook_manager.subscribe(event, url)
        return web.json_response({"status": "subscribed", "subscription": sub})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_webhook_list(
    request: "aiohttp.web.Request", ctx: HealthContext
) -> "aiohttp.web.Response":
    """GET /webhooks — list all webhook subscriptions."""
    from aiohttp import web  # type: ignore[import]

    if not check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    if ctx.webhook_manager is None:
        return web.json_response(
            {"error": "Webhook manager not available"}, status=503
        )

    event_filter = request.rel_url.query.get("event")
    subs = await ctx.webhook_manager.list_subscriptions(event_filter)
    return web.json_response({"subscriptions": subs, "count": len(subs)})
