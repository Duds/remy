"""Dashboard endpoints (login, auth, stats)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from remy.config import get_settings

from ..context import HealthContext
from ..utils import check_token

logger = logging.getLogger(__name__)


def _verify_telegram_login_widget(payload: dict, bot_token: str) -> bool:
    """Verify Telegram Login Widget hash. Returns True if valid."""
    received_hash = payload.get("hash")
    if not received_hash or not bot_token:
        return False
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(payload.items()) if k != "hash"
    )
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return False
    try:
        auth_date = int(payload.get("auth_date", 0))
        if abs(time.time() - auth_date) > 300:
            return False
    except (TypeError, ValueError):
        return False
    return True


async def handle_dashboard(request) -> "aiohttp.web.Response":
    """GET /dashboard — login page with Telegram Login Widget."""
    from aiohttp import web  # type: ignore[import]

    settings = get_settings()
    bot_username = (settings.telegram_bot_username or "").strip()
    if not bot_username:
        return web.json_response(
            {"error": "Dashboard not configured (set TELEGRAM_BOT_USERNAME)"},
            status=404,
        )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Remy Dashboard</title></head>
<body>
  <h1>Remy Dashboard</h1>
  <p>Sign in with Telegram to view stats.</p>
  <script async src="https://telegram.org/js/telegram-widget.js?22"
    data-telegram-login="{bot_username}"
    data-size="large"
    data-auth-url="/dashboard/auth"
    data-request-access="write"></script>
</body></html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_dashboard_auth(request) -> "aiohttp.web.Response":
    """GET /dashboard/auth — verify Telegram widget and set session cookie."""
    from aiohttp import web  # type: ignore[import]

    settings = get_settings()
    payload = dict(request.rel_url.query)
    if not _verify_telegram_login_widget(payload, settings.telegram_bot_token):
        return web.json_response({"error": "Invalid or expired login"}, status=401)
    user_id = payload.get("id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid user id"}, status=400)
    allowed = getattr(settings, "telegram_allowed_users", None) or []
    if user_id not in allowed:
        return web.json_response({"error": "Access denied"}, status=403)
    expiry = int(time.time()) + 3600
    secret = (
        settings.health_api_token or settings.remy_webhook_secret or "remy-dashboard"
    ).encode()
    msg = f"{user_id}:{expiry}"
    sig = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()[:16]
    cookie_val = f"{msg}:{sig}"
    response = web.Response(status=302, headers={"Location": "/dashboard/stats"})
    response.set_cookie(
        "remy_dash",
        cookie_val,
        max_age=3600,
        httponly=True,
        samesite="Lax",
    )
    return response


async def handle_dashboard_stats(
    request: "aiohttp.web.Request", ctx: HealthContext
) -> "aiohttp.web.Response":
    """GET /dashboard/stats — require session, show stats."""
    from aiohttp import web  # type: ignore[import]

    settings = get_settings()
    cookie_val = request.cookies.get("remy_dash")
    if not cookie_val or ":" not in cookie_val:
        return web.Response(status=302, headers={"Location": "/dashboard"})
    parts = cookie_val.rsplit(":", 1)
    if len(parts) != 2:
        return web.Response(status=302, headers={"Location": "/dashboard"})
    msg, sig = parts[0], parts[1]
    secret = (
        settings.health_api_token or settings.remy_webhook_secret or "remy-dashboard"
    ).encode()
    expected = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return web.Response(status=302, headers={"Location": "/dashboard"})
    try:
        user_id_s, expiry_s = msg.split(":", 1)
        if int(expiry_s) < time.time():
            return web.Response(status=302, headers={"Location": "/dashboard"})
    except (ValueError, TypeError):
        return web.Response(status=302, headers={"Location": "/dashboard"})
    if ctx.db is None:
        return web.Response(text="Stats not available (DB not wired).", status=503)
    try:
        async with ctx.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM api_calls WHERE user_id = ?",
                (int(user_id_s),),
            )
            row = await cursor.fetchone()
        count = row[0] if row else 0
    except Exception as e:
        logger.warning("Dashboard stats query failed: %s", e)
        count = 0
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Remy Stats</title></head>
<body>
  <h1>Remy Dashboard</h1>
  <p>API calls (you): {count}</p>
  <p><a href="/dashboard">Back to login</a></p>
</body></html>"""
    return web.Response(text=html, content_type="text/html")
