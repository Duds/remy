"""
Tests for remy/health.py — HTTP health endpoint.

Uses aiohttp's TestClient so no real TCP socket is needed.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import remy.health as health_module
from remy.health import (
    run_health_server,
    set_ready,
    set_db,
    _handle_health,
    _handle_ready,
    _handle_root,
    _handle_logs,
    _handle_telemetry,
    _handle_files,
    _handle_ship_it,
    _check_token,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def reset_ready_flag():
    """Ensure _READY is reset to False between tests."""
    health_module._READY = False
    yield
    health_module._READY = False


# --------------------------------------------------------------------------- #
# Unit tests for handler functions (via aiohttp TestClient)                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_health_endpoint_returns_200():
    """GET /health should always return 200 with uptime."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/ready", _handle_ready)
    app.router.add_get("/", _handle_root)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "uptime_s" in data
        assert isinstance(data["uptime_s"], int)


@pytest.mark.asyncio
async def test_ready_returns_503_before_set_ready():
    """/ready should return 503 before set_ready() is called."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/ready", _handle_ready)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/ready")
        assert resp.status == 503
        data = await resp.json()
        assert data["status"] == "starting"


@pytest.mark.asyncio
async def test_ready_returns_200_after_set_ready():
    """/ready should return 200 after set_ready() is called."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    set_ready()

    app = web.Application()
    app.router.add_get("/ready", _handle_ready)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/ready")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_root_endpoint_returns_service_info():
    """GET / should return service name and version."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/", _handle_root)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200
        data = await resp.json()
        assert data["service"] == "remy"
        assert "version" in data


@pytest.mark.asyncio
async def test_health_uptime_is_non_negative():
    """Uptime should always be >= 0."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/health", _handle_health)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        data = await resp.json()
        assert data["uptime_s"] >= 0


@pytest.mark.asyncio
async def test_set_ready_is_idempotent():
    """Calling set_ready() multiple times should not raise."""
    set_ready()
    set_ready()
    assert health_module._READY is True


# --------------------------------------------------------------------------- #
# run_health_server cancellation test                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_health_server_starts_and_cancels():
    """run_health_server should start and shut down cleanly on cancellation."""
    import asyncio

    try:
        import aiohttp  # noqa: F401
    except ImportError:
        pytest.skip("aiohttp not installed")

    # Use a high port unlikely to conflict
    task = asyncio.create_task(run_health_server(port=19876))
    # Give it a moment to start
    await asyncio.sleep(0.1)
    # Cancel it — should not raise
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # expected


# --------------------------------------------------------------------------- #
# run_health_server graceful degradation without aiohttp                      #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_health_server_graceful_without_aiohttp():
    """If aiohttp is not importable, run_health_server should return quietly."""
    import sys
    from unittest.mock import patch

    # Temporarily hide aiohttp
    with patch.dict(sys.modules, {"aiohttp": None, "aiohttp.web": None}):
        # Should return without raising, just logs a warning
        await run_health_server(port=19877)


# --------------------------------------------------------------------------- #
# _check_token unit tests                                                      #
# --------------------------------------------------------------------------- #


def test_check_token_passes_when_no_token_configured():
    """_check_token returns True when HEALTH_API_TOKEN is not set."""
    mock_request = MagicMock()
    with patch.dict("os.environ", {}, clear=False):
        os_env = os.environ.copy()
        os_env.pop("HEALTH_API_TOKEN", None)
        with patch(
            "os.environ.get",
            side_effect=lambda k, d="": (
                "" if k == "HEALTH_API_TOKEN" else os.environ.get(k, d)
            ),
        ):
            assert _check_token(mock_request) is True


def test_check_token_passes_with_correct_bearer_header():
    """_check_token returns True when Authorization: Bearer header matches."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "Bearer secret123"
    mock_request.rel_url.query.get.return_value = ""
    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret123"}):
        assert _check_token(mock_request) is True


def test_check_token_passes_with_correct_query_param():
    """_check_token returns True when ?token= query param matches."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = ""
    mock_request.rel_url.query.get.side_effect = lambda k, d="": (
        "secret123" if k == "token" else d
    )
    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret123"}):
        assert _check_token(mock_request) is True


