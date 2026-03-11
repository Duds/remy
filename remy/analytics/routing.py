"""
Routing breakdown analyzer — category, fallback rate, classifier overhead.

Queries api_calls and formats a /routing report (US-analytics-routing-breakdown).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from ..memory.database import DatabaseManager
from .prices import estimate_cost

logger = logging.getLogger(__name__)

# Classifier overhead as fraction of total spend above which we suggest lighter heuristics
CLASSIFIER_OVERHEAD_WARNING_THRESHOLD = 0.10
# Fallback rate above which we show a warning
FALLBACK_WARNING_THRESHOLD = 0.05

# User-initiated call sites for "By Category"; others go to "Other Call Sites"
ROUTER_CALL_SITES = {"router", "tool_use", "complete"}
OTHER_CALL_SITES = {"proactive", "background"}


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
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def _format_cost(amount: float) -> str:
    if amount < 0.01:
        return f"~${amount:.4f}"
    if amount < 1.00:
        return f"~${amount:.2f}"
    return f"~${amount:.2f}"


@dataclass
class CategoryRow:
    """One row in the category or other-call-sites table."""

    category_or_site: str
    call_count: int
    provider: str
    model: str
    more_models: int  # additional provider/model combos for this category
    avg_tokens: float
    avg_cost: float


@dataclass
class RoutingReport:
    """Full routing breakdown for a period."""

    user_id: int
    period: str
    start_date: datetime
    end_date: datetime
    total_calls: int
    total_tokens: int
    total_cost: float
    by_category: list[CategoryRow] = field(default_factory=list)
    other_sites: list[CategoryRow] = field(default_factory=list)
    classifier_calls: int = 0
    classifier_input_tokens: int = 0
    classifier_output_tokens: int = 0
    classifier_cost: float = 0.0
    fallback_calls: int = 0
    fallback_pct: float = 0.0


class RoutingAnalyzer:
    """Analyzes routing and classifier usage from api_calls."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get_routing_report(self, user_id: int, period: str = "30d") -> RoutingReport:
        """
        Build routing report: by category, other call sites, classifier overhead, fallback rate.
        """
        start, end = _parse_period(period)

        async with self._db.get_connection() as conn:
            # Per (category, call_site, provider, model) aggregation
            rows = await conn.execute_fetchall(
                """
                SELECT
                    category,
                    call_site,
                    provider,
                    model,
                    COUNT(*) AS calls,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(cache_creation_tokens) AS cache_creation_tokens,
                    SUM(cache_read_tokens) AS cache_read_tokens,
                    SUM(input_tokens + output_tokens) AS total_tokens,
                    AVG(input_tokens + output_tokens) AS avg_tokens,
                    SUM(fallback) AS fallback_calls
                FROM api_calls
                WHERE user_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                GROUP BY category, call_site, provider, model
                ORDER BY calls DESC
                """,
                (user_id, start.isoformat(), end.isoformat()),
            )

            # Classifier overhead
            classifier_rows = await conn.execute_fetchall(
                """
                SELECT
                    COUNT(*) AS calls,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens
                FROM api_calls
                WHERE user_id = ?
                  AND call_site = 'classifier'
                  AND timestamp >= ?
                  AND timestamp < ?
                """,
                (user_id, start.isoformat(), end.isoformat()),
            )

        # Aggregate totals
        total_calls = 0
        total_tokens = 0
        total_cost = 0.0
        fallback_calls = 0

        # Build per-(category or call_site) primary model and counts
        category_agg: dict[str, list[tuple[str, str, int, float, float, int]]] = {}
        for row in rows:
            cat = row["category"] or "unknown"
            call_site = (row["call_site"] or "router").lower()
            provider = row["provider"] or "unknown"
            model = row["model"] or "unknown"
            calls = row["calls"]
            inp = row["input_tokens"] or 0
            out = row["output_tokens"] or 0
            cache_cre = row["cache_creation_tokens"] or 0
            cache_read = row["cache_read_tokens"] or 0
            tot_tok = row["total_tokens"] or 0
            avg_tok = row["avg_tokens"] or 0
            fb = row["fallback_calls"] or 0

            total_calls += calls
            total_tokens += tot_tok
            fallback_calls += fb

            bucket_cost = estimate_cost(model, inp, out, cache_read, cache_cre)
            total_cost += bucket_cost
            avg_cost = bucket_cost / calls if calls else 0

            key = cat if call_site in ROUTER_CALL_SITES else f"site:{call_site}"
            if key not in category_agg:
                category_agg[key] = []
            category_agg[key].append((provider, model, calls, avg_tok, avg_cost, fb))

        # Classifier
        clf_calls = 0
        clf_in = 0
        clf_out = 0
        if classifier_rows:
            r = classifier_rows[0]
            clf_calls = r["calls"] or 0
            clf_in = r["input_tokens"] or 0
            clf_out = r["output_tokens"] or 0
        # Classifier typically uses a small model; use haiku for estimate
        classifier_cost = estimate_cost("claude-haiku-4-5", clf_in, clf_out)

        fallback_pct = (fallback_calls / total_calls * 100.0) if total_calls else 0.0

        # Build category table: one row per category/site with primary model
        by_category: list[CategoryRow] = []
        other_sites: list[CategoryRow] = []

        for key, buckets in category_agg.items():
            # Primary = highest call count
            buckets_sorted = sorted(buckets, key=lambda x: -x[2])
            primary = buckets_sorted[0]
            provider, model, calls, avg_tok, avg_cost, _ = primary
            more = len(buckets_sorted) - 1
            # Average tokens/cost across this key (simplified: use primary bucket)
            row = CategoryRow(
                category_or_site=key.replace("site:", ""),
                call_count=calls,
                provider=provider,
                model=model,
                more_models=more,
                avg_tokens=avg_tok,
                avg_cost=avg_cost,
            )
            if key.startswith("site:"):
                other_sites.append(row)
            else:
                by_category.append(row)

        # Sort by category name for stable output; other_sites by name
        by_category.sort(key=lambda r: (r.category_or_site.lower(), -r.call_count))
        other_sites.sort(key=lambda r: (r.category_or_site.lower(), -r.call_count))

        return RoutingReport(
            user_id=user_id,
            period=period,
            start_date=start,
            end_date=end,
            total_calls=total_calls,
            total_tokens=total_tokens,
            total_cost=total_cost,
            by_category=by_category,
            other_sites=other_sites,
            classifier_calls=clf_calls,
            classifier_input_tokens=clf_in,
            classifier_output_tokens=clf_out,
            classifier_cost=classifier_cost,
            fallback_calls=fallback_calls,
            fallback_pct=fallback_pct,
        )

    def format_routing_message(self, report: RoutingReport) -> str:
        """Format RoutingReport as Telegram Markdown."""
        if report.total_calls == 0:
            return (
                "_No API calls recorded for this period. "
                "Analytics data is collected from the date of your upgrade._"
            )

        lines: list[str] = []
        period_label = self._period_label(report.period)
        start_str = report.start_date.strftime("%d %b")
        end_str = report.end_date.strftime("%d %b %Y")

        lines.append(f"🔀 *Routing Breakdown — {period_label}*")
        lines.append(
            f"{report.total_calls} total calls · {_format_tokens(report.total_tokens)} tokens · "
            f"{_format_cost(report.total_cost)} estimated\n"
        )

        lines.append("📊 *By Category*")
        for r in report.by_category:
            model_str = f"{r.provider}-{r.model}" if r.provider != "unknown" else r.model
            if r.more_models:
                model_str += f" (+{r.more_models} more)"
            lines.append(
                f"{r.category_or_site:14} ×{r.call_count:4}  →  {model_str:28} "
                f"avg {_format_tokens(int(r.avg_tokens))} tok  {_format_cost(r.avg_cost)}/call"
            )

        if report.other_sites:
            lines.append("\n🤖 *Other Call Sites*")
            for r in report.other_sites:
                model_str = f"{r.provider}-{r.model}" if r.provider != "unknown" else r.model
                if r.more_models:
                    model_str += f" (+{r.more_models} more)"
                lines.append(
                    f"{r.category_or_site:14} ×{r.call_count:4}  →  {model_str:28} "
                    f"avg {_format_tokens(int(r.avg_tokens))} tok  {_format_cost(r.avg_cost)}/call"
                )

        lines.append("\n⚡ *Classifier Overhead*")
        clf_tok = report.classifier_input_tokens + report.classifier_output_tokens
        pct = (
            (report.classifier_cost / report.total_cost * 100.0)
            if report.total_cost > 0
            else 0.0
        )
        lines.append(
            f"{report.classifier_calls} calls · {_format_tokens(clf_tok)} tokens\n"
            f"Estimated cost: {_format_cost(report.classifier_cost)}  ({pct:.1f}% of total spend)"
        )
        if report.total_cost > 0 and report.classifier_cost / report.total_cost >= CLASSIFIER_OVERHEAD_WARNING_THRESHOLD:
            lines.append(
                "_Consider lighter-weight classification heuristics to reduce overhead._"
            )

        lines.append("\n⚠️ *Fallback Rate*")
        warn = " ⚠️" if report.fallback_pct > FALLBACK_WARNING_THRESHOLD * 100 else ""
        lines.append(
            f"{report.fallback_calls} calls fell back to Ollama ({report.fallback_pct:.1f}%)"
            f"{warn}"
        )
        if report.fallback_pct <= FALLBACK_WARNING_THRESHOLD * 100:
            lines.append(" — within normal range")

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
