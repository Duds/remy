# User Story: Confirmation Flows with Inline Yes/No

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want destructive or high-impact actions (e.g. archive 50 emails, delete an automation) to require an explicit inline [Confirm] [Cancel] tap so that I never accidentally trigger bulk or irreversible operations from a misread command or typo.

---

## Background

Today, `/gmail_classify` uses a text-based confirmation: "Reply *yes* to archive all N emails." The user must type "yes" in the next message. This works but is less discoverable and more error-prone than a one-tap inline keyboard. Other destructive flows (e.g. `delete` automation, `trash` emails via tools, bulk label changes) may not have confirmation at all.

Telegram inline keyboards with callback buttons provide instant, unambiguous confirmation. Tapping [Confirm] executes the action; tapping [Cancel] edits the message to "Cancelled" and clears the pending state. No typing required.

---

## Acceptance Criteria

1. **Inline keyboard for confirmable actions.** When Remy proposes a destructive or high-impact action, she sends a message with an inline keyboard: [Confirm] [Cancel].
2. **Callback handler registered.** `CallbackQueryHandler` is registered and processes `callback_data` (e.g. `confirm_archive_<id>` / `cancel_archive_<id>`).
3. **Confirm executes the action.** Tapping [Confirm] runs the stored intent (e.g. archive message_ids, delete automation) and edits the message to show the outcome (e.g. "✅ Archived 50 email(s).").
4. **Cancel clears state.** Tapping [Cancel] edits the message to "Cancelled." and clears any pending state. No action is performed.
5. **answer_callback_query called.** Every callback is answered with `answer_callback_query` so Telegram clears the loading state.
6. **Authorisation enforced.** Callbacks from users not in `TELEGRAM_ALLOWED_USERS` are ignored.
7. **Applied to existing flows.** At minimum: `/gmail_classify` archive confirmation. Optionally: `unschedule` (delete automation), tool-initiated trash/archive when count exceeds a threshold.

---

## Implementation

**Files:**

- `remy/bot/telegram_bot.py` — register `CallbackQueryHandler`
- `remy/bot/handlers/email.py` — replace "Reply yes" with inline keyboard for archive
- New or extended: `remy/bot/handlers/callbacks.py` — central callback router that dispatches by `callback_data` prefix

**Approach:**

1. Define `callback_data` schema: `confirm_<action>_<payload>` / `cancel_<action>_<payload>`. Payload can be a short token (e.g. base64 of message_ids or automation_id).
2. Store pending confirmations in a dict keyed by `(user_id, action, payload)` or a single-use token. TTL of 5–10 minutes to avoid stale state.
3. For `/gmail_classify`: after sending the promo list, send a follow-up message with `InlineKeyboardMarkup` containing [Confirm] [Cancel]. Callback handler looks up `_pending_archive[user_id]` (or equivalent) and executes archive on confirm.
4. Use `edit_message_text` to update the message after confirm/cancel — no new message.

**Telegram API:**

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Confirm", callback_data="confirm_archive_xyz")],
    [InlineKeyboardButton("Cancel", callback_data="cancel_archive_xyz")],
])
await update.message.reply_text("Archive 50 emails?", reply_markup=keyboard)
```

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User taps [Confirm] on archive prompt | Emails archived; message edited to "✅ Archived N email(s)." |
| User taps [Cancel] on archive prompt | Message edited to "Cancelled."; no archive performed |
| Callback from unauthorised user | Silent ignore; no state change |
| Callback with stale/unknown token | Log warning; edit message to "Expired. Please try again." |
| User sends "yes" as text (legacy) | Can be deprecated or kept as fallback during transition |

---

## Out of Scope

- Confirmation for every tool call (only destructive/high-impact).
- Rate limiting on callbacks (single user).
- Undo after confirm (irreversible by design).
