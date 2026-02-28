# User Story: Moonshot Credit Balance Monitoring

⬜ Backlog

## Summary

As Dale, I want Remy to check my Moonshot AI credit balance and warn me when it runs low so that I don't hit silent fallbacks mid-conversation because the account ran out of credits.

---

## Background

Unlike Anthropic and Mistral (which use post-pay billing), Moonshot AI uses pre-paid credits. If the balance hits zero, API calls fail and the router silently falls back to Ollama — with no visible indication of why. There is no proactive warning today.

Moonshot provides a documented balance check endpoint:
```
GET https://api.moonshot.ai/v1/users/me/balance
```
This returns the current credit balance for the authenticated API key. There is no usage history API — balance is the only programmatic signal available.

Mistral and Anthropic have no equivalent endpoint (Anthropic is post-pay; Mistral has no balance API).

**Covers:** ANA-010.

**Depends on:** Nothing — this story is self-contained. `MoonshotClient` already exists.

---

## Acceptance Criteria

1. **`MoonshotClient.get_balance()` method.** Calls `GET /v1/users/me/balance` and returns the credit amount as a `float` (USD). Returns `None` if the API key is not configured or the call fails.

2. **`/status` command includes Moonshot balance.** The existing `/status` health-check output gains a "Moonshot credits" line when `MOONSHOT_API_KEY` is configured. Shows current balance and a low-balance warning marker if below threshold.

3. **Low-balance warning in morning briefing.** If Moonshot balance is below the configurable threshold (`MOONSHOT_BALANCE_WARN_USD`, default `5.00`), a warning line is included in the daily morning briefing: `⚠️ Moonshot credits low: $X.XX remaining — top up to avoid fallbacks.`

4. **Threshold configurable via env var.** `MOONSHOT_BALANCE_WARN_USD` in `.env` / `config.py`. Default `5.00`. Set to `0` to disable the warning entirely.

5. **Balance check is on-demand and at briefing time only.** Not called on every message. Called:
   - When `/status` is invoked.
   - Once per morning briefing run (if the briefing scheduler is active).

6. **Failures are silent to the user.** If the balance check fails (network error, invalid key), no error is shown in the briefing or `/status`. Log at WARNING level only. The rest of `/status` continues normally.

7. **Not shown if Moonshot is not configured.** If `MOONSHOT_API_KEY` is empty, the balance line is omitted entirely from `/status` and the briefing.

---

## Implementation

**Files to modify:**
- `remy/ai/moonshot_client.py` — add `get_balance()` method
- `remy/config.py` — add `moonshot_balance_warn_usd: float = 5.00`
- `remy/bot/handlers.py` — update `/status` handler
- `remy/scheduler/proactive.py` — add balance check to morning briefing context

**`MoonshotClient.get_balance()`:**

```python
async def get_balance(self) -> float | None:
    """
    Returns current credit balance in USD, or None on failure.
    Endpoint: GET /v1/users/me/balance
    """
    if not self._api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{self._base_url}/users/me/balance",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            # Response shape (from Moonshot docs):
            # {"balance": {"available_balance": 12.50, "voucher_balance": 0.00, "cash_balance": 12.50}}
            balance_data = data.get("balance", {})
            return float(balance_data.get("available_balance", 0.0))
    except Exception as e:
        logger.warning("Moonshot balance check failed: %s", e)
        return None
```

**`/status` integration:**

```python
# In the /status handler, after existing health checks:
if settings.moonshot_api_key:
    balance = await moonshot_client.get_balance()
    if balance is None:
        status_lines.append("🟡 Moonshot: balance check failed")
    elif balance < settings.moonshot_balance_warn_usd:
        status_lines.append(f"🔴 Moonshot: ⚠️ ${balance:.2f} remaining (low!)")
    else:
        status_lines.append(f"🟢 Moonshot: ${balance:.2f} credits")
```

**Morning briefing integration:**

The morning briefing in `scheduler/proactive.py` (or wherever the briefing prompt is assembled) adds a balance check:

```python
if settings.moonshot_api_key:
    balance = await moonshot_client.get_balance()
    if balance is not None and balance < settings.moonshot_balance_warn_usd:
        briefing_warnings.append(
            f"⚠️ Moonshot credits low: ${balance:.2f} remaining — top up to avoid fallbacks."
        )
```

### Notes
- The exact JSON shape of the balance response should be verified at implementation time against the live API — the schema above is based on the documented response but the field names may vary.
- Consider caching the balance response for 15 minutes (using a simple `(value, fetched_at)` tuple on `MoonshotClient`) so rapid `/status` calls don't hammer the endpoint.
- There is no equivalent story for Anthropic (post-pay, no balance to check) or Mistral (no balance API). If Mistral ever adds one, this story is the template.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Moonshot key configured, balance $12.50 (above threshold) | `/status` shows `🟢 Moonshot: $12.50 credits` |
| Balance $3.20 (below default $5.00 threshold) | `/status` shows `🔴 Moonshot: ⚠️ $3.20 remaining (low!)` |
| Balance below threshold at briefing time | Warning line included in morning briefing |
| `MOONSHOT_BALANCE_WARN_USD=0` | No low-balance warning ever shown |
| Balance check fails (network error) | `🟡 Moonshot: balance check failed` in `/status`; briefing unaffected |
| `MOONSHOT_API_KEY` not set | Balance line omitted from `/status` entirely |
| `get_balance()` called twice within 15 minutes | Returns cached value (no second API call) |

---

## Out of Scope

- Automatic top-up or payment integration.
- Balance tracking history in `api_calls` table.
- Equivalent for Mistral (no API exists).
- Equivalent for Anthropic (post-pay billing, no pre-paid credits).
- Per-model spending rate projections ("balance will run out in N days at current burn rate") — stretch goal for a future story.
