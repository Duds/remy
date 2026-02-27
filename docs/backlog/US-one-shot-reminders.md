# User Story: One-Shot Reminders

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags (add one at the top of the file when relevant):
  ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

⬜ Backlog

## Summary
As a user, I want to set one-shot reminders via natural language (e.g. "remind me in 20 minutes" or "remind me at 3pm to call the dentist") so that I can get a single Telegram notification at a specific future time without creating a recurring reminder.

---

## Background

The current `schedule_reminder` tool only supports daily or weekly recurring reminders. There is no mechanism for a one-shot, fire-and-forget reminder triggered at a specific future time. Users frequently want to be nudged once — in N minutes, at a specific clock time, or on a specific date — without setting up a recurring schedule.

Remy should parse natural language time expressions from conversation and schedule a one-shot job accordingly.

---

## Acceptance Criteria

1. **Natural language parsing.** Remy correctly interprets expressions like "in 20 minutes", "at 3:30pm", "tomorrow at 9am", and schedules the reminder accordingly.
2. **Single delivery.** The reminder fires exactly once via Telegram and is then automatically removed from the scheduler.
3. **Visible in list_reminders.** One-shot reminders appear in the `list_reminders` output, clearly distinguished from recurring reminders (e.g. labelled "once" rather than "daily"/"weekly").
4. **Cancellable.** The user can cancel a pending one-shot reminder via `remove_reminder` before it fires.
5. **Confirmation on creation.** Remy confirms the scheduled time in her reply (e.g. "Done — I'll nudge you at 3:30 PM.").
6. **No regression.** Existing recurring reminder behaviour is unchanged.

---

## Implementation

**Files to create/modify:**
- `drbot/scheduler/` — add one-shot job support (likely APScheduler `date` trigger)
- `drbot/agents/` — extend the reminder tool definitions to include a `schedule_once` action
- Update `list_reminders` response formatting to include one-shot entries with a "once" frequency label

**Approach:**

Use APScheduler's `date` trigger (fires once at a specific datetime) rather than `cron` or `interval`.

```python
# Scheduling a one-shot reminder
scheduler.add_job(
    send_telegram_reminder,
    trigger='date',
    run_date=target_datetime,  # parsed from natural language
    args=[chat_id, label],
    id=f"once_{uuid4().hex[:8]}",
    misfire_grace_time=60,
)
```

Natural language time parsing should use the existing time context from `get_current_time` (Canberra timezone) combined with a parsing library (e.g. `dateparser`) or delegated to Claude during tool parameter extraction.

When the job fires, the scheduler should automatically remove the job entry so it does not reappear in `list_reminders`.

### Notes
- One-shot reminders must be persisted to the job store so they survive a bot restart before they fire.
- The `list_reminders` tool response should clearly distinguish one-shot vs recurring (frequency = "once", next fire time = the scheduled datetime).
- Depends on the scheduler having a persistent job store (check current APScheduler config).

---

## Test Cases

| Scenario | Expected |
|---|---|
| "Remind me in 2 minutes to check the oven" | Fires once ~2 min later via Telegram, then removed |
| "Remind me at 9am tomorrow to call the dentist" | Fires at 09:00 next day, correct timezone |
| User cancels before it fires | `remove_reminder` removes it; no message sent |
| Reminder appears in list | Shows with frequency "once" and correct fire time |
| Bot restarts before fire time | Reminder survives restart and fires on schedule |
| Ambiguous time ("remind me later") | Remy asks for clarification rather than guessing |
| Past time given ("remind me at 8am" when it's 10am) | Remy flags the time has passed, asks to confirm next day |

---

## Out of Scope

- Snooze / repeat-after-firing behaviour — deferred.
- Reminder delivery via any channel other than Telegram.
- Bulk one-shot reminders (multiple at once in a single message) — deferred.
