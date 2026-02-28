# User Story: Anthropic Admin API — Authoritative Spend Data

⬜ Backlog

## Summary

As Dale, I want Remy to optionally pull authoritative token usage and cost data from Anthropic's Admin API so that `/costs` can show ground-truth figures for Claude calls rather than local estimates — when an Admin API key is configured.

---

## Background

Anthropic provides a full programmatic usage and billing API, which is unique among the three services (Mistral and Moonshot have no equivalent):

- `GET /v1/organizations/usage_report/messages` — token usage grouped by model, date, workspace, etc.
- `GET /v1/organizations/cost_report` — cost in USD, grouped by workspace.

**Authentication:** These endpoints require an **Admin API key** (`sk-ant-admin...`), separate from the standard API key used for inference. Admin keys are provisioned via the Claude Console under Organization Settings → API Keys. They are not available on individual (non-organisation) accounts.

**Data freshness:** ~5 minutes after a request completes.

Currently, `/costs` (see `US-analytics-costs-command.md`) uses locally-computed estimates from the `api_calls` table. This story adds an optional supplementary layer: if `ANTHROPIC_ADMIN_API_KEY` is configured, the `/costs` command can show authoritative Anthropic data alongside (or instead of) the local estimate, and flag any discrepancy.

**Covers:** ANA-009.

**Depends on:** `US-analytics-costs-command.md` (the `/costs` command must exist first).

---

## Acceptance Criteria

1. **New optional config: `ANTHROPIC_ADMIN_API_KEY`.** If not set, all Admin API behaviour is silently skipped. No error shown to the user; local estimates are used as normal.

2. **`AnthropicAdminClient` class.** Located at `remy/ai/anthropic_admin_client.py`. Calls:
   - `GET https://api.anthropic.com/v1/organizations/usage_report/messages`
   - `GET https://api.anthropic.com/v1/organizations/cost_report`

3. **Usage report query parameters used:**
   - `starting_at` / `ending_at`: RFC3339 timestamps for the requested period.
   - `bucket_width=1d`: daily granularity.
   - `group_by[]=model`: breakdown by model.

4. **Returns structured data** including per-model: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, and estimated USD cost from the cost report.

5. **Called on-demand only.** The Admin API is queried when `/costs` is invoked, not on every message. No polling.

6. **`/costs` output shows "Anthropic (actual)" when Admin API data is available**, clearly distinguished from the local estimate. If both are available, show the authoritative figure with the local estimate in parentheses for comparison.

7. **Discrepancy flag.** If local estimate and Admin API figure differ by more than 15%, a note is shown: `⚠️ Local estimate diverges from Anthropic API by X% — consider updating the price table.`

8. **Pagination handled.** The usage report may return multiple pages. `AnthropicAdminClient` follows `next_page` tokens until exhausted for the requested period.

9. **Auth errors handled gracefully.** If the Admin key is invalid or the account is not an org account, the error is logged at WARNING level and `/costs` falls back to local estimates with a note: `_(Admin API unavailable — showing estimates)_`.

10. **Priority Tier costs not included.** The cost report endpoint does not include Priority Tier spend — this limitation is documented in the output with a note if the org uses Priority Tier.

---

## Implementation

**Files to create/modify:**
- `remy/ai/anthropic_admin_client.py` — new `AnthropicAdminClient`
- `remy/config.py` — add `anthropic_admin_api_key: str = ""`
- `remy/analytics/costs.py` — integrate Admin API data into `CostAnalyzer`
- `remy/bot/handlers.py` — pass admin client to cost command if configured

**`AnthropicAdminClient` skeleton:**

```python
class AnthropicAdminClient:
    BASE_URL = "https://api.anthropic.com"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, admin_api_key: str) -> None:
        self._key = admin_api_key
        self._headers = {
            "x-api-key": admin_api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }

    async def get_usage(
        self,
        starting_at: datetime,
        ending_at: datetime,
    ) -> list[dict]:
        """
        Returns list of usage buckets: [{model, input_tokens, output_tokens,
        cache_creation_input_tokens, cache_read_input_tokens, start_time}, ...]
        Handles pagination automatically.
        """
        params = {
            "starting_at": starting_at.isoformat(),
            "ending_at": ending_at.isoformat(),
            "bucket_width": "1d",
            "group_by[]": "model",
            "limit": 100,
        }
        results = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                resp = await client.get(
                    f"{self.BASE_URL}/v1/organizations/usage_report/messages",
                    headers=self._headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                results.extend(data.get("data", []))
                if not data.get("next_page"):
                    break
                params["page"] = data["next_page"]
        return results

    async def get_cost(
        self,
        starting_at: datetime,
        ending_at: datetime,
    ) -> dict:
        """Returns cost report data for the period."""
        ...
```

**Integration in `CostAnalyzer`:**

```python
async def get_cost_summary(self, user_id, period, admin_client=None):
    # 1. Get local estimate from api_calls (always)
    local = await self._query_local(user_id, period)

    # 2. Optionally get authoritative Anthropic data
    anthropic_actual = None
    if admin_client:
        try:
            anthropic_actual = await admin_client.get_usage(start, end)
        except Exception as e:
            logger.warning("Admin API failed: %s", e)

    return self._format(local, anthropic_actual)
```

### Notes
- The Admin API key must be kept separate from the inference key. Never pass it to `ClaudeClient`. Add it to `.env` as `ANTHROPIC_ADMIN_API_KEY`.
- The `x-api-key` header is used (same header name as inference), but the key prefix is `sk-ant-admin` for Admin keys.
- Test with a small date range first (`bucket_width=1d`, 1-day window) before querying longer periods.
- This story is clearly lower priority than `US-analytics-costs-command.md` — the local estimate is useful without this. Mark as "nice to have" if an org Admin key is not available.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `ANTHROPIC_ADMIN_API_KEY` not set | `/costs` shows local estimates only, no error |
| Admin key set, valid org account | `/costs` shows "Anthropic (actual)" section |
| Admin key invalid / not org account | WARNING logged, falls back to local estimate with note |
| Usage spans multiple pages | All pages fetched, totals correct |
| Local estimate within 15% of Admin API | No discrepancy warning |
| Local estimate diverges > 15% | Discrepancy note shown with percentage |
| Admin API times out | Logged at WARNING, graceful fallback to local estimate |
| Period has no Anthropic calls | Returns empty usage list, no crash |

---

## Out of Scope

- Workspace-level breakdown (single-workspace assumption for now).
- Priority Tier cost tracking (not available in the cost report endpoint per Anthropic docs).
- Automatic price table updates based on Admin API cost data.
- Cost alerts or budget thresholds (separate story).
- Admin API integration for Mistral or Moonshot (neither has an equivalent endpoint).
