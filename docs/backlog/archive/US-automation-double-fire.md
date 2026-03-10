# User Story: One-Time Automation Double-Fire on Restart

**Status:** ✅ Done

## Summary

As Dale, I want one-time reminders to fire exactly once even if the bot crashes or restarts immediately after firing, so that I don't receive duplicate reminder messages.

---

## Background

APScheduler loads all pending automations from the DB on startup via `load_user_automations()`. For one-time reminders (those with a `fire_at` datetime instead of a cron string), a `DateTrigger` is registered with `misfire_grace_time=3600`. If the bot restarts within the grace window after a one-time job fires, APScheduler re-registers the past-dated job and fires it again immediately.

The original bug was that `_run_automation()` deleted the DB row **after** firing. If the bot crashed between fire and delete, the row survived, causing a double-fire on the next startup.

Related to Bug 13 in `BUGS.md`.

---

## Acceptance Criteria

1. **Delete before fire.** For one-time automations, the DB row is deleted (or marked consumed) **before** the reminder message is sent. A crash between delete and send causes the reminder to be silently lost rather than double-fired.
2. **No double-fire on restart.** A bot restart within the APScheduler `misfire_grace_time` window does not cause a one-time reminder to fire more than once.
3. **Completed reminder logged.** After delete, a memory fact records that the reminder fired (e.g. `"Reminder completed: <label> (<datetime>)"`), providing a history trace even if the send fails.
4. **Recurring automations unaffected.** Recurring (cron) automations continue to use `update_last_run()` only and are not affected by this change.
5. **No regression.** `/schedule-daily`, `/schedule-weekly`, and `/unschedule` commands work correctly.

---

## Implementation

**Files:** `remy/scheduler/proactive.py` — `_run_automation()` method.

Delete the DB row **before** calling the send pipeline:

```python
async def _run_automation(self, automation_id, user_id, label, one_time=False):
    # ...resolve chat_id...

    # Delete BEFORE firing to prevent double-fire on crash/restart
    if self._automation_store is not None:
        if one_time:
            await self._automation_store.delete(automation_id)
            await self._log_completed_reminder(user_id, label)
        else:
            await self._automation_store.update_last_run(automation_id)

    # Now fire the pipeline
    await run_proactive_trigger(...)
```

`load_user_automations()` queries only rows that still exist in the DB. Once deleted, the row won't be re-registered on restart.

### Notes

- Trade-off: if the bot crashes between delete and send, the reminder is silently dropped. This is acceptable — better than flooding the user with duplicate messages.
- `_log_completed_reminder()` writes a `manage_memory` fact so the completion is preserved in Remy's memory even if the Telegram send fails.
- No schema changes required — delete removes the row entirely; no `status` column needed.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Normal one-time fire | DB row deleted before send; reminder fires once |
| Bot restarts within grace window after fire | Row already deleted; job not re-registered; no double-fire |
| `_automation_store` is `None` (test stub) | Skip delete; send fires; no crash |
| Delete fails (DB error) | Warning logged; send still attempted; row may re-fire on restart (acceptable edge case) |
| Recurring cron automation | `update_last_run()` called instead; row persists; unaffected |

---

## Out of Scope

- Adding a `status='fired'` column as an alternative to deletion — deletion is simpler and sufficient.
- Idempotency guarantees stronger than "delete before send" — not needed at current scale.
