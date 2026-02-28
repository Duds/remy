"""
Cost analyzer for API usage.

Queries the api_calls table and computes estimated costs using the price table.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..memory.database import DatabaseManager
from .prices import PRICE_TABLE_DATE, PRICES, estimate_cache_savings, estimate_cost

logger = logging.getLogger(__name__)


@dataclass
class ModelUsage:
    """Aggregated usage for a single model."""

    provider: str
    model: str
    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def estimated_cost(self) -> float:
        return estimate_cost(
            self.model,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_creation_tokens,
        )

    @property
    def cache_savings(self) -> float:
        return estimate_cache_savings(self.model, self.cache_read_tokens)

    @property
    def is_known_model(self) -> bool:
        return self.model in PRICES


@dataclass
class ProviderUsage:
    """Aggregated usage for a provider (may have multiple models)."""

    provider: str
    models: list[ModelUsage] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return sum(m.call_count for m in self.models)

    @property
    def total_input_tokens(self) -> int:
        return sum(m.input_tokens for m in self.models)

    @property
    def total_output_tokens(self) -> int:
        return sum(m.output_tokens for m in self.models)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(m.cache_read_tokens for m in self.models)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(m.cache_creation_tokens for m in self.models)

    @property
    def estimated_cost(self) -> float:
        return sum(m.estimated_cost for m in self.models)

    @property
    def cache_savings(self) -> float:
        return sum(m.cache_savings for m in self.models)


@dataclass
class CostSummary:
    """Complete cost summary for a period."""

    user_id: int
    period: str
    start_date: datetime
    end_date: datetime
    providers: list[ProviderUsage] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return sum(p.total_calls for p in self.providers)

    @property
    def total_cost(self) -> float:
        return sum(p.estimated_cost for p in self.providers)

    @property
    def total_savings(self) -> float:
        return sum(p.cache_savings for p in self.providers)


def _parse_period(period: str) -> tuple[datetime, datetime]:
    """Parse period string ('7d', '30d', '90d', 'all') to UTC (start, end)."""
    now = datetime.now(timezone.utc)
    p = period.lower().strip()
    if p == "7d":
        return now - timedelta(days=7), now
    if p in ("30d", "month"):
        return now - timedelta(days=30), now
    if p == "90d":
        return now - timedelta(days=90), now
    if p == "all":
        return datetime(2020, 1, 1, tzinfo=timezone.utc), now
    if p.endswith("d") and p[:-1].isdigit():
        return now - timedelta(days=int(p[:-1])), now
    return now - timedelta(days=30), now


def _format_tokens(count: int) -> str:
    """Format token count with K/M suffix."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)


def _format_cost(amount: float) -> str:
    """Format cost with ~ prefix and appropriate precision."""
    if amount < 0.01:
        return f"~${amount:.4f}"
    if amount < 1.00:
        return f"~${amount:.2f}"
    return f"~${amount:.2f}"


