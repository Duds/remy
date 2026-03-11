"""Diagnostics, logs, and telemetry endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..context import HealthContext
from ..utils import check_token

logger = logging.getLogger(__name__)


async def handle_diagnostics(request, ctx: HealthContext) -> "aiohttp.web.Response":
    """Run comprehensive diagnostics and return JSON results."""
    from aiohttp import web  # type: ignore[import]

    if ctx.diagnostics_runner is None:
        return web.json_response(
            {"error": "Diagnostics runner not configured"},
            status=503,
        )

    try:
        result = await ctx.diagnostics_runner.run_all()

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

        if ctx.outbound_queue is not None:
            try:
                queue_stats = await ctx.outbound_queue.get_stats()
                response["outbound_queue"] = {
                    "pending": queue_stats.pending,
                    "sending": queue_stats.sending,
                    "failed": queue_stats.failed,
                    "sent_24h": queue_stats.sent_24h,
                }
            except Exception as e:
                response["outbound_queue"] = {"error": str(e)}

        if ctx.hook_manager is not None:
            try:
                response["hooks"] = ctx.hook_manager.get_stats()
            except Exception as e:
                response["hooks"] = {"error": str(e)}

        return web.json_response(response)

    except Exception as e:
        logger.exception("Error running diagnostics")
        return web.json_response({"error": str(e)}, status=500)


async def handle_logs(request, ctx: HealthContext) -> "aiohttp.web.Response":
    """Serve recent log lines from data/logs/remy.log."""
    from aiohttp import web  # type: ignore[import]

    if not check_token(request):
        return web.Response(
            status=401,
            text="401 Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>",
        )

    from ...diagnostics.logs import (
        get_error_summary,
        get_recent_logs,
        get_session_start_line,
        since_dt,
    )

    try:
        lines = min(int(request.rel_url.query.get("lines", "100")), 500)
    except ValueError:
        lines = 100

    level = request.rel_url.query.get("level", "").upper() or None
    since_param = request.rel_url.query.get("since", "startup")

    since_line = None
    since_ts = None
    if since_param == "startup":
        since_line = get_session_start_line(ctx.data_dir)
    elif since_param != "all":
        since_ts = since_dt(since_param)

    if level == "ERROR":
        text = get_error_summary(
            ctx.data_dir, max_items=lines, since=since_ts, since_line=since_line
        )
    else:
        text = get_recent_logs(
            ctx.data_dir, lines=lines, level=level, since=since_ts, since_line=since_line
        )

    return web.Response(text=text, content_type="text/plain")


async def handle_telemetry(request, ctx: HealthContext) -> "aiohttp.web.Response":
    """Return JSON summary of API call telemetry from the api_calls table."""
    from aiohttp import web  # type: ignore[import]

    if not check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    if ctx.db is None:
        return web.json_response({"error": "Database not available"}, status=503)

    window_param = request.rel_url.query.get("window", "24h")
    window_hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}.get(window_param, 24)
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    try:
        async with ctx.db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT provider, model, call_site,
                       input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                       latency_ms, ttft_ms, tool_execution_ms, memory_injection_ms,
                       fallback, timestamp
                FROM api_calls
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 500
                """,
                (since.isoformat(),),
            )
    except Exception as e:
        logger.error("Telemetry query failed: %s", e)
        return web.json_response({"error": str(e)}, status=500)

    rows = [dict(r) for r in rows]

    total_calls = len(rows)
    total_input = sum(r["input_tokens"] or 0 for r in rows)
    total_output = sum(r["output_tokens"] or 0 for r in rows)
    total_cache_read = sum(r["cache_read_tokens"] or 0 for r in rows)
    total_cache_write = sum(r["cache_creation_tokens"] or 0 for r in rows)
    fallback_calls = sum(1 for r in rows if r["fallback"])

    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms")]
    ttfts = [r["ttft_ms"] for r in rows if r.get("ttft_ms")]

    def _percentile(values: list, pct: int) -> int:
        if not values:
            return 0
        s = sorted(values)
        idx = int(len(s) * pct / 100)
        return s[min(idx, len(s) - 1)]

    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    p95_latency = _percentile(latencies, 95)
    avg_ttft = int(sum(ttfts) / len(ttfts)) if ttfts else 0

    total_effective_input = total_input + total_cache_read
    cache_hit_rate = (
        round(total_cache_read / total_effective_input, 3)
        if total_effective_input
        else 0.0
    )

    by_model: dict = {}
    for r in rows:
        key = r["model"] or "unknown"
        if key not in by_model:
            by_model[key] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "latencies": [],
            }
        m = by_model[key]
        m["calls"] += 1
        m["input_tokens"] += r["input_tokens"] or 0
        m["output_tokens"] += r["output_tokens"] or 0
        m["cache_read_tokens"] += r["cache_read_tokens"] or 0
        if r.get("latency_ms"):
            m["latencies"].append(r["latency_ms"])

    by_model_clean = {
        k: {
            "calls": v["calls"],
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
            "cache_read_tokens": v["cache_read_tokens"],
            "avg_latency_ms": int(sum(v["latencies"]) / len(v["latencies"]))
            if v["latencies"]
            else 0,
        }
        for k, v in sorted(by_model.items(), key=lambda x: -x[1]["calls"])
    }

    recent = [
        {
            "timestamp": r["timestamp"],
            "model": r["model"],
            "call_site": r["call_site"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cache_read_tokens": r["cache_read_tokens"],
            "latency_ms": r["latency_ms"],
            "ttft_ms": r["ttft_ms"],
            "tool_execution_ms": r["tool_execution_ms"],
            "memory_injection_ms": r["memory_injection_ms"],
            "fallback": bool(r["fallback"]),
        }
        for r in rows[:20]
    ]

    return web.json_response(
        {
            "window": window_param,
            "since": since.isoformat(),
            "total_calls": total_calls,
            "fallback_calls": fallback_calls,
            "tokens": {
                "input": total_input,
                "output": total_output,
                "cache_read": total_cache_read,
                "cache_write": total_cache_write,
            },
            "latency_ms": {"avg": avg_latency, "p95": p95_latency},
            "avg_ttft_ms": avg_ttft,
            "cache_hit_rate": cache_hit_rate,
            "by_model": by_model_clean,
            "recent_calls": recent,
        }
    )
