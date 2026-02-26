"""
Tests for drbot/health.py — HTTP health endpoint.

Uses aiohttp's TestClient so no real TCP socket is needed.
"""

import pytest
import pytest_asyncio

import drbot.health as health_module
from drbot.health import run_health_server, set_ready, _handle_health, _handle_ready, _handle_root


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
        assert data["service"] == "drbot"
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