class CostAnalyzer:
    """Analyzes API call costs from the api_calls table."""

    # Provider display configuration
    PROVIDER_EMOJI = {
        "anthropic": "🟠",
        "mistral": "🔵",
        "moonshot": "🟡",
        "ollama": "🟢",
    }
    PROVIDER_ORDER = ["anthropic", "mistral", "moonshot", "ollama"]

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get_cost_summary(self, user_id: int, period: str = "30d") -> CostSummary:
        """
        Query api_calls and compute cost summary for the period.

        Returns a CostSummary with per-provider and per-model breakdowns.
        """
        start, end = _parse_period(period)

        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT provider, model,
                       SUM(input_tokens) AS input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(cache_creation_tokens) AS cache_creation_tokens,
                       SUM(cache_read_tokens) AS cache_read_tokens,
                       COUNT(*) AS call_count
                FROM api_calls
                WHERE user_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                GROUP BY provider, model
                ORDER BY provider, model
                """,
                (user_id, start.isoformat(), end.isoformat()),
            )

        providers_dict: dict[str, ProviderUsage] = {}

        for row in rows:
            provider = row["provider"]
            if provider not in providers_dict:
                providers_dict[provider] = ProviderUsage(provider=provider)

            model_usage = ModelUsage(
                provider=provider,
                model=row["model"],
                call_count=row["call_count"],
                input_tokens=row["input_tokens"] or 0,
                output_tokens=row["output_tokens"] or 0,
                cache_creation_tokens=row["cache_creation_tokens"] or 0,
                cache_read_tokens=row["cache_read_tokens"] or 0,
            )
            providers_dict[provider].models.append(model_usage)

        providers = sorted(
            providers_dict.values(),
            key=lambda p: (
                self.PROVIDER_ORDER.index(p.provider)
                if p.provider in self.PROVIDER_ORDER
                else 99
            ),
        )

        return CostSummary(
            user_id=user_id,
            period=period,
            start_date=start,
            end_date=end,
            providers=providers,
        )

    def format_cost_message(self, summary: CostSummary) -> str:
        """Format a CostSummary into a Telegram-ready Markdown message."""
        if summary.total_calls == 0:
            return (
                "_No API calls recorded for this period. "
                "Analytics data is collected from the date of your upgrade._"
            )

        lines: list[str] = []

        period_label = self._period_label(summary.period)
        start_str = summary.start_date.strftime("%d %b")
        end_str = summary.end_date.strftime("%d %b %Y")
        lines.append(f"💰 *Estimated AI Costs — {period_label}*")
        lines.append(f"_{start_str} – {end_str} · {summary.total_calls} API calls_\n")

        for provider_usage in summary.providers:
            emoji = self.PROVIDER_EMOJI.get(provider_usage.provider, "⚪")
            provider_name = provider_usage.provider.capitalize()

            if provider_usage.provider == "ollama":
                lines.append(
                    f"{emoji} *{provider_name} (local)* × {provider_usage.total_calls} calls — $0.00"
                )
                continue

            lines.append(f"{emoji} *{provider_name}*")

            for model in provider_usage.models:
                model_label = model.model
                if not model.is_known_model:
                    model_label += " (unknown)"
                lines.append(f"  {model_label} × {model.call_count} calls")

                input_cost = estimate_cost(model.model, model.input_tokens, 0, 0, 0)
                output_cost = estimate_cost(model.model, 0, model.output_tokens, 0, 0)

                lines.append(
                    f"  Input:  {_format_tokens(model.input_tokens)} tokens"
                    f"    {_format_cost(input_cost)}"
                )
                lines.append(
                    f"  Output: {_format_tokens(model.output_tokens)} tokens"
                    f"    {_format_cost(output_cost)}"
                )

                if model.cache_read_tokens > 0:
                    cache_cost = estimate_cost(
                        model.model, 0, 0, model.cache_read_tokens, 0
                    )
                    savings = model.cache_savings
                    lines.append(
                        f"  Cache reads: {_format_tokens(model.cache_read_tokens)} tokens"
                        f"   {_format_cost(cache_cost)}  _(saved {_format_cost(savings)})_"
                    )

                if model.cache_creation_tokens > 0:
                    cache_write_cost = estimate_cost(
                        model.model, 0, 0, 0, model.cache_creation_tokens
                    )
                    lines.append(
                        f"  Cache writes: {_format_tokens(model.cache_creation_tokens)} tokens"
                        f"   {_format_cost(cache_write_cost)}"
                    )

            subtotal = provider_usage.estimated_cost
            lines.append(f"  *Subtotal:* {_format_cost(subtotal)}")
            lines.append("")

        lines.append("━━━━━━━━━━━━")
        lines.append(f"*Total:* {_format_cost(summary.total_cost)}")

        if summary.total_savings > 0:
            lines.append(f"_Cache savings: {_format_cost(summary.total_savings)}_")

        lines.append(f"\n_Prices as of {PRICE_TABLE_DATE}. Actual billing may differ._")

        return "\n".join(lines)

    def _period_label(self, period: str) -> str:
        labels = {
            "7d": "Last 7 days",
            "30d": "Last 30 days",
            "month": "Last 30 days",
            "90d": "Last 90 days",
            "all": "All time",
        }
        p = period.lower()
        if p in labels:
            return labels[p]
        if p.endswith("d") and p[:-1].isdigit():
            return f"Last {p[:-1]} days"
        return "Last 30 days"
