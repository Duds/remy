# User Story: Anthropic Overload Detection and Fallback

**Status:** ✅ Done

## Summary

As a user, I want Remy to handle Anthropic API overload gracefully so that when the service is under stress, I get a clear message and optional fallback instead of long retries or opaque failures.

---

## Background

Logs from 03/03/2026 show:

```
stream_with_tools error: {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}
anthropic._base_client: Retrying request to /v1/messages in 0.398396 seconds
```

When Anthropic returns `overloaded_error`, the client retries. Retries add latency (often 30–60+ seconds) and the user may not understand why Remy is slow. There is no user-facing message explaining the delay, and no option to fall back to a lighter model (e.g. Haiku) when Sonnet is overloaded.

Related: `remy/ai/claude_client.py`, `remy/bot/model_router.py`, `remy/config.py`, Anthropic SDK retry behaviour.

---

## Acceptance Criteria

1. **Overload detection.** When Anthropic returns `overloaded_error`, it is detected and logged distinctly (e.g. `anthropic_overloaded`).
2. **User-facing message.** After N retries (e.g. 2), if still overloaded, Remy sends a Telegram message: "Anthropic's API is busy right now. I'll keep trying, or you can try again in a few minutes." Optionally: "Say 'use faster model' to try Haiku instead."
3. **Optional fallback model.** A setting (e.g. `ANTHROPIC_OVERLOAD_FALLBACK_MODEL=claude-haiku-4-5-20251001`) allows automatic fallback to a lighter model when overload is detected. Fallback is configurable (can be disabled).
4. **Telemetry.** Log `anthropic_overload` and `anthropic_overload_fallback` events for monitoring.
5. **No regression.** Normal requests (no overload) behave unchanged. Retry logic for transient network errors is preserved.

---

## Implementation

**Files:** `remy/config.py`, `remy/ai/claude_client.py`, `remy/bot/handlers.py` (or pipeline), `remy/analytics/call_log.py`.

- Add `anthropic_overload_fallback_model: str = ""` (empty = disabled) and `anthropic_overload_max_retries: int = 2` to `Settings`.
- In `stream_with_tools` or the API call layer, catch `overloaded_error` from the response. On detection:
  - Increment overload retry counter.
  - If under max retries: retry with same model.
  - If at max retries and fallback model set: retry with fallback model; log `anthropic_overload_fallback`.
  - If at max retries and no fallback: send user-facing "API busy" message; log `anthropic_overload`.
- Ensure the user message is sent via the outbound queue so it appears in the correct chat/thread.

### Notes

- Anthropic SDK may wrap the error; check the exact exception/response structure.
- Fallback to Haiku may change response quality; document this trade-off.
- Consider a simple "status" check (e.g. HEAD or minimal request) before retrying — out of scope for this story but could reduce wasted retries.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Normal request | No change |
| overloaded_error, retry 1 | Retries with same model |
| overloaded_error, retry 2, fallback set | Retries with fallback model; log |
| overloaded_error, retry 2, no fallback | User gets "API busy" message; log |
| Transient network error | Existing retry logic applies |

---

## Out of Scope

- Proactive Anthropic status checks (e.g. polling a status page).
- Fallback to non-Anthropic providers (Moonshot, Ollama).
- Changing default retry count for non-overload errors.
