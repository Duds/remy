# User Story: Emoji Reactions as Task Completion Feedback

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want Remy to reliably react with ✅ to my message when she completes a task (e.g. archive emails, add calendar event, run automation) so that I get instant, silent confirmation without a redundant "Done" or "Got it" text reply.

---

## Background

`US-emoji-reaction-handling` (Phase 2 ✅) already implements outbound reactions: Claude can call `react_to_message(emoji)` via a tool. Claude decides when to react. In practice, Claude may not always react on task completion, or may both react and send a text reply when a reaction alone would suffice.

This US tightens the behaviour for **task completion** flows:
1. When a tool completes a destructive or high-impact action (archive, trash, add event, delete automation, etc.), the pipeline should ensure a ✅ reaction is applied to the user's message.
2. Optionally: when a reaction is used as the primary acknowledgement, suppress or shorten the text reply to avoid "✅ Got it, Doc." (redundant).

---

## Acceptance Criteria

1. **Automatic ✅ on tool completion.** When a "confirmable" or "completion" tool finishes successfully (e.g. `archive_messages`, `create_calendar_event`, `remove_automation`), the pipeline calls `set_message_reaction` with ✅ on the user's message, regardless of whether Claude also called `react_to_message`.
2. **Pipeline-level reaction.** The reaction is applied by the handler/pipeline after the tool result is processed, not solely by Claude. This guarantees consistency.
3. **No double reaction.** If Claude already reacted, the pipeline does not overwrite (or the pipeline runs first and Claude is instructed not to react for completion cases).
4. **Graceful fallback.** If `set_message_reaction` fails (message too old, API error), log WARNING and continue — never surface to user.
5. **Tool allowlist.** Define which tools trigger the auto-reaction: e.g. `archive_messages`, `modify_labels` (when removing INBOX/trash), `create_calendar_event`, `remove_automation`, `delete` fact/goal. Extensible.
6. **Optional: suppress redundant text.** When pipeline applies ✅, Claude can be prompted to omit a brief acknowledgement if the reaction is sufficient. (May be a SOUL.md / system prompt tweak.)

---

## Implementation

**Files:**

- `remy/bot/pipeline.py` or `remy/bot/handlers/chat.py` — after tool turn completes, check if tool is in completion allowlist; call `bot.set_message_reaction(chat_id, message_id, [ReactionTypeEmoji("✅")])`
- `remy/ai/tools/` — optional: tools return a `completion_reaction: true` flag in metadata, or use a static allowlist in the pipeline
- `config/SOUL.md` — add guidance: "When the pipeline has already reacted with ✅ for a task completion, you may omit a brief 'Done' reply."

**Approach:**

1. **Allowlist in pipeline.** Define `COMPLETION_REACTION_TOOLS = {"archive_messages", "modify_labels", "create_calendar_event", ...}`. After each tool result is processed, if the tool name is in the set and the result indicates success, call `set_message_reaction`.
2. **Message ID availability.** The handler already has `update.message.message_id`. Pass it through the pipeline context so the reaction can be applied after streaming completes.
3. **Timing.** Apply the reaction after the final assistant message is sent (or after the last tool result is streamed). The reaction goes on the *user* message that triggered the turn, not the assistant message.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User: "Archive those 50 emails" → tool succeeds | User's message gets ✅ reaction; Remy may send short confirmation text |
| User: "Add meeting with John tomorrow 2pm" → tool succeeds | User's message gets ✅ reaction |
| Tool fails (e.g. Gmail error) | No reaction |
| set_message_reaction raises (e.g. message >24h) | WARNING logged; no user-visible error |
| Claude also calls react_to_message | Pipeline applies first; Claude's call may be redundant but harmless |

---

## Out of Scope

- Reaction on every message (only completion flows).
- Other emojis (👍, 🔥) — those remain Claude-driven.
- Storing reaction history in DB.
