# User Story: Forward-to-Cowork Feedback and Observability

**Status:** ✅ Done

**Depends on (optional):** [US-relay-shared-backend](US-relay-shared-backend.md) — delivery is only guaranteed after shared backend is in place. This story improves feedback and debuggability regardless.

**Related bugs:** [Bug 4](../../BUGS.md) (misleading "Sent to cowork" when not delivered)

## Summary

As Dale, I want clear feedback when I tap [Send to cowork] and visibility into whether the message was queued vs delivered, so that I am not misled and we can debug delivery issues.

---

## Background

Today the [Send to cowork] callback in `remy/bot/handlers/callbacks.py` edits the message to "✅ Sent to cowork." whenever the local relay write succeeds. When Remy and cowork use different relay backends (Bug 3), cowork never receives the message but the UI still says "Sent". After US-relay-shared-backend, delivery will be correct; this story adds better feedback and observability so that:

1. We can tell the difference between "written to local DB" and "using shared backend (delivery expected)" if we ever need to support both modes.
2. If the Telegram edit fails (e.g. message disappears), we have a log trail.
3. Optionally we record relay/button outcomes for debugging (e.g. in logs or telemetry).

**Related:** `remy/bot/handlers/callbacks.py` (forward_to_cowork), `remy/relay/client.py`, `BUGS.md` Bug 4.

---

## Acceptance Criteria

1. **Edit failures logged.** If `query.edit_message_text(...)` fails in the forward_to_cowork callback (success or failure path), log at WARNING with the exception so we can diagnose "message disappeared" reports.

2. **Copy or behaviour when using shared backend.** After US-relay-shared-backend is implemented, keep "✅ Sent to cowork." as the success message (no change required if shared backend is the only supported mode). If we explicitly support a "local-only" mode (e.g. no RELAY_MCP_URL), then show different copy (e.g. "Queued for cowork (offline)." or "Saved locally; start shared relay so cowork can see it.") so the user is not misled.

3. **Optional: Relay post logged with message id.** When `post_message_to_cowork` succeeds, the existing log line (`Relay: posted message to cowork (id=...)`) is sufficient. Optionally add a short log in the callback: "Forward to cowork: message_id=... so we can correlate with relay logs.

4. **No regression.** Authorised users can still tap [Send to cowork]; message is still replaced with success or error text; unauthorised users are still ignored.

---

## Implementation

**Files:** `remy/bot/handlers/callbacks.py` (forward_to_cowork block), optionally `remy/relay/client.py` or config (if we add "shared backend vs local-only" detection).

### 1. Log edit_message_text failures

In the forward_to_cowork block, the existing `try/except` around `query.edit_message_text` uses `except Exception: pass`. Replace with logging:

- On success edit: `except Exception as e: logger.warning("Forward to cowork: could not edit message to success state: %s", e)`
- On failure edit (could not send): already in an except block; ensure we log the edit failure if the second `edit_message_text` raises: `except Exception as edit_e: logger.warning("Forward to cowork: could not edit message to error state: %s", edit_e)`

### 2. Optional: Different copy for local-only mode

If we introduce a config flag or heuristic (e.g. "relay is shared" when RELAY_MCP_URL is set or when using a known-shared DB path), then in the callback:

- If shared: keep "✅ Sent to cowork."
- If local-only: use "📤 Queued for cowork (start shared relay so cowork can see it)." or similar.

Out of scope for minimal version: if US-relay-shared-backend makes shared backend the only supported setup, skip this and keep current copy.

### 3. Optional: Callback log with message_id

After `ok = await post_message_to_cowork(...)` when `ok` is truthy, log: `logger.info("Forward to cowork: relay message_id=%s", ok.get("message_id"))` so we can correlate with `Relay: posted message to cowork (id=...)` in the same log file.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User taps [Send to cowork], relay post succeeds, edit succeeds | Message shows "✅ Sent to cowork."; no new WARNING |
| User taps [Send to cowork], relay post succeeds, edit fails (e.g. message deleted) | WARNING logged with exception; user may see no change |
| User taps [Send to cowork], relay post fails | Message shows "❌ Could not send to cowork. Try again later."; existing WARNING for post failure |
| Unauthorised user taps button | Silent ignore; no crash |
| Optional: local-only mode | Copy distinguishes queued vs delivered (if implemented) |

---

## Out of Scope

- Implementing the shared backend (US-relay-shared-backend).
- Adding relay events to the api_calls/telemetry DB (can be a separate analytics story).
- Changing the suggest_actions schema or when [Send to cowork] is shown.
