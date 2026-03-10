# ✅ Done

# User Story: Telegram Catch-All Error Handler

## Summary

As Dale, I want unhandled Telegram exceptions to be caught and logged cleanly so that I get structured error output and optionally a Telegram notification for critical failures, instead of noisy "No error handlers are registered" log spam.

---

## Background

Logs show 8+ instances of:

```
telegram.ext.Application: No error handlers are registered, logging exception.
```

python-telegram-bot routes unhandled exceptions through `Application.add_error_handler()`. Without one, PTB logs the raw exception at ERROR level with no context (no user ID, no update type) and no Telegram notification. This makes diagnosis slow and produces log noise. Related to BUG-003 — the scheduler miss warnings were mixed into the same noisy log stream.

---

## Acceptance Criteria

1. **Catch-all registered.** `application.add_error_handler(error_handler)` is called during bot setup. The `"No error handlers are registered"` log message no longer appears.
2. **Structured logging.** The handler logs at ERROR level with: exception type, message, and update context (user ID, update type) where available.
3. **Telegram alert for unexpected errors.** For exceptions that are not `telegram.error.NetworkError` or `telegram.error.TimedOut` (transient / expected), a short alert is sent to the first allowed user: `"⚠️ Remy error: <ExceptionType>: <message>"`.
4. **Transient errors suppressed.** `NetworkError`, `TimedOut`, and `Forbidden` (bot blocked by user) are logged at WARNING level only — no Telegram notification.
5. **No regression.** Existing command and message handlers are unaffected.

---

## Implementation

**Files:** `remy/bot/telegram_bot.py` (primary), no other changes needed.

Add a module-level async handler function and register it in `_register_handlers`:

```python
import telegram.error

async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    # Transient / expected — log quietly
    if isinstance(err, (telegram.error.NetworkError, telegram.error.TimedOut,
                        telegram.error.Forbidden)):
        logger.warning("Telegram transient error: %s", err)
        return
    # Unexpected — log with context and notify Dale
    user_id = None
    update_type = type(update).__name__ if update else "unknown"
    if hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    logger.error(
        "Unhandled Telegram exception (update_type=%s, user=%s): %s",
        update_type, user_id, err, exc_info=context.error,
    )
    # Notify the first allowed user
    from ..config import settings
    if settings.telegram_allowed_users:
        try:
            await context.bot.send_message(
                chat_id=settings.telegram_allowed_users[0],
                text=f"⚠️ *Remy error:* `{type(err).__name__}: {err}`",
                parse_mode="Markdown",
            )
        except Exception:
            pass  # Don't let the error handler itself raise
```

Register it at the end of `_register_handlers`:

```python
app.add_error_handler(_error_handler)
```

### Notes

- The handler can be a module-level function or a static/instance method on `TelegramBot` — either works.
- `ContextTypes.DEFAULT_TYPE` import comes from `telegram.ext`.
- `Forbidden` covers the case where Dale blocks the bot (edge case but harmless to suppress).
- Do NOT send Telegram alerts for `ConversationHandler` timeout errors if those are ever added.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `NetworkError` raised during polling | WARNING log, no Telegram message |
| `TimedOut` during a send | WARNING log, no Telegram message |
| Unexpected `ValueError` in a handler | ERROR log with user/update context + Telegram alert |
| Handler itself raises during `send_message` | Silently swallowed; original error still logged |
| Normal message handling | Unaffected |

---

## Out of Scope

- Per-command error recovery (tool dispatch errors are handled separately in `US-tool-dispatch-exception-recovery`).
- Error rate limiting / deduplication (not needed at current scale).
- Sentry / external error tracking integration.
