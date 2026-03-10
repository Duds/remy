# User Story: One-Tap Automation Templates (Inline Buttons)

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want `/list_automations` (or a menu) to show my scheduled automations as inline buttons so that I can run any automation (e.g. "Gmail quick wins", "Morning briefing") with one tap instead of typing a command or waiting for the schedule.

---

## Background

Today, `/list_automations` returns a text list of automations with IDs and labels. To run one on-demand, the user would need a separate command (e.g. `/run_auto <id>`) or to wait for the scheduled fire time. There is no one-tap way to trigger "Gmail quick wins" or "Morning briefing" immediately.

Adding inline buttons transforms the list into an actionable menu. Each automation becomes a button; tapping it runs the same pipeline as when the scheduler fires it (`run_proactive_trigger`), and streams the result to the chat.

---

## Acceptance Criteria

1. **Inline keyboard for automations.** When the user invokes `/list_automations` (or a new `/automations` command), Remy sends a message with an inline keyboard: one button per automation, labelled with the automation's label (e.g. "Morning briefing", "Gmail quick wins").
2. **Tapping runs the automation.** Callback handler receives the tap, looks up the automation by ID, and invokes `run_proactive_trigger` with the same `label` and `user_id` as the scheduler would use. The result is streamed to the chat.
3. **One-shot reminders included.** If one-shot reminders are visible in the list (e.g. via `list_reminders` or a combined view), they can also be buttons. Tapping "Run now" would fire them immediately (or show "Already scheduled for HH:MM").
4. **Empty state.** If no automations exist, show "No automations. Use /schedule_daily or /schedule_weekly to add one." with no buttons.
5. **Authorisation enforced.** Only the automation owner can run their automations via callback.
6. **No double-fire.** Running on-demand does not affect the next scheduled fire (recurring) or the one-shot fire time. It is an extra, manual trigger.
7. **Optional: "Run all" or grouping.** Can be deferred; for v1, one button per automation is sufficient.

---

## Implementation

**Files:**

- `remy/bot/handlers/automations.py` — modify `list_automations_command` to send message with `InlineKeyboardMarkup` instead of (or in addition to) plain text list
- `remy/bot/handlers/callbacks.py` — handle `run_auto_<id>`; fetch automation from store, invoke `run_proactive_trigger`
- `remy/bot/telegram_bot.py` — ensure `CallbackQueryHandler` registered
- `remy/scheduler/proactive.py` — `run_proactive_trigger` is already callable; ensure it can be invoked from a callback context (chat_id, user_id available)

**Approach:**

1. **Build keyboard from AutomationStore.** `automation_store.get_all(user_id)` returns list of `{id, label, cron, fire_at, ...}`. Build one `InlineKeyboardButton` per row: `callback_data=f"run_auto_{row['id']}"`, `text=row['label'][:32]` (Telegram button text limit).
2. **Callback handler.** On `run_auto_<id>`, fetch automation by ID, verify `user_id` matches, call `run_proactive_trigger(label=..., user_id=..., chat_id=...)`. Use `context.bot` and inject `claude_client`, `tool_registry`, etc. from handler dependencies.
3. **Streaming.** `run_proactive_trigger` uses the same streaming path as scheduler-fired runs. The callback handler will need access to the pipeline components. Consider a shared `run_automation_now(automation_id, user_id, chat_id, bot, ...)` helper.
4. **Working message.** Optionally send "Running Gmail quick wins…" and then stream into that message, or send a new message. Match existing proactive pipeline behaviour.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User runs /list_automations | Message with inline buttons, one per automation |
| User taps "Gmail quick wins" | Pipeline runs; result streamed to chat |
| User has no automations | Message "No automations…" with no buttons |
| Callback for automation owned by another user | Ignore (or 403) |
| Automation deleted between list and tap | Callback handles missing automation; "No longer available" |
| Recurring automation run on-demand | Runs now; next scheduled fire unchanged |

---

## Out of Scope

- "Run all" button.
- Editing automation from the list (use /unschedule).
- One-shot reminders in the same list (can be Phase 2).
