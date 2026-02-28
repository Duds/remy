"""
Tests for US-analytics-costs-command.

Covers:
- Price table and estimate_cost function
- CostAnalyzer.get_cost_summary() query
- CostAnalyzer.format_cost_message() output
- Period parsing
- Empty state handling
- Cache savings calculation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from remy.analytics.costs import CostAnalyzer, CostSummary, ModelUsage, ProviderUsage
from remy.analytics.prices import (
    PRICES,
    PRICE_TABLE_DATE,
    estimate_cache_savings,
    estimate_cost,
)
from remy.memory.database import DatabaseManager


# ---------------------------------------------------------------------------
# Price table tests
# ---------------------------------------------------------------------------


def test_prices_contains_anthropic_models():
    """Anthropic models should be in the price table."""
    assert "claude-sonnet-4-6" in PRICES
    assert "claude-haiku-4-5" in PRICES
    assert "claude-opus-4-6" in PRICES


def test_prices_contains_mistral_models():
    """Mistral models should be in the price table."""
    assert "mistral-medium-3" in PRICES
    assert "mistral-large-2411" in PRICES


def test_prices_contains_moonshot_models():
    """Moonshot models should be in the price table."""
    assert "moonshot-v1-8k" in PRICES
    assert "kimi-k2-thinking" in PRICES


def test_anthropic_prices_have_cache_fields():
    """Anthropic models should have cache pricing."""
    sonnet = PRICES["claude-sonnet-4-6"]
    assert "cache_read" in sonnet
    assert "cache_write" in sonnet
    assert sonnet["cache_read"] < sonnet["input"]


def test_price_table_date_is_set():
    """Price table date should be set for display."""
    assert PRICE_TABLE_DATE
    assert "2026" in PRICE_TABLE_DATE or "2025" in PRICE_TABLE_DATE


# ---------------------------------------------------------------------------
# estimate_cost tests
# ---------------------------------------------------------------------------


def test_estimate_cost_basic():
    """Basic cost estimation for input/output tokens."""
    cost = estimate_cost("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert cost == 3.00

    cost = estimate_cost("claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000)
    assert cost == 15.00


def test_estimate_cost_combined():
    """Combined input and output tokens."""
    cost = estimate_cost(
        "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert cost == 18.00


def test_estimate_cost_with_cache():
    """Cost estimation including cache tokens."""
    cost = estimate_cost(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=1_000_000,
        cache_creation_tokens=1_000_000,
    )
    expected = 3.00 + 0.30 + 3.75
    assert cost == expected


def test_estimate_cost_unknown_model():
    """Unknown models should return 0.0."""
    cost = estimate_cost("unknown-model", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.0


def test_estimate_cost_ollama():
    """Ollama (local) should return 0.0."""
    cost = estimate_cost("local", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.0


def test_estimate_cost_small_amounts():
    """Small token amounts should be calculated correctly."""
    cost = estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    expected = (1000 / 1_000_000 * 3.00) + (500 / 1_000_000 * 15.00)
    assert abs(cost - expected) < 0.0001


# ---------------------------------------------------------------------------
# estimate_cache_savings tests
# ---------------------------------------------------------------------------


def test_estimate_cache_savings_anthropic():
    """Cache savings for Anthropic models."""
    savings = estimate_cache_savings("claude-sonnet-4-6", cache_read_tokens=1_000_000)
    expected = 3.00 - 0.30
    assert savings == expected


def test_estimate_cache_savings_no_cache_pricing():
    """Models without cache pricing should return 0."""
    savings = estimate_cache_savings("mistral-medium-3", cache_read_tokens=1_000_000)
    assert savings == 0.0


def test_estimate_cache_savings_unknown_model():
    """Unknown models should return 0."""
    savings = estimate_cache_savings("unknown-model", cache_read_tokens=1_000_000)
    assert savings == 0.0


# ---------------------------------------------------------------------------
# CostAnalyzer tests with database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh DB per test."""
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    await manager.init()
    yield manager
    await manager.close()


