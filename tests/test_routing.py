"""
Tests for US-analytics-routing-breakdown — RoutingAnalyzer and /routing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from remy.analytics.routing import RoutingAnalyzer, RoutingReport
from remy.memory.database import DatabaseManager


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh DB per test with api_calls table."""
    manager = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await manager.init()
    yield manager
    await manager.close()


async def _insert_api_call(
    db: DatabaseManager,
    user_id: int,
    provider: str,
    model: str,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    category: str = "routine",
    call_site: str = "router",
    fallback: int = 0,
    timestamp: datetime | None = None,
) -> None:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    async with db.get_connection() as conn:
        await conn.execute(
            """INSERT INTO api_calls
               (user_id, session_key, timestamp, provider, model, category, call_site,
                input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, latency_ms, fallback)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                "test-session",
                timestamp.isoformat(),
                provider,
                model,
                category,
                call_site,
                input_tokens,
                output_tokens,
                0,
                0,
                0,
                fallback,
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_get_routing_report_empty(db):
    """Empty api_calls should return zero totals."""
    analyzer = RoutingAnalyzer(db)
    report = await analyzer.get_routing_report(user_id=999, period="30d")
    assert report.total_calls == 0
    assert report.total_tokens == 0
    assert report.total_cost == 0.0
    assert len(report.by_category) == 0


@pytest.mark.asyncio
async def test_get_routing_report_by_category(db):
    """Category breakdown should aggregate by category and show primary model."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 2000, 1000, category="reasoning")
    await _insert_api_call(db, 1, "mistral", "mistral-medium-3", 1000, 500, category="routine")

    analyzer = RoutingAnalyzer(db)
    report = await analyzer.get_routing_report(user_id=1, period="30d")

    assert report.total_calls == 2
    assert report.total_tokens == 2000 + 1000 + 1000 + 500
    assert len(report.by_category) >= 1
    categories = {r.category_or_site: r for r in report.by_category}
    assert "reasoning" in categories or "routine" in categories


@pytest.mark.asyncio
async def test_format_routing_message_empty(db):
    """Empty report should format as no-data message."""
    analyzer = RoutingAnalyzer(db)
    report = await analyzer.get_routing_report(user_id=999, period="30d")
    msg = analyzer.format_routing_message(report)
    assert "No API calls" in msg or "no API calls" in msg.lower()


@pytest.mark.asyncio
async def test_format_routing_message_has_sections(db):
    """Non-empty report should include By Category and Classifier Overhead."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500, category="routine")
    analyzer = RoutingAnalyzer(db)
    report = await analyzer.get_routing_report(user_id=1, period="30d")
    msg = analyzer.format_routing_message(report)
    assert "Routing Breakdown" in msg
    assert "By Category" in msg
    assert "Classifier Overhead" in msg
    assert "Fallback Rate" in msg
