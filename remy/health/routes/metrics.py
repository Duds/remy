"""Prometheus metrics endpoint."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def handle_metrics(request) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]

    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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
