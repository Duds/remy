# User Story: Smart Reply Buttons (Inline Keyboards)

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want Remy to attach contextual inline buttons (e.g. [Add to calendar], [Forward to cowork], [Break down]) to substantive replies so that I can take the next action with one tap instead of typing a follow-up message.

---

## Background

Today, when Remy sends a calendar summary, email triage result, or research synthesis, the reply is plain text. To act on it (e.g. add an event, share with cowork, get more detail), the user must type another message. Inline keyboards let Remy suggest 2–4 contextual actions directly below the message. Tapping a button sends a callback that triggers the corresponding flow without any typing.

This requires:
1. A way for Claude or tools to return "suggested_actions" (labels + callback identifiers).
2. The streaming/pipeline layer to attach an `InlineKeyboardMarkup` to the final message.
3. A `CallbackQueryHandler` to process the callbacks and invoke the appropriate flow.

---

## Acceptance Criteria

1. **Suggested actions from pipeline.** When a tool or Claude response includes structured `suggested_actions` (list of `{label, callback_id, payload?}`), the handler attaches an inline keyboard to the sent message.
2. **Callback handler dispatches actions.** Tapping a button triggers the callback handler, which routes by `callback_id` to the correct flow (e.g. `add_to_calendar`, `forward_to_cowork`, `break_down`, `dismiss`).
3. **Context preserved.** Callback payload (e.g. event snippet, message_id) is passed to the flow so it can execute without re-asking the user.
4. **Edit message after action.** After a successful action (e.g. event added), the message can be edited to remove the buttons or show "Added ✓". Optional: `edit_message_reply_markup` to clear buttons.
5. **Not every message.** Buttons appear only when `suggested_actions` is non-empty. Most conversational replies remain button-free.
6. **Authorisation enforced.** Callbacks from users not in `TELEGRAM_ALLOWED_USERS` are ignored.
7. **Initial action set.** At minimum support: `add_to_calendar`, `forward_to_cowork`, `break_down`, `dismiss`. Extensible for more.

---

## Implementation

**Files:**

- `remy/bot/streaming.py` — after final message is sent, check for `suggested_actions` in tool result or response metadata; attach `reply_markup`
- `remy/ai/claude_client.py` or tool schemas — define how tools/Claude return `suggested_actions`
- `remy/bot/handlers/callbacks.py` — callback router for `add_to_calendar`, `forward_to_cowork`, etc.
- `remy/bot/telegram_bot.py` — register `CallbackQueryHandler`

**Approach:**

1. **Structured output from tools.** Tools that produce calendar-related content (e.g. `get_calendar_events`, briefing) can return an extra field `suggested_actions: [{"label": "Add event", "callback_id": "add_to_calendar", "payload": {...}}]`. The pipeline merges tool-level suggestions with any from Claude.
2. **Claude tool for suggestions.** Alternatively, add a lightweight tool `suggest_actions` that Claude calls at the end of a turn with a list of actions. The tool returns a sentinel; the handler reads the tool input and builds the keyboard.
3. **Callback data encoding.** Use `callback_data` (max 64 bytes): `action:payload` where payload is a short token (e.g. `evt_abc123`). Store full context in a short-lived cache keyed by token.
4. **Streaming integration.** `stream_to_telegram` receives the final assembled message. If `suggested_actions` is present in the turn metadata, build `InlineKeyboardMarkup` and pass as `reply_markup` to `send_message` or the last `edit_text`.

**Example tool response extension:**

```python
# In a tool or pipeline layer
return {
    "content": "Tomorrow: Team standup 10:00, Sarah 1:1 requested.",
    "suggested_actions": [
        {"label": "Add standup", "callback_id": "add_to_calendar", "payload": {"title": "Team standup", "when": "2026-03-04T10:00"}},
        {"label": "Break down", "callback_id": "break_down", "payload": {"topic": "prepare for standup"}},
    ],
}
```

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Remy sends calendar summary with suggested_actions | Message has inline keyboard with [Add event] [Break down] etc. |
| User taps [Add to calendar] | Callback handler creates event; message updated or new confirmation sent |
| User taps [Dismiss] | Buttons removed from message; no further action |
| Reply has no suggested_actions | No keyboard; plain text only |
| Callback with unknown action | Log warning; answer_callback_query with "Unknown action" |
| Callback from unauthorised user | Silent ignore |

---

## Out of Scope

- Claude autonomously deciding actions (can be Phase 2; initially tools or fixed rules).
- More than 4 buttons (keep it simple).
- Nested or multi-row complex keyboards.
