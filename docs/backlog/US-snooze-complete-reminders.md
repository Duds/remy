# User Story: Snooze and Complete on Proactive Reminders

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want proactive reminder messages (e.g. "Standup in 2 min") to include inline buttons [Snooze 5m] [Snooze 15m] [Done] [Reschedule] so that I can acknowledge, snooze, or mark complete with one tap instead of typing or ignoring.

---

## Background

The proactive scheduler fires automations (daily reminders, one-shot reminders) and sends a Telegram message. Today, the message is plain text (e.g. "⏰ Reminder: Standup in 2 min" or the agentic pipeline output). The user must either act on it, type a reply, or ignore it. There is no one-tap way to snooze or mark done.

Adding inline buttons to reminder messages lets the user:
- **Snooze 5m / 15m** — schedule a one-shot follow-up reminder in 5 or 15 minutes; optionally edit the original message to "Snoozed until 14:07"
- **Done** — mark the reminder as complete (for one-shot: already deleted when fired; for recurring: update last_run and optionally edit message to "Done ✓")
- **Reschedule** — optional: open a flow to pick a new time (can be deferred to a later US)

---

## Acceptance Criteria

1. **Inline keyboard on reminder messages.** When the proactive scheduler sends a reminder (either raw fallback or pipeline output), it attaches an inline keyboard: [Snooze 5m] [Snooze 15m] [Done].
2. **Snooze creates one-shot follow-up.** Tapping [Snooze 5m] or [Snooze 15m] creates a one-shot job (via scheduler) that re-sends the same reminder in 5 or 15 minutes. The original message is edited to "Snoozed — next reminder at HH:MM."
3. **Done marks complete.** Tapping [Done] edits the message to "Done ✓". For recurring automations, `update_last_run` is called. For one-shot, the job was already deleted when it fired; no further DB change needed.
4. **Callback handler.** `CallbackQueryHandler` processes `snooze_5`, `snooze_15`, `done` with a payload encoding `automation_id` or `label` + `chat_id` so the callback can identify which reminder was acted on.
5. **Message ID passed to scheduler.** The scheduler must know the `message_id` of the sent reminder so the callback can `edit_message_text` on it. This may require the scheduler to return the sent message, or store `(chat_id, message_id)` in a short-lived cache keyed by a token in the callback.
6. **Authorisation enforced.** Callbacks from users not in `TELEGRAM_ALLOWED_USERS` are ignored.
7. **No regression.** Reminders still fire on schedule; pipeline-based reminders (agentic path) also get the keyboard.

---

## Implementation

**Files:**

- `remy/scheduler/proactive.py` — after `_send` or pipeline send, attach inline keyboard; pass message_id to callback payload or cache
- `remy/bot/pipeline.py` — when sending proactive trigger response, attach keyboard to the final message
- `remy/bot/handlers/callbacks.py` — handle `snooze_5`, `snooze_15`, `done`; create one-shot job for snooze; edit message for done/snoozed
- `remy/bot/telegram_bot.py` — ensure `CallbackQueryHandler` is registered (may be added in US-confirmation-flows)

**Approach:**

1. **Keyboard on send.** In `_send` (fallback) and in `run_proactive_trigger` (pipeline), after sending the message, send a second message with the keyboard, OR include `reply_markup` in the initial send. For pipeline, the streaming layer would need to support attaching a keyboard to the proactive message — may require a dedicated "proactive reminder" send path that always adds the keyboard.
2. **Callback payload.** Encode `reminder_{automation_id}_{message_id}` or similar. For one-shot reminders, `automation_id` is already deleted; use `label` + `chat_id` + `message_id` instead. Store in callback_data (max 64 bytes) or use a short token that maps to stored context.
3. **Snooze job.** Reuse the one-shot reminder mechanism (APScheduler `date` trigger). Create a job that fires in 5 or 15 minutes and sends the same label to the same chat. Reuse `_run_automation` with a synthetic one-time job.
4. **Edit vs new message.** Prefer `edit_message_text` on the original reminder message to avoid clutter. Buttons can be removed via `edit_message_reply_markup(reply_markup=None)` after action.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Reminder fires; user taps [Snooze 5m] | Message edited to "Snoozed — next reminder at HH:MM"; one-shot job fires in 5 min |
| Reminder fires; user taps [Done] | Message edited to "Done ✓"; recurring automation's last_run updated |
| One-shot reminder; user taps [Done] | Message edited to "Done ✓"; no DB change (already deleted) |
| Snoozed reminder fires again | New message has same [Snooze] [Done] buttons |
| Callback from unauthorised user | Silent ignore |
| Callback with stale/unknown payload | Log warning; answer_callback_query |

---

## Out of Scope

- [Reschedule] button (defer to separate US).
- Custom snooze duration (5m and 15m are sufficient for v1).
- Snooze limit (e.g. max 3 snoozes) — not needed for single user.
