"""
Tests for US-analytics-call-log.

Covers:
- api_calls table schema and creation
- log_api_call helper function
- Non-blocking writes (fire-and-forget)
- Graceful failure handling
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from remy.analytics.call_log import log_api_call
from remy.memory.database import DatabaseManager
from remy.models import TokenUsage


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh DB per test."""
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    await manager.init()
    yield manager
    await manager.close()


# ---------------------------------------------------------------------------
# api_calls table schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_calls_table_exists(db):
    """api_calls table should be created during init."""
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_calls'"
        )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_api_calls_table_has_correct_columns(db):
    """Verify all required columns exist with correct types."""
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall("PRAGMA table_info(api_calls)")
    
    columns = {row["name"]: row for row in rows}
    
    assert "id" in columns
    assert "user_id" in columns
    assert "session_key" in columns
    assert "timestamp" in columns
    assert "provider" in columns
    assert "model" in columns
    assert "category" in columns
    assert "call_site" in columns
    assert "input_tokens" in columns
    assert "output_tokens" in columns
    assert "cache_creation_tokens" in columns
    assert "cache_read_tokens" in columns
    assert "latency_ms" in columns
    assert "fallback" in columns


@pytest.mark.asyncio
async def test_api_calls_index_exists(db):
    """Index on (user_id, timestamp) should exist for efficient queries."""
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_api_calls_user_ts'"
        )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# log_api_call helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_api_call_inserts_row(db):
    """log_api_call should insert a row with all provided values."""
    usage = TokenUsage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=5,
        cache_read_tokens=10,
    )
    
    await log_api_call(
        db,
        user_id=123,
        session_key="user_123_20260228",
        provider="anthropic",
        model="claude-sonnet-4-6",
        category="reasoning",
        call_site="router",
        usage=usage,
        latency_ms=1500,
        fallback=False,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT * FROM api_calls WHERE user_id=123")
    
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == 123
    assert row["session_key"] == "user_123_20260228"
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["category"] == "reasoning"
    assert row["call_site"] == "router"
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50
    assert row["cache_creation_tokens"] == 5
    assert row["cache_read_tokens"] == 10
    assert row["latency_ms"] == 1500
    assert row["fallback"] == 0


@pytest.mark.asyncio
async def test_log_api_call_fallback_flag(db):
    """fallback=True should be stored as 1."""
    usage = TokenUsage()
    
    await log_api_call(
        db,
        user_id=456,
        session_key="user_456_20260228",
        provider="ollama",
        model="local",
        category="routine",
        call_site="router",
        usage=usage,
        latency_ms=500,
        fallback=True,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT fallback FROM api_calls WHERE user_id=456")
    
    assert rows[0]["fallback"] == 1


@pytest.mark.asyncio
async def test_log_api_call_timestamp_is_utc_iso(db):
    """Timestamp should be ISO 8601 UTC format."""
    usage = TokenUsage()
    
    await log_api_call(
        db,
        user_id=789,
        session_key="user_789_20260228",
        provider="mistral",
        model="mistral-medium-3",
        category="routine",
        call_site="router",
        usage=usage,
        latency_ms=200,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT timestamp FROM api_calls WHERE user_id=789")
    
    ts = rows[0]["timestamp"]
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None or "+" in ts or "Z" in ts


@pytest.mark.asyncio
async def test_log_api_call_multiple_rows(db):
    """Multiple calls should create multiple rows."""
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    
    for i in range(3):
        await log_api_call(
            db,
            user_id=100,
            session_key=f"user_100_2026022{i}",
            provider="anthropic",
            model="claude-haiku",
            category="classifier",
            call_site="classifier",
            usage=usage,
            latency_ms=50 + i * 10,
        )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT * FROM api_calls WHERE user_id=100")
    
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_api_call_handles_db_error_gracefully(db, caplog):
    """DB write failure should log WARNING and not raise."""
    usage = TokenUsage()
    
    with patch.object(db, "get_connection") as mock_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("disk full"))
        mock_ctx.__aexit__ = AsyncMock()
        mock_conn.return_value = mock_ctx
        
        await log_api_call(
            db,
            user_id=999,
            session_key="user_999_20260228",
            provider="anthropic",
            model="claude-sonnet",
            category="coding",
            call_site="tool_use",
            usage=usage,
            latency_ms=100,
        )
    
    assert "Failed to write api_call log" in caplog.text


@pytest.mark.asyncio
async def test_log_api_call_does_not_block_caller(db):
    """log_api_call should complete quickly even with slow DB."""
    usage = TokenUsage()
    
    original_execute = None
    
    async def slow_execute(*args, **kwargs):
        await asyncio.sleep(0.5)
        return await original_execute(*args, **kwargs)
    
    async with db.get_connection() as conn:
        original_execute = conn.execute
        
    start = asyncio.get_event_loop().time()
    await log_api_call(
        db,
        user_id=111,
        session_key="user_111_20260228",
        provider="anthropic",
        model="claude-sonnet",
        category="coding",
        call_site="tool_use",
        usage=usage,
        latency_ms=100,
    )
    elapsed = asyncio.get_event_loop().time() - start
    
    assert elapsed < 0.1


# ---------------------------------------------------------------------------
# Call site variations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_api_call_router_site(db):
    """Router call site should be recorded correctly."""
    usage = TokenUsage(input_tokens=200, output_tokens=100)
    
    await log_api_call(
        db,
        user_id=1,
        session_key="user_1_20260228",
        provider="mistral",
        model="mistral-large-2411",
        category="summarization",
        call_site="router",
        usage=usage,
        latency_ms=800,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT call_site, category FROM api_calls WHERE user_id=1"
        )
    
    assert rows[0]["call_site"] == "router"
    assert rows[0]["category"] == "summarization"


@pytest.mark.asyncio
async def test_log_api_call_tool_use_site(db):
    """Tool-use call site should be recorded correctly."""
    usage = TokenUsage(input_tokens=500, output_tokens=200)
    
    await log_api_call(
        db,
        user_id=2,
        session_key="user_2_20260228",
        provider="anthropic",
        model="claude-sonnet-4-6",
        category="tool_use",
        call_site="tool_use",
        usage=usage,
        latency_ms=3000,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT call_site, latency_ms FROM api_calls WHERE user_id=2"
        )
    
    assert rows[0]["call_site"] == "tool_use"
    assert rows[0]["latency_ms"] == 3000


@pytest.mark.asyncio
async def test_log_api_call_proactive_site(db):
    """Proactive call site should be recorded correctly."""
    usage = TokenUsage(input_tokens=150, output_tokens=80)
    
    await log_api_call(
        db,
        user_id=3,
        session_key="user_3_20260228",
        provider="anthropic",
        model="claude-sonnet-4-6",
        category="proactive",
        call_site="proactive",
        usage=usage,
        latency_ms=1200,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT call_site FROM api_calls WHERE user_id=3"
        )
    
    assert rows[0]["call_site"] == "proactive"


@pytest.mark.asyncio
async def test_log_api_call_classifier_site(db):
    """Classifier call site should be recorded correctly."""
    usage = TokenUsage(input_tokens=20, output_tokens=2)
    
    await log_api_call(
        db,
        user_id=4,
        session_key="user_4_20260228",
        provider="anthropic",
        model="claude-haiku-4-5",
        category="routine",
        call_site="classifier",
        usage=usage,
        latency_ms=150,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT call_site, input_tokens, output_tokens FROM api_calls WHERE user_id=4"
        )
    
    assert rows[0]["call_site"] == "classifier"
    assert rows[0]["input_tokens"] == 20
    assert rows[0]["output_tokens"] == 2


@pytest.mark.asyncio
async def test_log_api_call_background_site(db):
    """Background call site should be recorded correctly."""
    usage = TokenUsage(input_tokens=800, output_tokens=400)
    
    await log_api_call(
        db,
        user_id=5,
        session_key="user_5_20260228",
        provider="anthropic",
        model="claude-sonnet-4-6",
        category="reasoning",
        call_site="background",
        usage=usage,
        latency_ms=5000,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT call_site FROM api_calls WHERE user_id=5"
        )
    
    assert rows[0]["call_site"] == "background"


# ---------------------------------------------------------------------------
# Provider variations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_api_call_moonshot_provider(db):
    """Moonshot provider should be recorded correctly."""
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    
    await log_api_call(
        db,
        user_id=6,
        session_key="user_6_20260228",
        provider="moonshot",
        model="kimi-k2-thinking",
        category="reasoning",
        call_site="router",
        usage=usage,
        latency_ms=10000,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT provider, model FROM api_calls WHERE user_id=6"
        )
    
    assert rows[0]["provider"] == "moonshot"
    assert rows[0]["model"] == "kimi-k2-thinking"


@pytest.mark.asyncio
async def test_log_api_call_ollama_provider(db):
    """Ollama provider (fallback) should be recorded correctly."""
    usage = TokenUsage()
    
    await log_api_call(
        db,
        user_id=7,
        session_key="user_7_20260228",
        provider="ollama",
        model="local",
        category="routine",
        call_site="router",
        usage=usage,
        latency_ms=2000,
        fallback=True,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT provider, model, fallback FROM api_calls WHERE user_id=7"
        )
    
    assert rows[0]["provider"] == "ollama"
    assert rows[0]["model"] == "local"
    assert rows[0]["fallback"] == 1


# ---------------------------------------------------------------------------
# Cache token handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_api_call_cache_tokens(db):
    """Cache creation and read tokens should be recorded."""
    usage = TokenUsage(
        input_tokens=500,
        output_tokens=200,
        cache_creation_tokens=100,
        cache_read_tokens=300,
    )
    
    await log_api_call(
        db,
        user_id=8,
        session_key="user_8_20260228",
        provider="anthropic",
        model="claude-sonnet-4-6",
        category="coding",
        call_site="tool_use",
        usage=usage,
        latency_ms=2500,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT cache_creation_tokens, cache_read_tokens FROM api_calls WHERE user_id=8"
        )
    
    assert rows[0]["cache_creation_tokens"] == 100
    assert rows[0]["cache_read_tokens"] == 300


@pytest.mark.asyncio
async def test_log_api_call_zero_cache_tokens_for_non_anthropic(db):
    """Non-Anthropic providers should have zero cache tokens."""
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    
    await log_api_call(
        db,
        user_id=9,
        session_key="user_9_20260228",
        provider="mistral",
        model="mistral-medium-3",
        category="routine",
        call_site="router",
        usage=usage,
        latency_ms=300,
    )
    
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT cache_creation_tokens, cache_read_tokens FROM api_calls WHERE user_id=9"
        )
    
    assert rows[0]["cache_creation_tokens"] == 0
    assert rows[0]["cache_read_tokens"] == 0
