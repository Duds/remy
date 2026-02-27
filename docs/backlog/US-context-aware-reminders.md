# User Story: Context-Aware Gentle Reminders

## Summary
As a user, I want Remy to gently nudge me when a goal or commitment has gone stale —
particularly later in the day — without being intrusive or repeating itself.

---

## Background

Phase 5.2 in the roadmap listed "context-aware gentle reminders" as a Could Have feature,
but deferred it because the evening check-in from `ProactiveScheduler` already surfaces
stale goals (any goal with no update in 3+ days gets a ⚠️ indicator).

This story captures what a true context-aware reminder would add **beyond** the existing
evening check-in: reminders tied to time-of-day context, active calendar events, and
whether the user has already interacted about a topic that day.

**Deferred.** Only implement if the current evening check-in proves insufficient in practice.

---

## Acceptance Criteria

1. **No duplicate nudges.** If Remy already discussed a goal during the current day's
   conversation, it is not surfaced again in the evening check-in.
2. **Calendar-aware.** If the user has a meeting about topic X on their calendar today,
   Remy references it when prompting about related goals.
3. **Staleness threshold configurable** via `.env` (default: 3 days, consistent with
   goal-status ⚠️ indicator).
4. **Opt-out available.** User can say "stop reminding me about [goal]" and Remy tags
   that goal as `snoozed_until=<date>`.
5. **Evening check-in remains the primary channel** — no new notification jobs added.

---

## Implementation

**Modified file:** `drbot/scheduler/proactive.py`

### Dedup logic

In the evening check-in job, before building the stale-goals list, query the
`conversations` table for messages in the last 24 hours that mention the goal's title.
Skip any goals already discussed.

```python
async def _evening_checkin(self):
    stale_goals = await goal_store.get_stale(days=STALENESS_DAYS)
    today_topics = await conversation_store.get_topics_today(user_id)
    to_surface = [g for g in stale_goals if g.title not in today_topics]
    ...
```

### Calendar context

If `GoogleCalendarClient` is configured, fetch today's events and inject matching
event titles as context alongside the stale goal.

### Snooze

Add `snoozed_until` column to the `goals` table. `manage_goal` tool gains a `snooze`
action: `{"action": "snooze", "goal_id": 42, "until": "2026-03-07"}`.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Goal discussed earlier today | Not surfaced in evening check-in |
| Stale goal with a calendar event today | Check-in includes calendar context |
| User says "stop reminding me about X" | Goal snoozed for 7 days |
| Snooze expires | Goal resurfaces in next evening check-in after expiry |
| Goal updated within staleness window | Not flagged as stale |

---

## Out of Scope

- Mid-day push reminders (separate notification job)
- Reminder frequency beyond the existing evening check-in cadence
- ADHD-specific escalation patterns (body double features are in Phase 5.2 body double story)
