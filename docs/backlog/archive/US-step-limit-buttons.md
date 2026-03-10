# User Story: Step-Limit Message Inline Buttons

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, when Remy hits the step limit and sends _“I reached my step limit for this turn. Ask me to continue or break this into smaller tasks.”_, I want three inline buttons — **Continue**, **Break down**, **Stop** — so that I can choose the next action with one tap instead of typing.

---

## Background

When `stream_with_tools` hits `anthropic_max_tool_iterations` (see US-cap-tool-iterations-per-turn), Remy yields a truncation message. Previously this was plain text with no actions. Adding inline buttons gives the user clear, one-tap options: continue the same task, break it into smaller tasks, or end the turn.

Related: `remy/ai/claude_client.py` (step limit TextChunk + `StepLimitReached`), `remy/bot/handlers/chat.py`, `remy/bot/handlers/callbacks.py`, US-cap-tool-iterations-per-turn, US-calendar-quick-add (inline button pattern).

---

## Acceptance Criteria

1. **Step-limit message has three inline buttons.** When the turn hits the tool-iteration cap, the message shows the existing truncation text plus an inline keyboard: [Continue] [Break down] [Stop].
2. **Continue.** Tapping **Continue** removes the buttons and shows a short hint (e.g. via `query.answer`) that the user can send “continue” to pick up where Remy left off. No synthetic message injection required for v1.
3. **Break down.** Tapping **Break down** removes the buttons and hints that the user can send “break this into smaller tasks” or use `/breakdown`.
4. **Stop.** Tapping **Stop** removes the buttons (dismiss); no further hint. User keeps the truncated reply as-is.
5. **Step-limit keyboard takes precedence.** When `StepLimitReached` is emitted, the final message uses the step-limit keyboard only (no suggested_actions from the same turn).
6. **Both streaming paths.** Step-limit buttons apply in both the chat handler streaming path and the handlers.py `_stream_with_tools_path` (if used).

---

## Implementation

**Files:**

- `remy/ai/claude_client.py` — After the step-limit `TextChunk`, yield `StepLimitReached()`. Add `StepLimitReached` to the `StreamEvent` union.
- `remy/bot/handlers/callbacks.py` — `make_step_limit_keyboard()` returning `InlineKeyboardMarkup` with three buttons; handle `step_limit_continue`, `step_limit_break`, `step_limit_stop` in the callback handler (edit reply_markup to None, optional `query.answer` with hint).
- `remy/bot/handlers/chat.py` — In the stream loop, set `step_limit_reached = True` when `StepLimitReached` is received; when building `reply_markup`, use `make_step_limit_keyboard()` if `step_limit_reached`, else suggested_actions.
- `remy/bot/handlers.py` — Same `StepLimitReached` handling and final flush with `reply_markup = make_step_limit_keyboard()` when `step_limit_reached`; extend `_flush_display` to accept optional `reply_markup`.

**Button labels:**

- **Continue** — user can send “continue” next.
- **Break down** — concise; user can send “break this into smaller tasks” or use `/breakdown`.
- **Stop** — end here; no further action.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Turn hits max_iterations | Message shows truncation text + [Continue] [Break down] [Stop]. |
| Tap Continue | Buttons removed; user sees hint to send “continue”. |
| Tap Break down | Buttons removed; user sees hint for break down / `/breakdown`. |
| Tap Stop | Buttons removed; message unchanged. |
| Unit test `make_step_limit_keyboard` | Returns keyboard with three buttons and correct callback_data. |

---

## Out of Scope

- One-tap “Continue” that injects a synthetic user “continue” and re-runs the stream (possible future improvement).
- Changing the step-limit message wording (handled in US-cap-tool-iterations-per-turn / BUGS.md).
