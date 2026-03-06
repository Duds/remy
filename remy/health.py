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
                     Query params: lines (default 100), level (ERROR/WARNING/INFO),
                                   since (startup|1h|6h|24h|all)
  GET /telemetry   → JSON summary of API call stats from the last 24h.
                     Auth required if HEALTH_API_TOKEN set.
                     Query params: window (1h|6h|24h|7d, default 24h)
  GET /files       → Stream a file by path. Requires path= and token= (signed).
                     Path must be base64url-encoded; token from get_file_download_link.
  POST /commands/ship-it → Run SHIP-IT pipeline (fetch, diff, tests). Auth required.
                           Optional JSON body: {"dry_run": true} to skip running tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_START_TIME = time.monotonic()
_READY = False  # flipped to True after DB init completes

# Late-bound references for diagnostics endpoint
_DIAGNOSTICS_RUNNER = None
_OUTBOUND_QUEUE = None
_HOOK_MANAGER = None

# Late-bound references for /logs and /telemetry
_DB = None  # DatabaseManager — set via set_db()
_DATA_DIR = "./data"  # path to data directory — set via set_data_dir()


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


def set_db(db) -> None:
    """Set the DatabaseManager for /telemetry endpoint."""
    global _DB
    _DB = db


def set_data_dir(data_dir: str) -> None:
    """Set the data directory path for /logs endpoint."""
    global _DATA_DIR
    _DATA_DIR = data_dir


def _check_token(request) -> bool:
    """
    Return True if the request passes token auth.

    If HEALTH_API_TOKEN is not set (or empty), all requests pass.
    Otherwise, the token must be supplied via:
      - Authorization: Bearer <token>  header, or
      - ?token=<token>                 query param
    """
    token = os.environ.get("HEALTH_API_TOKEN", "").strip()
    if not token:
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == token:
        return True
    if request.rel_url.query.get("token") == token:
        return True
    return False


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


async def _handle_logs(request) -> "aiohttp.web.Response":
    """
    Serve recent log lines from data/logs/remy.log.

    Query params:
      lines  — number of lines to return (default 100, max 500)
      level  — filter to ERROR / WARNING / INFO (omit for all)
      since  — startup | 1h | 6h | 24h | all (default: startup)
    """
    from aiohttp import web  # type: ignore[import]

    if not _check_token(request):
        return web.Response(
            status=401,
            text="401 Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>",
        )

    from .diagnostics.logs import (
        get_recent_logs,
        get_error_summary,
        since_dt,
        get_session_start_line,
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
        since_line = get_session_start_line(_DATA_DIR)
    elif since_param != "all":
        since_ts = since_dt(since_param)

    if level == "ERROR":
        text = get_error_summary(
            _DATA_DIR, max_items=lines, since=since_ts, since_line=since_line
        )
    else:
        text = get_recent_logs(
            _DATA_DIR, lines=lines, level=level, since=since_ts, since_line=since_line
        )

    return web.Response(text=text, content_type="text/plain")


async def _handle_telemetry(request) -> "aiohttp.web.Response":
    """
    Return a JSON summary of API call telemetry from the api_calls table.

    Query params:
      window — 1h | 6h | 24h | 7d (default: 24h)
    """
    from aiohttp import web  # type: ignore[import]

    if not _check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    if _DB is None:
        return web.json_response({"error": "Database not available"}, status=503)

    window_param = request.rel_url.query.get("window", "24h")
    window_hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}.get(window_param, 24)
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    try:
        async with _DB.get_connection() as conn:
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

    # Aggregate stats
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

    # Cache hit rate: cache_read / (cache_read + input)
    total_effective_input = total_input + total_cache_read
    cache_hit_rate = (
        round(total_cache_read / total_effective_input, 3)
        if total_effective_input
        else 0.0
    )

    # Per-model breakdown
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

    # Recent 20 calls for the timeline view
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
            "latency_ms": {
                "avg": avg_latency,
                "p95": p95_latency,
            },
            "avg_ttft_ms": avg_ttft,
            "cache_hit_rate": cache_hit_rate,
            "by_model": by_model_clean,
            "recent_calls": recent,
        }
    )


