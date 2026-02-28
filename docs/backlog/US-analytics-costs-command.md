# User Story: /costs — Token & Spend Summary Command

✅ Done

## Summary

As Dale, I want a `/costs` Telegram command that shows my token consumption and estimated spend across all three AI services for a chosen period so that I know what I'm actually spending on Remy.

---

## Background

After `US-analytics-call-log.md` is implemented, every API call is recorded in the `api_calls` table with full token counts. This story turns that data into a user-facing Telegram command.

There is no universal billing API across all three services. Cost data is therefore computed locally from token counts multiplied against published price tables:

- **Anthropic:** Input `$3/MTok`, output `$15/MTok` for Sonnet 4.6; Haiku significantly cheaper. Cache reads at ~10% of input price. If an Admin API key is configured (`US-analytics-anthropic-admin-api.md`), authoritative data can optionally supplement the estimate.
- **Mistral:** Varies by model (Medium ~`$0.40/MTok` input, Large ~`$2/MTok` input).
- **Moonshot:** Varies by model (K2 context-dependent pricing).
- **Ollama:** `$0.00` — local model.

All costs are clearly labelled as *estimated* since prices change and the price table is hard-coded at implementation time.

**Covers:** ANA-006.
**Depends on:** `US-analytics-call-log.md` (requires `api_calls` table with token counts).

---

## Acceptance Criteria

1. **`/costs` command registered** in the Telegram bot. Accepts optional period argument: `/costs`, `/costs 7d`, `/costs 30d`, `/costs all`. Default period is the current calendar month (`30d`).

2. **Per-service breakdown.** Output includes one section per service that was actually used in the period. Each section shows:
   - Total input tokens (excluding cache reads)
   - Total output tokens
   - Cache read tokens (Anthropic only, if > 0)
   - Cache creation tokens (Anthropic only, if > 0)
   - Estimated USD cost for that service
   - Estimated cache savings (Anthropic only — what it would have cost without cache)

3. **Total estimated cost line** at the bottom, summing all services.

4. **Clearly labelled as estimates.** Every cost figure is accompanied by a `~` prefix and a footer note: `_Prices based on published rates as of [date hard-coded at implementation]. Actual billing may differ._`

5. **Zero-usage services omitted.** If Moonshot was not called in the period, its section is not shown.

6. **Ollama shown as `$0.00 (local)`** if any Ollama calls occurred.

7. **Period summary header** shows the date range and total number of API calls.

8. **`ConversationAnalyzer` or a new `CostAnalyzer`** handles the query and formatting — not inline in the handler.

9. **Graceful empty state.** If no calls in `api_calls` for the period, returns: `_No API calls recorded for this period. Analytics data is collected from the date of your upgrade._`

---

## Implementation

**Files to create/modify:**
- `remy/analytics/costs.py` — new `CostAnalyzer` class
- `remy/analytics/prices.py` — new price table constants
- `remy/bot/handlers.py` — register `/costs` command handler

**Price table (`remy/analytics/prices.py`):**

```python
# Prices in USD per 1,000,000 tokens
# Last updated: [implementation date] — update when provider prices change
PRICES: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-6":       {"input": 3.00,  "output": 15.00, "cache_read": 0.30,  "cache_write": 3.75},
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00,  "cache_read": 0.08,  "cache_write": 1.00},
    "claude-opus-4-6":         {"input": 15.00, "output": 75.00, "cache_read": 1.50,  "cache_write": 18.75},
    # Mistral
    "mistral-medium-3":        {"input": 0.40,  "output": 2.00},
    "mistral-large-2411":      {"input": 2.00,  "output": 6.00},
    # Moonshot
    "moonshot-v1-8k":          {"input": 0.15,  "output": 0.15},
    "moonshot-v1-32k":         {"input": 0.23,  "output": 0.23},
    "kimi-k2-thinking":        {"input": 2.00,  "output": 8.00},
}
_FALLBACK_PRICE = {"input": 0.0, "output": 0.0}

def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  cache_read_tokens: int = 0, cache_creation_tokens: int = 0) -> float:
    """Return estimated USD cost for a call. Returns 0.0 for unknown models."""
    p = PRICES.get(model, _FALLBACK_PRICE)
    mtok = 1_000_000
    cost = (input_tokens / mtok * p["input"]
            + output_tokens / mtok * p["output"]
            + cache_read_tokens / mtok * p.get("cache_read", 0)
            + cache_creation_tokens / mtok * p.get("cache_write", 0))
    return round(cost, 4)
```

**`CostAnalyzer.get_cost_summary()` query:**

```sql
SELECT provider, model,
       SUM(input_tokens)          AS input_tokens,
       SUM(output_tokens)         AS output_tokens,
       SUM(cache_creation_tokens) AS cache_creation_tokens,
       SUM(cache_read_tokens)     AS cache_read_tokens,
       COUNT(*)                   AS call_count
FROM api_calls
WHERE user_id = ?
  AND timestamp >= ?
  AND timestamp < ?
GROUP BY provider, model
ORDER BY provider, model
```

**Sample output format:**

```
💰 *Estimated AI Costs — Last 30 days*

🟠 *Anthropic*
  claude-sonnet-4-6 × 312 calls
  Input:   4.2M tokens        ~$12.60
  Output:  890K tokens        ~$13.35
  Cache reads: 1.1M tokens   ~$0.33  _(saved ~$3.30)_
  Subtotal:                  ~$26.28

🔵 *Mistral*
  mistral-medium-3 × 87 calls
  Input:   680K tokens        ~$0.27
  Output:  210K tokens        ~$0.42
  Subtotal:                   ~$0.69

🟡 *Moonshot*
  kimi-k2-thinking × 14 calls
  Input:   320K tokens        ~$0.64
  Output:  95K tokens         ~$0.76
  Subtotal:                   ~$1.40

🟢 *Ollama (local)* × 3 calls — $0.00

━━━━━━━━━━━━
Total: ~$28.37

_Prices as of Feb 2026. Actual billing may differ._
```

### Notes
- Price table is a constant dict — easy to update. Add a comment with the date it was last verified.
- The Anthropic cache savings figure (`saved ~$3.30`) is computed as: what the cache read tokens would have cost at full input price, minus what they actually cost at cache read price.
- `/costs` shares the period-parsing logic with `ConversationAnalyzer._parse_period()` — extract to a shared utility if not already done.
- `US-analytics-anthropic-admin-api.md` may later supplement the local estimate with authoritative Anthropic data. The output format should have a clearly marked "source" field per service to support that upgrade path.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `/costs` with data in last 30 days | Formatted breakdown, correct per-service totals |
| `/costs 7d` | Uses 7-day window, correct date range in header |
| `/costs all` | All time data, header shows full date range |
| Only Anthropic used in period | Only Anthropic section shown |
| Anthropic cache hits present | Cache savings line shown |
| No calls in period | Empty state message returned |
| Unknown model in `api_calls` | Cost shown as `$0.00 (unknown model)`, no crash |
| Ollama calls in period | Shown as `$0.00 (local)` |
| DB unavailable | Error message to user, stack trace logged |

---

## Out of Scope

- Authoritative Anthropic billing data from Admin API (handled in `US-analytics-anthropic-admin-api.md`).
- Real-time spend alerts or budget thresholds (separate story).
- Moonshot balance check (handled in `US-analytics-moonshot-balance.md`).
- Price table auto-updates (out of scope — manual update with comment date is sufficient).
