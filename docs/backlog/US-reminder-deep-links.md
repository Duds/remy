# User Story: Deep Links for Reminders

**Status:** ⬜ Backlog

## Summary
As a user, I want to tap a reminder notification and land in Telegram with that reminder’s context (e.g. `t.me/RemyBot?start=reminder_<id>`) so that I can act on it or see details without hunting through the chat.

---

## Background

**Tier 3 — Nice to have.** Reminders are sent by the proactive scheduler with inline buttons (Snooze 5m, Snooze 15m, Done). Callback handlers in `remy/bot/handlers/callbacks.py` use short-lived tokens in `callback_data`; there is no stable deep link today. When the user taps a push notification (or shares a link), opening `t.me/RemyBot?start=reminder_42` should bring them into the bot with context for reminder ID 42 (e.g. show the reminder label, next fire time, and Snooze/Done actions).

Relevant code: `remy/bot/handlers/core.py` (`start_command`), `remy/bot/handlers/callbacks.py` (`store_reminder_payload`, `make_reminder_keyboard`), `remy/ai/tools/automations.py` (reminder CRUD), automations table (id, user_id, label, cron, last_run_at, etc.).

---

## Acceptance Criteria

1. **Deep link format.** `t.me/RemyBot?start=reminder_<id>` is supported, where `<id>` is the automation (reminder) ID.
2. **Start command parses payload.** When the user opens the link, Telegram sends a message with text `/start reminder_<id>`. The start handler parses this and dispatches to reminder-context behaviour instead of the default welcome.
3. **Reminder context for the user.** For a valid reminder belonging to the user, Remy replies with: reminder label, next run time (or “one-time: &lt;datetime&gt;”), and the same inline keyboard as the original notification ([Snooze 5m] [Snooze 15m] [Done]).
4. **Auth and ownership.** Only the reminder owner can see/act on it; if reminder_&lt;id&gt; does not exist or belongs to another user, show a friendly “Reminder not found or no longer available” (no data leak).
5. **One-time reminders.** One-time reminders that have already fired may be shown as “Already completed” with no Snooze/Done; optionally offer “Remove from list” only.
6. **Existing reminder flow unchanged.** Reminder notifications sent by the scheduler continue to use the current token-based callback flow; deep links are an additional entry point.

---

## Implementation

**Files:** `remy/bot/handlers/core.py`, optionally a small helper in `remy/bot/handlers/callbacks.py` or a dedicated `remy/bot/handlers/deep_links.py`.

### Start payload parsing

In `start_command`, read `update.message.text`. If it is `/start reminder_123`, split and parse `reminder_123` → prefix `reminder_`, id `123`. If prefix is `reminder_`, load automation by id and user_id; if found, build reminder message + `make_reminder_keyboard(token)` (reuse existing `store_reminder_payload` so Snooze/Done work). Send that reply and return; otherwise fall through to the default welcome.

```python
# In start_command (conceptual)
text = (update.message and update.message.text) or ""
if text.startswith("/start "):
    payload = text[len("/start "):].strip()
    if payload.startswith("reminder_"):
        try:
            automation_id = int(payload[len("reminder_"):])
        except ValueError:
            pass
        else:
            # Resolve reminder, check ownership, reply with context + keyboard
            await _handle_reminder_deep_link(update, context, user_id, automation_id)
            return
# Default welcome
await update.message.reply_text("Remy online. ...")
```

### Notes

- Reuse `store_reminder_payload` so the generated token is valid for the same callback handlers (snooze/done). Pass `automation_id` and `chat_id` from the current chat.
- Ensure `AutomationStore` (or equivalent) exposes a method to get a single automation by id and user_id (e.g. `get(user_id, automation_id)`). If it does not, add it.
- Deep link payload in Telegram is limited to 64 bytes; `reminder_<id>` is well within that for integer ids.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User opens t.me/RemyBot?start=reminder_5, owns reminder 5 | Reply shows label, next run, [Snooze 5m] [Snooze 15m] [Done] |
| User opens reminder_999, no such id | “Reminder not found or no longer available” |
| User A opens reminder_3, reminder belongs to User B | “Reminder not found or no longer available” |
| User opens /start (no payload) | Default welcome message unchanged |
| User opens /start reminder_abc | Treated as unknown payload or invalid id; fall back to default welcome |
| One-time reminder already fired | Show “Already completed” (and optionally Remove); no Snooze/Done |

---

## Out of Scope

- Changing how reminder notifications are sent (e.g. adding the deep link URL to the notification body) — can be a follow-up.
- Deep links for other entities (e.g. goals, plans) — separate stories.
- Custom URL schemes or non-Telegram links.
