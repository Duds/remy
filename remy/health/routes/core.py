"""Core health endpoints: root, health, ready."""

from __future__ import annotations

import time

from ..context import HealthContext
from ..utils import get_start_time


async def handle_root(request) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]

    return web.json_response({"service": "remy", "version": "1.0"})


async def handle_health(request) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]

    uptime = int(time.monotonic() - get_start_time())
    return web.json_response({"status": "ok", "uptime_s": uptime})


async def handle_ready(request, ctx: HealthContext) -> "aiohttp.web.Response":
    from aiohttp import web  # type: ignore[import]

    if ctx.is_ready():
        return web.json_response({"status": "ready"})
    return web.json_response({"status": "starting"}, status=503)
