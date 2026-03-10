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
  POST /incoming         → Third-party webhooks (CI, Zapier). X-Webhook-Secret required.
                           Body: {"action": "notify"|"remind"|"note", "message": "...", ...}
  POST /webhooks/subscribe → Register a webhook URL for an event. Auth required.
                             Body: {"event": "plan_step_complete", "url": "https://..."}
  GET  /webhooks           → List registered webhook subscriptions. Auth required.
                             Query param: event= to filter by event name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

import asyncio
import hashlib
import hmac
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

# Late-bound references for /logs and /telemetry (consolidation: same pattern as StartupContext)
_DB = None  # DatabaseManager — set via set_db()
_DATA_DIR = "./data"  # path to data directory — set via set_data_dir()

# Late-bound WebhookManager — set via set_webhook_manager()
_WEBHOOK_MANAGER = None

# Incoming webhook (CI/Zapier): bot, get_primary_chat_id, automation_store, webhook_user_id
_INCOMING_WEBHOOK_BOT = None
_INCOMING_WEBHOOK_GET_CHAT_ID = None
_INCOMING_WEBHOOK_AUTOMATION_STORE = None
_INCOMING_WEBHOOK_USER_ID = None
_INCOMING_WEBHOOK_RATE: dict[str, list[float]] = {}
_INCOMING_WEBHOOK_RATE_LIMIT = 60  # requests per minute per IP


def set_incoming_webhook_deps(
    *,
    bot=None,
    get_primary_chat_id=None,
    automation_store=None,
    webhook_user_id: int | None = None,
) -> None:
    """Set dependencies for POST /incoming (third-party webhooks)."""
    global _INCOMING_WEBHOOK_BOT, _INCOMING_WEBHOOK_GET_CHAT_ID
    global _INCOMING_WEBHOOK_AUTOMATION_STORE, _INCOMING_WEBHOOK_USER_ID
    _INCOMING_WEBHOOK_BOT = bot
    _INCOMING_WEBHOOK_GET_CHAT_ID = get_primary_chat_id
    _INCOMING_WEBHOOK_AUTOMATION_STORE = automation_store
    _INCOMING_WEBHOOK_USER_ID = webhook_user_id


def set_webhook_manager(manager) -> None:
    """Register the WebhookManager so /webhooks endpoints can use it."""
    global _WEBHOOK_MANAGER
    _WEBHOOK_MANAGER = manager


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


async def _handle_incoming_webhook(request) -> "aiohttp.web.Response":
    """POST /incoming — third-party webhooks (CI, Zapier). Actions: notify, remind, note.

    Requires X-Webhook-Secret header matching REMY_WEBHOOK_SECRET.
    Body (JSON): {"action": "notify"|"remind"|"note", "message": "...", "source": "...",
                  "label": "...", "fire_at": "ISO8601"} (fields depend on action).
    """
    from aiohttp import web  # type: ignore[import]

    from ..config import get_settings

    settings = get_settings()
    if not (settings.remy_webhook_secret or "").strip():
        return web.json_response({"error": "Incoming webhooks not configured"}, status=404)

    secret = (request.headers.get("X-Webhook-Secret") or "").strip()
    if secret != settings.remy_webhook_secret.strip():
        return web.json_response({"error": "Unauthorized"}, status=401)

    # Rate limit per IP
    peername = request.remote or "unknown"
    now = time.time()
    if peername not in _INCOMING_WEBHOOK_RATE:
        _INCOMING_WEBHOOK_RATE[peername] = []
    times = _INCOMING_WEBHOOK_RATE[peername]
    times.append(now)
    times[:] = [t for t in times if now - t < 60]
    if len(times) > _INCOMING_WEBHOOK_RATE_LIMIT:
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
            {"error": "Missing or invalid 'action'. Use: notify, remind, note"}, status=400
        )

    if action == "notify":
        message = (body.get("message") or "").strip()
        if not message:
            return web.json_response({"error": "Missing 'message' for notify"}, status=400)
        source = (body.get("source") or "").strip()
        if source:
            message = f"[{source}] {message}"
        chat_id = _INCOMING_WEBHOOK_GET_CHAT_ID() if _INCOMING_WEBHOOK_GET_CHAT_ID else None
        if _INCOMING_WEBHOOK_BOT is None or chat_id is None:
            return web.json_response(
                {"error": "Bot or primary chat not available"}, status=503
            )
        try:
            await _INCOMING_WEBHOOK_BOT.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.warning("Incoming webhook notify failed: %s", e)
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"status": "ok"})

    if action == "remind":
        label = (body.get("label") or "").strip() or "Webhook reminder"
        fire_at = (body.get("fire_at") or "").strip()
        if not fire_at:
            return web.json_response({"error": "Missing 'fire_at' for remind"}, status=400)
        user_id = _INCOMING_WEBHOOK_USER_ID
        store = _INCOMING_WEBHOOK_AUTOMATION_STORE
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
        if abs(time.time() - auth_date) > 300:  # 5 min
            return False
    except (TypeError, ValueError):
        return False
    return True


