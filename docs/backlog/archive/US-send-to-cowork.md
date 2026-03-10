# User Story: Send to Cowork with One Tap

<!--
Filename convention: US-<kebab-case-feature-slug>.md
Status tags: ⬜ Backlog  |  🔄 In Progress  |  ✅ Done  |  ❌ Deferred
-->

✅ Done

## Summary

As Dale, I want Remy to add an inline [Send to cowork] button to notes or summaries (e.g. "Gmail quick wins complete…") so that I can forward that content to the cowork agent in one tap without typing or copying.

---

## Background

Remy uses the relay MCP to communicate with cowork. `relay_post_note` and `relay_post_message` send content to cowork. Today, the user would need to ask Remy to "send this to cowork" or manually invoke a command. When Remy produces a summary that would be useful for cowork (e.g. task completion, audit results, findings), a one-tap [Send to cowork] button streamlines the handoff.

This US adds that button to appropriate messages. Tapping it calls `relay_post_note` or `relay_post_message` with the current message content (or a stored note_id) and optionally edits the message to show "Sent to cowork ✓".

---

## Acceptance Criteria

1. **Inline [Send to cowork] on relevant messages.** When Remy sends a note or summary that is a candidate for cowork (e.g. task completion, Gmail audit, research findings), the message includes an inline button [Send to cowork].
2. **Callback posts to relay.** Tapping the button calls `relay_post_note(from_agent="remy", content=..., tags=[...])` or `relay_post_message(from_agent="remy", to_agent="cowork", content=...)` with the message text.
3. **Content source.** The callback uses the text of the message the button is attached to. The handler can read `callback_query.message.text` to get the content. For long messages, truncate or use full content per relay API limits.
4. **Edit after send.** After successful post, edit the message to show "Sent to cowork ✓" or append a brief note. Optionally remove the button.
5. **Authorisation enforced.** Callbacks from users not in `TELEGRAM_ALLOWED_USERS` are ignored.
6. **Relay unavailable.** If relay MCP is not configured or the post fails, edit message to "Could not send to cowork. Try again later." and log the error.
7. **Integration with suggested_actions.** This can be a `callback_id` in the smart reply buttons flow: `forward_to_cowork` with optional payload (e.g. tags).

---

## Implementation

**Files:**

- `remy/bot/handlers/callbacks.py` — handle `forward_to_cowork` callback; read message text, call relay MCP, edit message
- `relay_mcp/server.py` or client — ensure `relay_post_note` / `relay_post_message` is callable from Python (MCP tools are typically invoked via MCP client; Remy may have a direct Python client or use the MCP connector)
- `remy/bot/streaming.py` or pipeline — when content is "shareable" (e.g. task completion, audit summary), add `suggested_actions` with `forward_to_cowork`

**Approach:**

1. **Relay invocation.** Determine how Remy invokes relay: direct Python import, HTTP client, or MCP. Use the same path as when Remy posts notes from tool use. If relay is in a separate process, there may be an HTTP or stdio interface.
2. **Content extraction.** `callback_query.message.text` contains the message. For Markdown-formatted messages, the raw text may have Markdown; relay may accept it as-is or strip formatting. Max length: check relay API limits.
3. **Tags.** Optional: pass tags like `["gmail", "audit", "complete"]` based on message context. Can be derived from tool name or a simple heuristic.
4. **Suggested actions.** When tools return completion summaries (e.g. Gmail audit, research), include `forward_to_cowork` in `suggested_actions`. Claude could also suggest it via a tool.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User taps [Send to cowork] on Gmail audit summary | relay_post_note called with content; message edited to "Sent to cowork ✓" |
| Relay unavailable / error | Message edited to "Could not send to cowork."; WARNING logged |
| Callback from unauthorised user | Silent ignore |
| Very long message | Content truncated if needed; relay accepts |
| Message has no [Send to cowork] | Normal; only added when relevant |

---

## Out of Scope

- Cowork replying in-thread (relay is one-way for this action).
- Selecting which parts to send (full message only).
- Custom tags from user (fixed or derived tags only).
