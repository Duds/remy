"""
Anthropic Admin API client — authoritative usage and cost data.

Uses Admin API key (sk-ant-admin...) for GET usage_report/messages and cost_report.
Called on-demand when /costs is invoked (US-analytics-anthropic-admin-api).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DISCREPANCY_PCT_THRESHOLD = 15.0


class AnthropicAdminClient:
    """
    Client for Anthropic Admin API (usage and cost reports).

    Requires an Admin API key (sk-ant-admin...); not the inference API key.
    """

    def __init__(self, admin_api_key: str) -> None:
        self._key = admin_api_key.strip()
        self._headers = {
            "x-api-key": self._key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

    async def get_usage(
        self,
        starting_at: datetime,
        ending_at: datetime,
    ) -> list[dict[str, Any]]:
        """
        Fetch usage report (messages) for the period; paginates automatically.

        Returns a flat list of bucket items: each has model, uncached_input_tokens,
        output_tokens, cache_read_input_tokens, cache_creation (ephemeral_1h/5m), etc.
        """
        if not self._key:
            return []

        params: dict[str, Any] = {
            "starting_at": starting_at.isoformat(),
            "ending_at": ending_at.isoformat(),
            "bucket_width": "1d",
            "group_by[]": "model",
            "limit": 100,
        }
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                resp = await client.get(
                    f"{BASE_URL}/v1/organizations/usage_report/messages",
                    headers=self._headers,
                    params=params,
                )
                if resp.status_code != 200:
                    resp.raise_for_status()
                data = resp.json()
                for bucket in data.get("data", []):
                    for item in bucket.get("results", []):
                        results.append({
                            **item,
                            "starting_at": bucket.get("starting_at"),
                            "ending_at": bucket.get("ending_at"),
                        })
                if not data.get("has_more") or not data.get("next_page"):
                    break
                params = {"page": data["next_page"], **{k: v for k, v in params.items() if k != "page"}}

        return results

    async def get_cost_report(
        self,
        starting_at: datetime,
        ending_at: datetime,
    ) -> list[dict[str, Any]]:
        """
        Fetch cost report for the period; paginates automatically.

        Returns a flat list of cost items (amount in USD decimal string, model, etc.).
        """
        if not self._key:
            return []

        params: dict[str, Any] = {
            "starting_at": starting_at.isoformat(),
            "ending_at": ending_at.isoformat(),
            "bucket_width": "1d",
            "limit": 100,
        }
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                resp = await client.get(
                    f"{BASE_URL}/v1/organizations/cost_report",
                    headers=self._headers,
                    params=params,
                )
                if resp.status_code != 200:
                    resp.raise_for_status()
                data = resp.json()
                for bucket in data.get("data", []):
                    for item in bucket.get("results", []):
                        results.append({
                            **item,
                            "starting_at": bucket.get("starting_at"),
                            "ending_at": bucket.get("ending_at"),
                        })
                if not data.get("has_more") or not data.get("next_page"):
                    break
                params = {"page": data["next_page"], **{k: v for k, v in params.items() if k != "page"}}

        return results


def sum_cost_report_usd(cost_items: list[dict[str, Any]]) -> float:
    """
    Sum amount from cost_report results.

    amount is in lowest currency units (e.g. cents) as decimal string;
    e.g. "123.45" USD = $1.2345. We convert to dollars when currency is USD.
    """
    total = 0.0
    for item in cost_items:
        amt = item.get("amount")
        currency = (item.get("currency") or "USD").upper()
        if amt is not None:
            try:
                val = float(amt)
                if currency == "USD":
                    val /= 100.0
                total += val
            except (TypeError, ValueError):
                pass
    return round(total, 4)
