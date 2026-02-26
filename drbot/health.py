"""
Lightweight HTTP health check server.

Runs an aiohttp server on HEALTH_PORT (default 8080) alongside the Telegram bot
in the same asyncio event loop. Used by:
  - Docker HEALTHCHECK
  - Azure Container Instances liveness/readiness probes
  - Local `make status` checks

Endpoints:
  GET /health  → 200 {"status": "ok", "uptime_s": N}
  GET /ready   → 200 {"status": "ready"} or 503 {"status": "starting"}
"""

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_START_TIME = time.monotonic()
_READY = False  # flipped to True after DB init completes


def set_ready() -> None:
    """Call this once the database and scheduler are initialised."""
    global _READY
    _READY = True
    logger.info("Health server: marked ready")


async def _handle_health(request) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]
    uptime = int(time.monotonic() - _START_TIME)
    return web.json_response({"status": "ok", "uptime_s": uptime})


async def _handle_ready(request) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]
    if _READY:
        return web.json_response({"status": "ready"})
    return web.json_response({"status": "starting"}, status=503)


async def _handle_root(request) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]
    return web.json_response({"service": "drbot", "version": "1.0"})


async def run_health_server(port: int | None = None) -> None:
    """
    Start the aiohttp health server on the given port.
    Runs until cancelled. Call with asyncio.create_task().
    """
    try:
        from aiohttp import web  # type: ignore[import]
    except ImportError:
        logger.warning(
            "aiohttp not installed — health endpoint disabled. "
            "Add 'aiohttp' to requirements.txt to enable it."
        )
        return

    _port = port or int(os.environ.get("HEALTH_PORT", "8080"))

    app = web.Application()
    app.router.add_get("/", _handle_root)
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/ready", _handle_ready)

    runner = web.AppRunner(app, access_log=None)  # suppress per-request noise
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", _port)

    try:
        await site.start()
        logger.info("Health server listening on http://0.0.0.0:%d", _port)
        # Run forever (until this coroutine is cancelled)
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Health server shutting down")
    finally:
        await runner.cleanup()
