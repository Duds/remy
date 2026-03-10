# User Story: Calendar Quick Add from Inline Suggestions

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want Remy to add [Add to calendar] inline buttons next to event mentions (e.g. in a briefing or email summary) so that I can create a calendar event with one tap instead of copy-pasting or typing a new command.

---

## Background

When Remy mentions events (e.g. "Team standup 10:00", "Sarah asked for 1:1 this week") in a morning briefing, email summary, or research output, the user must manually add them to the calendar. There is no direct action from the message.

This US adds inline [Add to calendar] buttons. Tapping one parses the event context (title, date, time) from stored metadata, optionally shows a minimal "Confirm: Title, Date, Time" step, and creates the event via the existing calendar tools.

---

## Acceptance Criteria

1. **Inline [Add to calendar] on event mentions.** When Remy's response includes calendar-related content (e.g. from briefing, email summary, or explicit "you have X at Y"), the message has an inline button [Add to calendar] per event (or one [Add all] if multiple).
2. **Callback passes event context.** `callback_data` or a stored payload includes `title`, `date`, `time` (or ISO string) so the callback handler can create the event without re-asking.
3. **Confirmation step optional.** For simple cases (clear title + time), create directly. For ambiguous cases, send a follow-up "Confirm: Meeting with Sarah, Thu 14:00. [Add] [Edit] [Cancel]."
4. **Uses existing calendar tools.** Callback handler invokes the same calendar create API used by Claude tools (e.g. `create_calendar_event` or equivalent). No new calendar logic.
5. **Edit message after add.** After successful creation, edit the original message to show "Added ✓" next to that event, or remove the button.
6. **Authorisation enforced.** Callbacks from users not in `TELEGRAM_ALLOWED_USERS` are ignored.
7. **Integration with suggested_actions.** This can be a specific `callback_id` in the smart reply buttons flow (US-smart-reply-buttons): `add_to_calendar` with payload.

---

## Implementation

**Files:**

- `remy/bot/handlers/callbacks.py` — handle `add_to_calendar` callback; parse payload, call calendar client, edit message
- `remy/ai/tools/calendar.py` — ensure `create_calendar_event` (or equivalent) is callable from non-Claude context
- `remy/bot/streaming.py` or pipeline — when content includes event snippets, attach `suggested_actions` with `add_to_calendar` and payload (from US-smart-reply-buttons)
- Briefing generators — when producing "you have X at Y" lines, include structured `event_snippets` for the pipeline to convert to buttons

**Approach:**

1. **Structured event snippets.** When generating briefings or summaries, tools or Claude output structured data: `event_snippets: [{title, date, time}]`. The pipeline maps these to `suggested_actions` with `callback_id: add_to_calendar` and `payload: {title, date, time}`.
2. **Payload encoding.** `callback_data` is max 64 bytes. Encode a short token (e.g. `evt_abc123`) and store full `{title, date, time}` in a cache keyed by token. TTL 10 minutes.
3. **Callback handler.** On `add_to_calendar`, load payload from cache, call `google_calendar.create_event(...)` (or the appropriate method), edit message to "Added ✓", clear buttons.
4. **Calendar client.** The callback handler needs `google_calendar` injected. Ensure the handler factory receives it (same as other handlers).

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Briefing mentions "Standup 10:00"; user taps [Add to calendar] | Event created; message updated |
| Multiple events in one message | One button per event, or [Add all] |
| Payload missing/invalid | "Could not add event. Try again." |
| Calendar API error | Edit message to "Failed: <reason>"; log error |
| Callback from unauthorised user | Silent ignore |

---

## Out of Scope

- Recurring events (one-off only for v1).
- Edit event after add.
- Integration with Google Meet / video links.