def test_check_token_fails_with_wrong_bearer():
    """_check_token returns False when Bearer token is wrong."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "Bearer wrongtoken"
    mock_request.rel_url.query.get.return_value = ""
    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret123"}):
        assert _check_token(mock_request) is False


def test_check_token_fails_with_no_credentials():
    """_check_token returns False when token is required but not supplied."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = ""
    mock_request.rel_url.query.get.return_value = ""
    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret123"}):
        assert _check_token(mock_request) is False


# --------------------------------------------------------------------------- #
# /logs endpoint tests                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_logs_returns_401_when_token_required():
    """GET /logs should return 401 when HEALTH_API_TOKEN is set and not supplied."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/logs", _handle_logs)

    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret123"}):
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/logs")
            assert resp.status == 401


@pytest.mark.asyncio
async def test_logs_returns_200_with_no_token_required():
    """GET /logs returns 200 plain text when no HEALTH_API_TOKEN is configured."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/logs", _handle_logs)

    with patch.dict("os.environ", {}, clear=False):
        # Ensure token is absent
        env = {k: v for k, v in os.environ.items() if k != "HEALTH_API_TOKEN"}
        with patch.dict("os.environ", env, clear=True):
            with patch("remy.health._check_token", return_value=True):
                with patch(
                    "remy.diagnostics.logs.get_recent_logs",
                    return_value="log line 1\nlog line 2",
                ) as _mock:
                    with patch(
                        "remy.diagnostics.logs.get_session_start_line", return_value=0
                    ):
                        async with TestClient(TestServer(app)) as client:
                            resp = await client.get("/logs")
                            assert resp.status == 200
                            assert resp.content_type == "text/plain"
                            text = await resp.text()
                            assert "log line" in text


@pytest.mark.asyncio
async def test_logs_passes_with_correct_token_in_header():
    """GET /logs returns 200 when valid Authorization: Bearer header is supplied."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/logs", _handle_logs)

    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "mytoken"}):
        with patch("remy.diagnostics.logs.get_recent_logs", return_value="some logs"):
            with patch("remy.diagnostics.logs.get_session_start_line", return_value=0):
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get(
                        "/logs", headers={"Authorization": "Bearer mytoken"}
                    )
                    assert resp.status == 200


# --------------------------------------------------------------------------- #
# /telemetry endpoint tests                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_telemetry_returns_503_when_db_not_set():
    """GET /telemetry returns 503 when DB has not been wired."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    # Ensure _DB is None
    set_db(None)

    app = web.Application()
    app.router.add_get("/telemetry", _handle_telemetry)

    with patch("remy.health._check_token", return_value=True):
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/telemetry")
            assert resp.status == 503
            data = await resp.json()
            assert "error" in data


@pytest.mark.asyncio
async def test_telemetry_returns_401_when_token_required():
    """GET /telemetry returns 401 when token is required but not supplied."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/telemetry", _handle_telemetry)

    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret"}):
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/telemetry")
            assert resp.status == 401


@pytest.mark.asyncio
async def test_telemetry_returns_200_with_mock_db():
    """GET /telemetry returns 200 JSON with aggregate stats when DB is wired."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    # Build a fake DB with an async context manager
    fake_rows = [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "call_site": "chat",
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_tokens": 50,
            "cache_read_tokens": 300,
            "latency_ms": 1200,
            "ttft_ms": 400,
            "tool_execution_ms": None,
            "memory_injection_ms": None,
            "fallback": 0,
            "timestamp": "2026-03-02T10:00:00+00:00",
        }
    ]

    mock_conn = AsyncMock()
    mock_conn.execute_fetchall = AsyncMock(return_value=fake_rows)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.get_connection = MagicMock(return_value=mock_ctx)

    set_db(mock_db)

    app = web.Application()
    app.router.add_get("/telemetry", _handle_telemetry)

    with patch("remy.health._check_token", return_value=True):
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/telemetry")
            assert resp.status == 200
            data = await resp.json()
            assert data["total_calls"] == 1
            assert data["fallback_calls"] == 0
            assert data["tokens"]["input"] == 1000
            assert data["tokens"]["output"] == 200
            assert data["tokens"]["cache_read"] == 300
            assert "by_model" in data
            assert "claude-sonnet-4-6" in data["by_model"]
            assert len(data["recent_calls"]) == 1
            assert data["recent_calls"][0]["model"] == "claude-sonnet-4-6"

    # Clean up
    set_db(None)


