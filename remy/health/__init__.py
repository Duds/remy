"""Lightweight HTTP health check server with Prometheus metrics.

Runs an aiohttp server on HEALTH_PORT (default 8080) alongside the Telegram bot
in the same asyncio event loop. Used by:
  - Docker HEALTHCHECK
  - Azure Container Instances liveness/readiness probes
  - Local `make status` checks
  - Prometheus scraping

Endpoints:
  GET /            → 200 {"service": "remy", "version": "1.0"}
  GET /health      → 200 {"status": "ok", "uptime_s": N}
  GET /ready       → 200 {"status": "ready"} or 503 {"status": "starting"}
  GET /metrics     → Prometheus metrics in text format
  GET /diagnostics → 200 Comprehensive system diagnostics (JSON)
  GET /logs        → Recent log lines (plain text). Auth required if HEALTH_API_TOKEN set.
  GET /telemetry   → JSON summary of API call stats. Auth required if HEALTH_API_TOKEN set.
  GET /files       → Stream a file by path. Requires path= and token= (signed).
  POST /commands/ship-it → Run SHIP-IT pipeline. Auth required.
  POST /incoming         → Third-party webhooks (CI, Zapier). X-Webhook-Secret required.
  GET /dashboard         → Login page with Telegram Login Widget
  GET /dashboard/auth    → Verify Telegram widget, set session cookie
  GET /dashboard/stats   → Stats page (requires session)
  POST /webhooks/subscribe → Register webhook URL. Auth required.
  GET  /webhooks           → List webhook subscriptions. Auth required.
"""

from __future__ import annotations

import asyncio
import logging
import os
import warnings

from .context import HealthContext
from .routes import commands, dashboard, diagnostics, files, incoming, metrics, sms_wallet, webhooks
from .routes.core import handle_health, handle_ready, handle_root
from .utils import get_start_time

logger = logging.getLogger(__name__)

# Stored context for run_health_server (used by bound handlers)
_ctx: HealthContext | None = None


def set_ready() -> None:
    """Call this once the database and scheduler are initialised.

    Deprecated: Prefer calling ctx.set_ready() on the HealthContext
    passed to run_health_server.
    """
    global _ctx
    if _ctx is not None:
        _ctx.set_ready()
        logger.info("Health server: marked ready")
    else:
        warnings.warn(
            "set_ready() called but no HealthContext was passed to run_health_server. "
            "Pass ctx to run_health_server and call ctx.set_ready() instead.",
            DeprecationWarning,
            stacklevel=2,
        )


async def run_health_server(
    port: int | None = None, ctx: HealthContext | None = None
) -> None:
    """
    Start the aiohttp health server on the given port.
    Runs until cancelled. Call with asyncio.create_task().

    Args:
        port: Port to listen on (default: HEALTH_PORT env or 8080)
        ctx: HealthContext with dependencies. If None, uses empty context
             (endpoints that need deps will return 503).
    """
    global _ctx
    _ctx = ctx or HealthContext()

    try:
        from aiohttp import web  # type: ignore[import]
    except ImportError:
        logger.warning(
            "aiohttp not installed — health endpoint disabled. "
            "Add 'aiohttp' to requirements.txt to enable it."
        )
        return

    _port = port or int(os.environ.get("HEALTH_PORT", "8080"))

    try:
        from .analytics.metrics import set_service_info

        environment = "azure" if os.environ.get("AZURE_ENVIRONMENT") else "local"
        set_service_info(version="1.0", environment=environment)
    except ImportError:
        pass

    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ready", lambda r: handle_ready(r, _ctx))
    app.router.add_get("/metrics", metrics.handle_metrics)
    app.router.add_get("/diagnostics", lambda r: diagnostics.handle_diagnostics(r, _ctx))
    app.router.add_get("/logs", lambda r: diagnostics.handle_logs(r, _ctx))
    app.router.add_get("/telemetry", lambda r: diagnostics.handle_telemetry(r, _ctx))
    app.router.add_get("/files", files.handle_files)
    app.router.add_post("/commands/ship-it", commands.handle_ship_it)
    app.router.add_post("/incoming", lambda r: incoming.handle_incoming_webhook(r, _ctx))
    app.router.add_post("/webhook/sms", lambda r: sms_wallet.handle_sms_webhook(r, _ctx))
    app.router.add_post(
        "/webhook/notification", lambda r: sms_wallet.handle_notification_webhook(r, _ctx)
    )
    app.router.add_get("/dashboard", dashboard.handle_dashboard)
    app.router.add_get("/dashboard/auth", dashboard.handle_dashboard_auth)
    app.router.add_get(
        "/dashboard/stats", lambda r: dashboard.handle_dashboard_stats(r, _ctx)
    )
    app.router.add_post(
        "/webhooks/subscribe", lambda r: webhooks.handle_webhook_subscribe(r, _ctx)
    )
    app.router.add_get("/webhooks", lambda r: webhooks.handle_webhook_list(r, _ctx))

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", _port)

    try:
        await site.start()
        logger.info("Health server listening on http://0.0.0.0:%d", _port)
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Health server shutting down")
    finally:
        await runner.cleanup()


__all__ = [
    "HealthContext",
    "run_health_server",
    "set_ready",
]
