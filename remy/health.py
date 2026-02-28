"""
Lightweight HTTP health check server with Prometheus metrics.

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
"""

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_START_TIME = time.monotonic()
_READY = False  # flipped to True after DB init completes

# Late-bound references for diagnostics endpoint
_DIAGNOSTICS_RUNNER = None
_OUTBOUND_QUEUE = None
_HOOK_MANAGER = None


def set_diagnostics_runner(runner) -> None:
    """Set the diagnostics runner for the /diagnostics endpoint."""
    global _DIAGNOSTICS_RUNNER
    _DIAGNOSTICS_RUNNER = runner


def set_outbound_queue(queue) -> None:
    """Set the outbound queue for diagnostics stats."""
    global _OUTBOUND_QUEUE
    _OUTBOUND_QUEUE = queue


def set_hook_manager(manager) -> None:
    """Set the hook manager for diagnostics stats."""
    global _HOOK_MANAGER
    _HOOK_MANAGER = manager


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
    return web.json_response({"service": "remy", "version": "1.0"})


async def _handle_metrics(request) -> "aiohttp.web.Response":
    """Serve Prometheus metrics in text format."""
    from aiohttp import web  # type: ignore[import]
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        metrics_output = generate_latest()
        return web.Response(body=metrics_output, content_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return web.json_response(
            {"error": "prometheus-client not installed"},
            status=501,
        )
    except Exception as e:
        logger.error("Error generating metrics: %s", e)
        return web.json_response({"error": str(e)}, status=500)


async def _handle_diagnostics(request) -> "aiohttp.web.Response":
    """Run comprehensive diagnostics and return JSON results.

    Includes:
    - All DiagnosticsRunner checks (database, AI providers, memory, etc.)
    - Outbound queue stats (pending, failed, sent_24h)
    - Hook system stats (registered handlers, emissions)
    """
    from aiohttp import web  # type: ignore[import]

    if _DIAGNOSTICS_RUNNER is None:
        return web.json_response(
            {"error": "Diagnostics runner not configured"},
            status=503,
        )

    try:
        result = await _DIAGNOSTICS_RUNNER.run_all()

        # Convert to JSON-serialisable format
        checks_json = [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "duration_ms": round(check.duration_ms, 2),
                "details": check.details,
            }
            for check in result.checks
        ]

        response = {
            "status": result.overall_status.value,
            "version": result.version,
            "python_version": result.python_version,
            "uptime_seconds": round(result.uptime_seconds, 1),
            "last_restart": result.last_restart.isoformat(),
            "total_duration_ms": round(result.total_duration_ms, 2),
            "checks": checks_json,
        }

        # Add outbound queue stats if available
        if _OUTBOUND_QUEUE is not None:
            try:
                queue_stats = await _OUTBOUND_QUEUE.get_stats()
                response["outbound_queue"] = {
                    "pending": queue_stats.pending,
                    "sending": queue_stats.sending,
                    "failed": queue_stats.failed,
                    "sent_24h": queue_stats.sent_24h,
                }
            except Exception as e:
                response["outbound_queue"] = {"error": str(e)}

        # Add hook system stats if available
        if _HOOK_MANAGER is not None:
            try:
                response["hooks"] = _HOOK_MANAGER.get_stats()
            except Exception as e:
                response["hooks"] = {"error": str(e)}

        return web.json_response(response)

    except Exception as e:
        logger.exception("Error running diagnostics")
        return web.json_response({"error": str(e)}, status=500)


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

    # Initialise service info for Prometheus
    try:
        from .analytics.metrics import set_service_info
        environment = "azure" if os.environ.get("AZURE_ENVIRONMENT") else "local"
        set_service_info(version="1.0", environment=environment)
    except ImportError:
        pass

    app = web.Application()
    app.router.add_get("/", _handle_root)
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/ready", _handle_ready)
    app.router.add_get("/metrics", _handle_metrics)
    app.router.add_get("/diagnostics", _handle_diagnostics)

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