async def _insert_api_call(
    db,
    user_id: int,
    provider: str,
    model: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    timestamp: datetime | None = None,
):
    """Helper to insert test api_call rows."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    async with db.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO api_calls
              (user_id, session_key, timestamp, provider, model, category,
               call_site, input_tokens, output_tokens, cache_creation_tokens,
               cache_read_tokens, latency_ms, fallback)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                f"user_{user_id}_20260228",
                timestamp.isoformat(),
                provider,
                model,
                "test",
                "router",
                input_tokens,
                output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                100,
                0,
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_get_cost_summary_empty(db):
    """Empty api_calls should return zero totals."""
    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=999, period="30d")

    assert summary.total_calls == 0
    assert summary.total_cost == 0.0
    assert len(summary.providers) == 0


@pytest.mark.asyncio
async def test_get_cost_summary_single_provider(db):
    """Single provider usage should be summarised correctly."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 2000, 1000)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")

    assert summary.total_calls == 2
    assert len(summary.providers) == 1
    assert summary.providers[0].provider == "anthropic"
    assert summary.providers[0].total_input_tokens == 3000
    assert summary.providers[0].total_output_tokens == 1500


@pytest.mark.asyncio
async def test_get_cost_summary_multiple_providers(db):
    """Multiple providers should be grouped correctly."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)
    await _insert_api_call(db, 1, "mistral", "mistral-medium-3", 2000, 1000)
    await _insert_api_call(db, 1, "ollama", "local", 500, 250)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")

    assert summary.total_calls == 3
    assert len(summary.providers) == 3

    providers_by_name = {p.provider: p for p in summary.providers}
    assert "anthropic" in providers_by_name
    assert "mistral" in providers_by_name
    assert "ollama" in providers_by_name


@pytest.mark.asyncio
async def test_get_cost_summary_multiple_models_same_provider(db):
    """Multiple models from same provider should be listed separately."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)
    await _insert_api_call(db, 1, "anthropic", "claude-haiku-4-5", 2000, 1000)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")

    assert len(summary.providers) == 1
    assert len(summary.providers[0].models) == 2


@pytest.mark.asyncio
async def test_get_cost_summary_respects_period(db):
    """Period filtering should work correctly."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)

    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500, timestamp=now)
    await _insert_api_call(
        db, 1, "anthropic", "claude-sonnet-4-6", 2000, 1000, timestamp=old
    )

    analyzer = CostAnalyzer(db)
    summary_30d = await analyzer.get_cost_summary(user_id=1, period="30d")
    summary_all = await analyzer.get_cost_summary(user_id=1, period="all")

    assert summary_30d.total_calls == 1
    assert summary_all.total_calls == 2


@pytest.mark.asyncio
async def test_get_cost_summary_respects_user_id(db):
    """User ID filtering should work correctly."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)
    await _insert_api_call(db, 2, "anthropic", "claude-sonnet-4-6", 2000, 1000)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")

    assert summary.total_calls == 1
    assert summary.providers[0].total_input_tokens == 1000


@pytest.mark.asyncio
async def test_get_cost_summary_cache_tokens(db):
    """Cache tokens should be aggregated correctly."""
    await _insert_api_call(
        db,
        1,
        "anthropic",
        "claude-sonnet-4-6",
        1000,
        500,
        cache_read_tokens=300,
        cache_creation_tokens=100,
    )

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")

    model = summary.providers[0].models[0]
    assert model.cache_read_tokens == 300
    assert model.cache_creation_tokens == 100


# ---------------------------------------------------------------------------
# format_cost_message tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_cost_message_empty(db):
    """Empty summary should show appropriate message."""
    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=999, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "No API calls recorded" in msg


@pytest.mark.asyncio
async def test_format_cost_message_has_header(db):
    """Message should have cost header."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "Estimated AI Costs" in msg
    assert "Last 30 days" in msg


@pytest.mark.asyncio
async def test_format_cost_message_shows_providers(db):
    """Message should show provider sections."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)
    await _insert_api_call(db, 1, "mistral", "mistral-medium-3", 2000, 1000)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "Anthropic" in msg
    assert "Mistral" in msg