async def _handle_files(request) -> "aiohttp.web.Response":
    """
    Stream a file from allowed base dirs. Requires path= and token= (signed).
    path must be base64url-encoded. Returns 401 if token invalid/expired, 403 if path not allowed.
    """
    from typing import cast

    from aiohttp import web  # type: ignore[import]

    from .config import settings
    from .file_link import decode_path_param, verify_token
    from .ai.input_validator import sanitize_file_path

    path_encoded = request.rel_url.query.get("path", "").strip()
    token = request.rel_url.query.get("token", "").strip()
    if not path_encoded or not token:
        return web.json_response(
            {"error": "Missing path or token query parameter"},
            status=400,
        )

    path = decode_path_param(path_encoded)
    if path is None:
        return web.json_response({"error": "Invalid path parameter"}, status=400)

    secret = (
        os.environ.get("FILE_LINK_SECRET") or os.environ.get("HEALTH_API_TOKEN") or ""
    ).strip()
    ok, reason = verify_token(path, token, secret)
    if not ok:
        return web.json_response(
            {"error": reason or "Unauthorized"},
            status=401,
        )

    safe_path, err = sanitize_file_path(path, settings.allowed_base_dirs)
    if err or safe_path is None:
        return web.json_response({"error": err or "Access denied"}, status=403)

    file_path = __import__("pathlib").Path(safe_path)
    if not file_path.exists():
        return web.json_response({"error": "File not found"}, status=404)
    if not file_path.is_file():
        return web.json_response({"error": "Not a file"}, status=400)

    chunk_size = 65536
    try:
        import mimetypes

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"
        disposition = f'attachment; filename="{file_path.name}"'
    except Exception:
        content_type = "application/octet-stream"
        disposition = f'attachment; filename="{file_path.name}"'

    async def stream():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": content_type,
            "Content-Disposition": disposition,
        },
    )
    await response.prepare(request)
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            await response.write(chunk)
    await response.write_eof()
    return cast(web.Response, response)


async def _handle_ship_it(request: "aiohttp.web.Request") -> "aiohttp.web.Response":
    """
    Run the SHIP-IT pipeline: git fetch, diff against main, run tests.
    Requires Bearer token (same as /logs, /telemetry). Intended for remote
    trigger over Cloudflare Tunnel (e.g. https://remy.dalerogers.com.au/commands/ship-it).
    """
    from aiohttp import web  # type: ignore[import]

    if request.method != "POST":
        return web.json_response(
            {"error": "Method not allowed — use POST"},
            status=405,
        )
    if not _check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    workspace = os.environ.get("WORKSPACE_ROOT", "").strip()
    if not workspace:
        return web.json_response(
            {"error": "WORKSPACE_ROOT not set — cannot run SHIP-IT"},
            status=503,
        )
    workspace_path = __import__("pathlib").Path(workspace)
    if not workspace_path.is_dir():
        return web.json_response(
            {"error": f"WORKSPACE_ROOT is not a directory: {workspace}"},
            status=503,
        )

    dry_run = False
    try:
        if request.content_length and request.content_length > 0:
            body = await request.json()
            dry_run = bool(body.get("dry_run", False))
    except Exception:
        pass

    result: dict = {
        "branch": None,
        "diff_summary": None,
        "tests_passed": None,
        "tests_output": None,
        "error": None,
    }

    async def _run(cmd: list[str], cwd: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, (stdout or b"").decode("utf-8", errors="replace")

    # Git fetch and branch
    code, out = await _run(["git", "fetch", "origin", "main"], str(workspace_path))
    if code != 0:
        result["error"] = f"git fetch failed: {out[:500]}"
        return web.json_response(result, status=200)

    code, out = await _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], str(workspace_path)
    )
    result["branch"] = out.strip() if code == 0 else None

    code, out = await _run(
        ["git", "diff", "origin/main...HEAD", "--stat"],
        str(workspace_path),
    )
    result["diff_summary"] = out.strip() if code == 0 else None

    if dry_run:
        result["tests_passed"] = None
        result["tests_output"] = "(dry run — tests skipped)"
        return web.json_response(result)

    # Run tests (pytest)
    code, out = await _run(
        ["python3", "-m", "pytest", "tests/", "-v", "--tb=short"],
        str(workspace_path),
    )
    result["tests_passed"] = code == 0
    result["tests_output"] = out[-4000:] if len(out) > 4000 else out  # last 4k chars

    return web.json_response(result)


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
    app.router.add_get("/logs", _handle_logs)
    app.router.add_get("/telemetry", _handle_telemetry)
    app.router.add_get("/files", _handle_files)
    app.router.add_post("/commands/ship-it", _handle_ship_it)

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