@pytest.mark.asyncio
async def test_telemetry_window_parameter_accepted():
    """GET /telemetry accepts window=1h, 6h, 24h, 7d without error."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    mock_conn = AsyncMock()
    mock_conn.execute_fetchall = AsyncMock(return_value=[])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.get_connection = MagicMock(return_value=mock_ctx)

    set_db(mock_db)

    app = web.Application()
    app.router.add_get("/telemetry", _handle_telemetry)

    with patch("remy.health._check_token", return_value=True):
        async with TestClient(TestServer(app)) as client:
            for window in ("1h", "6h", "24h", "7d"):
                resp = await client.get(f"/telemetry?window={window}")
                assert resp.status == 200
                data = await resp.json()
                assert data["window"] == window

    set_db(None)


@pytest.mark.asyncio
async def test_telemetry_empty_db_returns_zero_stats():
    """GET /telemetry with no rows in DB returns zeroed aggregate stats."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    mock_conn = AsyncMock()
    mock_conn.execute_fetchall = AsyncMock(return_value=[])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.get_connection = MagicMock(return_value=mock_ctx)

    set_db(mock_db)

    app = web.Application()
    app.router.add_get("/telemetry", _handle_telemetry)

    with patch("remy.health._check_token", return_value=True):
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/telemetry")
            assert resp.status == 200
            data = await resp.json()
            assert data["total_calls"] == 0
            assert data["fallback_calls"] == 0
            assert data["tokens"]["input"] == 0
            assert data["cache_hit_rate"] == 0.0
            assert data["recent_calls"] == []
            assert data["by_model"] == {}

    set_db(None)


# --------------------------------------------------------------------------- #
# /files endpoint tests                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_files_returns_400_when_missing_params():
    """GET /files returns 400 when path or token is missing."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_get("/files", _handle_files)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/files")
        assert resp.status == 400
        resp = await client.get("/files?path=abc")
        assert resp.status == 400
        resp = await client.get("/files?token=abc")
        assert resp.status == 400


@pytest.mark.asyncio
async def test_files_returns_401_when_token_invalid():
    """GET /files returns 401 when token is invalid or expired."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    from remy.file_link import encode_path_param

    app = web.Application()
    app.router.add_get("/files", _handle_files)

    path_encoded = encode_path_param("/tmp/somefile.txt")
    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret"}):
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/files?path={path_encoded}&token=invalidtoken")
            assert resp.status == 401


# --------------------------------------------------------------------------- #
# POST /commands/ship-it endpoint tests                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ship_it_returns_405_for_get():
    """POST /commands/ship-it only accepts POST."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_post("/commands/ship-it", _handle_ship_it)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/commands/ship-it")
        assert resp.status == 405


@pytest.mark.asyncio
async def test_ship_it_returns_401_without_token():
    """POST /commands/ship-it returns 401 when HEALTH_API_TOKEN set and not supplied."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_post("/commands/ship-it", _handle_ship_it)

    with patch.dict("os.environ", {"HEALTH_API_TOKEN": "secret123"}):
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/commands/ship-it")
            assert resp.status == 401


@pytest.mark.asyncio
async def test_ship_it_returns_503_when_workspace_root_unset():
    """POST /commands/ship-it returns 503 when WORKSPACE_ROOT is not set."""
    try:
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        pytest.skip("aiohttp not installed")

    app = web.Application()
    app.router.add_post("/commands/ship-it", _handle_ship_it)

    with patch.dict(
        "os.environ", {"HEALTH_API_TOKEN": "secret123", "WORKSPACE_ROOT": ""}
    ):
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/commands/ship-it",
                headers={"Authorization": "Bearer secret123"},
            )
            assert resp.status == 503
            data = await resp.json()
            assert data.get("error") == "WORKSPACE_ROOT not set — cannot run SHIP-IT"
