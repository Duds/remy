# User Story: Budget Enforcement / Monthly Cost Cap (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐⭐ High
**Effort:** Low
**Source:** [docs/paperclip-ideas.md §5](../paperclip-ideas.md)

## Summary

As Dale, I want Remy to track my monthly API spend against a configured budget ceiling, warn me when I approach the limit, and refuse non-critical LLM calls when the budget is exhausted — so I'm never surprised by a runaway bill at the end of the month.

---

## Background

Remy already logs API costs per model call in the `api_calls` table (via `remy/analytics/call_log.py` and `remy/analytics/costs.py`). What's missing is an enforced ceiling:

- No monthly budget cap in `config.py`
- No warning when approaching the limit
- No blocking of low-priority calls when over budget
- Budget status not surfaced in the morning briefing

Paperclip implements this as: per-agent monthly budget → auto-pause at 100% → deprioritise non-critical work at >80%.

---

## Acceptance Criteria

1. **Config variable.** `MONTHLY_BUDGET_USD` in `.env` (default: `None` = unlimited). When set, enforces the cap.
2. **Usage query.** `analytics/costs.py` exposes `get_month_spend() -> float` returning total USD spent in the current calendar month.
3. **80% warning.** When month spend crosses 80% of budget, Remy sends Dale a Telegram notification once per day: "⚠️ You've used $X of your $Y monthly budget (Z%)."
4. **100% block.** When month spend reaches 100%, non-critical Claude API calls are refused with a message: "Monthly budget exhausted. Only high-priority tasks will proceed." Critical tasks (goal/plan creation, relay task handling, heartbeat) are exempt.
5. **Morning briefing integration.** If `MONTHLY_BUDGET_USD` is set, the morning briefing includes a one-liner: "API budget: $X / $Y used (Z%)."
6. **No regression.** Calls continue normally when `MONTHLY_BUDGET_USD` is unset.

---

## Implementation

### 1. Config (`remy/config.py`)

```python
monthly_budget_usd: float | None = None  # None = unlimited
```

### 2. Cost query (`remy/analytics/costs.py`)

```python
async def get_month_spend(db_path: str) -> float:
    """Return total USD spent in the current calendar month."""
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # SELECT SUM(cost_usd) FROM api_calls WHERE created_at >= month_start
    ...
```

### 3. Budget guard (`remy/analytics/costs.py`)

```python
async def check_budget(db_path: str, budget: float | None) -> BudgetStatus:
    """Returns OK / WARNING (>80%) / EXHAUSTED (>=100%)."""
    ...
```

### 4. Claude client hook (`remy/ai/claude_client.py`)

Before each API call, call `check_budget()`. If `EXHAUSTED`, raise `BudgetExhaustedError` unless `critical=True` is passed by the caller.

### 5. Warning notification (`remy/scheduler/proactive.py` or heartbeat)

Once per day, if status is `WARNING`, send a Telegram message to Dale. Track last-sent date to avoid repeating.

### 6. Morning briefing (`remy/scheduler/briefings/`)

If budget is configured, append budget status line to the briefing.

---

## Files Affected

| File | Change |
|------|--------|
| `remy/config.py` | Add `monthly_budget_usd` setting |
| `remy/analytics/costs.py` | Add `get_month_spend()`, `check_budget()` |
| `remy/ai/claude_client.py` | Add pre-call budget guard |
| `remy/scheduler/proactive.py` | Add daily warning notification |
| `remy/scheduler/briefings/morning.py` | Add budget status line |
| `remy/exceptions.py` | Add `BudgetExhaustedError` |
| `.env.example` | Document `MONTHLY_BUDGET_USD` |

---

## Test Cases

| Scenario | Expected |
|---|---|
| `MONTHLY_BUDGET_USD` not set | No change to behaviour |
| Spend < 80% | No warnings, calls proceed |
| Spend crosses 80% | One Telegram warning per day |
| Spend >= 100% | Non-critical calls blocked with message |
| Critical call at 100% | Proceeds normally |
| New month resets | Spend resets to $0, warnings reset |

---

## Out of Scope

- Per-conversation or per-tool budgets
- Automatic plan/goal pausing (just block the LLM call)
- Integration with Anthropic's Admin API billing endpoint (separate US: `US-analytics-anthropic-admin-api.md`)