@pytest.mark.asyncio
async def test_format_cost_message_shows_ollama_as_free(db):
    """Ollama should be shown as $0.00 (local)."""
    await _insert_api_call(db, 1, "ollama", "local", 1000, 500)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "Ollama (local)" in msg
    assert "$0.00" in msg


@pytest.mark.asyncio
async def test_format_cost_message_shows_total(db):
    """Message should show total cost."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1_000_000, 100_000)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "Total:" in msg
    assert "~$" in msg


@pytest.mark.asyncio
async def test_format_cost_message_shows_cache_savings(db):
    """Cache savings should be shown when present."""
    await _insert_api_call(
        db,
        1,
        "anthropic",
        "claude-sonnet-4-6",
        1_000_000,
        100_000,
        cache_read_tokens=500_000,
    )

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "Cache reads:" in msg
    assert "saved" in msg


@pytest.mark.asyncio
async def test_format_cost_message_shows_price_disclaimer(db):
    """Message should include price disclaimer."""
    await _insert_api_call(db, 1, "anthropic", "claude-sonnet-4-6", 1000, 500)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "Actual billing may differ" in msg
    assert PRICE_TABLE_DATE in msg


@pytest.mark.asyncio
async def test_format_cost_message_unknown_model(db):
    """Unknown models should be marked."""
    await _insert_api_call(db, 1, "anthropic", "unknown-claude-model", 1000, 500)

    analyzer = CostAnalyzer(db)
    summary = await analyzer.get_cost_summary(user_id=1, period="30d")
    msg = analyzer.format_cost_message(summary)

    assert "(unknown)" in msg


# ---------------------------------------------------------------------------
# ModelUsage and ProviderUsage dataclass tests
# ---------------------------------------------------------------------------


def test_model_usage_estimated_cost():
    """ModelUsage should calculate estimated cost."""
    usage = ModelUsage(
        provider="anthropic",
        model="claude-sonnet-4-6",
        call_count=10,
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    expected = 3.00 + 7.50
    assert usage.estimated_cost == expected


def test_model_usage_cache_savings():
    """ModelUsage should calculate cache savings."""
    usage = ModelUsage(
        provider="anthropic",
        model="claude-sonnet-4-6",
        call_count=10,
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=1_000_000,
    )
    expected = 3.00 - 0.30
    assert usage.cache_savings == expected


def test_model_usage_is_known_model():
    """ModelUsage should report if model is known."""
    known = ModelUsage(provider="anthropic", model="claude-sonnet-4-6")
    unknown = ModelUsage(provider="anthropic", model="unknown-model")

    assert known.is_known_model is True
    assert unknown.is_known_model is False


def test_provider_usage_totals():
    """ProviderUsage should aggregate model totals."""
    provider = ProviderUsage(
        provider="anthropic",
        models=[
            ModelUsage(
                provider="anthropic",
                model="claude-sonnet-4-6",
                call_count=5,
                input_tokens=1000,
                output_tokens=500,
            ),
            ModelUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                call_count=10,
                input_tokens=2000,
                output_tokens=1000,
            ),
        ],
    )

    assert provider.total_calls == 15
    assert provider.total_input_tokens == 3000
    assert provider.total_output_tokens == 1500


# ---------------------------------------------------------------------------
# Period parsing tests
# ---------------------------------------------------------------------------


def test_period_label_7d():
    """7d period should have correct label."""
    analyzer = CostAnalyzer.__new__(CostAnalyzer)
    assert analyzer._period_label("7d") == "Last 7 days"


def test_period_label_30d():
    """30d period should have correct label."""
    analyzer = CostAnalyzer.__new__(CostAnalyzer)
    assert analyzer._period_label("30d") == "Last 30 days"


def test_period_label_all():
    """all period should have correct label."""
    analyzer = CostAnalyzer.__new__(CostAnalyzer)
    assert analyzer._period_label("all") == "All time"


def test_period_label_custom():
    """Custom period should have correct label."""
    analyzer = CostAnalyzer.__new__(CostAnalyzer)
    assert analyzer._period_label("14d") == "Last 14 days"