async def _handle_dashboard(request) -> "aiohttp.web.Response":
    """GET /dashboard — login page with Telegram Login Widget."""
    from aiohttp import web  # type: ignore[import]

    from ..config import get_settings

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


async def _handle_dashboard_auth(request) -> "aiohttp.web.Response":
    """GET /dashboard/auth — verify Telegram widget (query params) and set session cookie."""
    from aiohttp import web  # type: ignore[import]

    from ..config import get_settings

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
    # Simple session: sign user_id + expiry (1h)
    expiry = int(time.time()) + 3600
    secret = (settings.health_api_token or settings.remy_webhook_secret or "remy-dashboard").encode()
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


async def _handle_dashboard_stats(request) -> "aiohttp.web.Response":
    """GET /dashboard/stats — require session, show stats."""
    from aiohttp import web  # type: ignore[import]

    from ..config import get_settings

    settings = get_settings()
    cookie_val = request.cookies.get("remy_dash")
    if not cookie_val or ":" not in cookie_val:
        return web.Response(status=302, headers={"Location": "/dashboard"})
    parts = cookie_val.rsplit(":", 1)
    if len(parts) != 2:
        return web.Response(status=302, headers={"Location": "/dashboard"})
    msg, sig = parts[0], parts[1]
    secret = (settings.health_api_token or settings.remy_webhook_secret or "remy-dashboard").encode()
    expected = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return web.Response(status=302, headers={"Location": "/dashboard"})
    try:
        user_id_s, expiry_s = msg.split(":", 1)
        if int(expiry_s) < time.time():
            return web.Response(status=302, headers={"Location": "/dashboard"})
    except (ValueError, TypeError):
        return web.Response(status=302, headers={"Location": "/dashboard"})
    if _DB is None:
        return web.Response(text="Stats not available (DB not wired).", status=503)
    try:
        async with _DB.get_connection() as conn:
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


async def _handle_webhook_subscribe(request) -> "aiohttp.web.Response":
    """POST /webhooks/subscribe — register a webhook URL for an event.

    Body (JSON): {"event": "plan_step_complete", "url": "https://example.com/hook"}
    Returns 200 with the created subscription or 400 on error.
    Requires HEALTH_API_TOKEN auth if configured.
    """
    from aiohttp import web  # type: ignore[import]

    if not _check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    if _WEBHOOK_MANAGER is None:
        return web.json_response({"error": "Webhook manager not available"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    event = str(body.get("event", "")).strip()
    url = str(body.get("url", "")).strip()
    if not event or not url:
        return web.json_response({"error": "event and url are required"}, status=400)

    try:
        sub = await _WEBHOOK_MANAGER.subscribe(event, url)
        return web.json_response({"status": "subscribed", "subscription": sub})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def _handle_webhook_list(request) -> "aiohttp.web.Response":
    """GET /webhooks — list all webhook subscriptions.

    Query param: event= to filter by event name.
    Requires HEALTH_API_TOKEN auth if configured.
    """
    from aiohttp import web  # type: ignore[import]

    if not _check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    if _WEBHOOK_MANAGER is None:
        return web.json_response({"error": "Webhook manager not available"}, status=503)

    event_filter = request.rel_url.query.get("event")
    subs = await _WEBHOOK_MANAGER.list_subscriptions(event_filter)
    return web.json_response({"subscriptions": subs, "count": len(subs)})


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
    app.router.add_post("/incoming", _handle_incoming_webhook)
    app.router.add_get("/dashboard", _handle_dashboard)
    app.router.add_get("/dashboard/auth", _handle_dashboard_auth)
    app.router.add_get("/dashboard/stats", _handle_dashboard_stats)
    app.router.add_post("/webhooks/subscribe", _handle_webhook_subscribe)
    app.router.add_get("/webhooks", _handle_webhook_list)

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
