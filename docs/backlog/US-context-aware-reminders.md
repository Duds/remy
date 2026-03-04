# User Story: Context-Aware Gentle Reminders

## Summary
As a user, I want Remy to gently nudge me when a goal or commitment has gone stale —
particularly later in the day — without being intrusive or repeating itself.

---

## Background

Phase 5.2 listed "context-aware gentle reminders" as a Could Have feature. The evening
check-in from `ProactiveScheduler` already surfaces stale goals (goals with no update
in 3+ days). This story implements the **full** context-aware behaviour: dedup by
conversation, configurable staleness, calendar context, and snooze — so the single
evening check-in remains the primary channel but is smarter and less repetitive.

**Status:** Ready to implement in full.

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

### 1. Configurable staleness (`.env`)

- **Config:** `remy/config.py` already defines `stale_goal_days: int = 3`. Ensure it is
  loaded from env (e.g. `STALE_GOAL_DAYS`) if present.
- **Proactive scheduler:** In `remy/scheduler/proactive.py`, remove the hardcoded
  `_STALE_GOAL_DAYS = 3` and use `settings.stale_goal_days` when constructing
  `EveningCheckinGenerator` and when passing `stale_days`.
- **Evening generator:** In `remy/scheduler/briefings/evening.py`, remove the
  module-level `_STALE_GOAL_DAYS`; accept `stale_days` from the caller (proactive already
  passes it). Default in the generator can remain 3 for tests that don't set config.
- **Analytics:** In `remy/analytics/analyzer.py`, the goal-status staleness marker (⚠️)
  should use the same threshold: `settings.stale_goal_days` (or a shared constant) so
  dashboard and evening check-in stay in sync.

**Files:** `remy/config.py` (env binding if missing), `remy/scheduler/proactive.py`,
`remy/scheduler/briefings/evening.py`, `remy/analytics/analyzer.py`.

---

### 2. Dedup: don’t surface goals already discussed today

- **ConversationStore:** Add a method to determine which goal titles were mentioned in
  today’s conversation content, e.g.:

  ```python
  async def get_goal_titles_mentioned_today(
      self, user_id: int, goal_titles: list[str]
  ) -> set[str]:
      """
      Return the subset of goal_titles that appear in any of today's
      conversation turns (user or assistant content). Case-insensitive
      substring match. Used to avoid re-nudging about goals already
      discussed in the evening check-in.
      """
  ```

  Implementation: call `get_today_messages(user_id)`, then for each turn’s `content`,
  check which of `goal_titles` appear as substrings (e.g. `title.lower() in
  content.lower()`). Return the set of titles that were mentioned.

- **EveningCheckinGenerator:** In `remy/scheduler/briefings/evening.py`:
  - Inject `ConversationStore` (or a narrow interface) into the generator, e.g. via
    `BriefingGenerator` constructor if shared, or only on `EveningCheckinGenerator`.
  - After `stale_goals = await self._get_stale_goals(days=self._stale_days)`, compute
    `mentioned_today = await conv_store.get_goal_titles_mentioned_today(
        self._user_id, [g["title"] for g in stale_goals]
    )`, then `to_surface = [g for g in stale_goals if g["title"] not in mentioned_today]`.
  - If `to_surface` is empty, return `""` (no message). Otherwise generate the
    evening message from `to_surface` only.

- **ProactiveScheduler:** Ensure `_evening_checkin` passes `conv_store` into
  `EveningCheckinGenerator` (and that the scheduler already has `_conv_store` wired).

**Files:** `remy/memory/conversations.py`, `remy/scheduler/briefings/evening.py`,
`remy/scheduler/briefings/base.py` (if constructor extended), `remy/scheduler/proactive.py`.

---

### 3. Calendar context for evening check-in

- **EveningCheckinGenerator:** If the base class (or evening generator) has access to
  `CalendarClient`, fetch today’s events in the user’s timezone (reuse existing
  scheduler timezone / calendar helpers). Build a short context string, e.g. “Today’s
  events: Meeting with Bob 14:00, Gym 18:00.”
- **Content generation:** When building the “You haven’t mentioned these goals…”
  message, append a line when calendar context exists, e.g. “_Context: [today’s
  events]._” so the nudge can reference relevant events (e.g. “You have Gym later —
  still on for your fitness goal?”). Keep the main body unchanged; the calendar line
  is optional context so the user (or future Claude-generated check-in) can tie goals
  to the day.
- **Optional refinement:** If desired later, match event titles to goal titles (e.g.
  keyword overlap or simple embedding similarity) and only include events that relate
  to a surfaced goal. For initial implementation, including all of today’s events is
  acceptable.

**Files:** `remy/scheduler/briefings/evening.py`, `remy/scheduler/briefings/base.py`
(if calendar is shared), `remy/scheduler/proactive.py` (ensure calendar is passed
into evening generator).

---

### 4. Snooze: goals table + GoalStore + manage_goal

- **Schema:** Add nullable `snoozed_until` column to the `goals` table (ISO date string
  or datetime). Add a migration in `remy/memory/database.py` (e.g. `ALTER TABLE goals
  ADD COLUMN snoozed_until TEXT;`).
- **GoalStore:**
  - In `get_active` (or wherever the evening check-in’s stale list is sourced), filter
    out goals where `snoozed_until` is set and `snoozed_until > now` (interpret as
    date/datetime in the user’s scheduler timezone or UTC). Goals with `snoozed_until`
    in the past or null are treated as not snoozed.
  - Add `async def snooze(self, user_id: int, goal_id: int, until: datetime | str) ->
    bool`: set `snoozed_until` for the goal (store as date string or ISO). Return
    `True` if the goal existed and was updated.
- **manage_goal tool:** Add a `snooze` action:
  - Schema: extend the `action` enum with `"snooze"`. Add optional `until` parameter
    (date string, e.g. `YYYY-MM-DD`). Default `until` to 7 days from today if not
    provided.
  - Executor: when `action == "snooze"`, require `goal_id`. If `registry._goal_store`
    is available, call `await registry._goal_store.snooze(user_id, goal_id, until)`.
    If goal_store is not available, return a message that snooze is not available.
    Confirm to the user that the goal will not appear in evening check-ins until the
    given date.
- **Natural language:** When the user says “stop reminding me about [goal]” or similar,
  Claude should call `manage_goal` with `action: "snooze"` and the matching
  `goal_id` (from `get_goals`). Document in the tool description that snooze is for
  temporarily hiding a goal from evening check-ins.

**Files:** `remy/memory/database.py`, `remy/memory/goals.py`, `remy/ai/tools/schemas.py`,
`remy/ai/tools/memory.py`.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Goal discussed earlier today | Not surfaced in evening check-in |
| Stale goal with a calendar event today | Check-in includes calendar context line |
| User says "stop reminding me about X" | Goal snoozed (e.g. 7 days); confirm via manage_goal |
| Snooze expires | Goal resurfaces in next evening check-in after expiry |
| Goal updated within staleness window | Not flagged as stale |
| `STALE_GOAL_DAYS` set in `.env` | Evening check-in and goal-status use that value |
| All stale goals were discussed today | No evening check-in message sent |

---

## Out of Scope

- Mid-day push reminders (separate notification job)
- Reminder frequency beyond the existing evening check-in cadence
- ADHD-specific escalation patterns (body double features are in Phase 5.2 body double story)
