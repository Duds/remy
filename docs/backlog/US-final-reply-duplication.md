# User Story: Fix Final Reply Duplication / Reordering in Telegram

✅ Done — 2026-02-27

## Summary
As a user, I want Remy's final reply to appear exactly once and in the correct order,
so that confirmations and responses are not duplicated or rendered out of sequence in
Telegram after multi-tool interactions.

---

## Background

After a multi-step agentic exchange involving sequential tool calls, Claude's final
prose response is sometimes rendered twice in Telegram, or partially rendered before
the tool results have fully flushed, causing the confirmation text to appear
out of order.

Observed example: after completing a `manage_goal` → confirmation flow, the final
"Timesheets — done." message appeared once correctly *and* again prepended to
subsequent tool output, giving the impression the reply was mangled.

This is distinct from `US-suppress-inter-tool-text-chunks.md`, which covers
*inter-tool* text fragments leaking mid-stream. This bug affects the **final**
`TextChunk` stream — the actual user-facing reply — not intermediate status text.

Likely cause: `StreamingReply` accumulates text across the entire event loop, and if
Claude emits a partial `TextChunk` before the final `ToolTurnComplete`, the streaming
reply flushes that text early. When Claude then emits the full final reply, the earlier
partial text is repeated.

---

## Acceptance Criteria

1. **Final reply appears exactly once in Telegram.** No duplicate messages, no partial
   text followed by a full repeat.
2. **Reply content is correct and complete.** No truncation of the final response.
3. **Ordering is preserved.** Tool status (if shown) always precedes the final reply.
4. **No regression on single-tool flows.** Simple one-tool interactions continue to
   stream normally.
5. **No regression on zero-tool flows.** Plain conversational replies unaffected.

---

## Implementation

**Files to investigate:**
- `remy/bot/handlers.py` — event loop, `StreamingReply` usage
- `remy/bot/streaming.py` — `StreamingReply.feed()` and flush logic
- `remy/ai/claude_client.py` — event emission order around `ToolTurnComplete`

### Hypothesis

`StreamingReply.feed()` is being called with `TextChunk` content that arrives
*just before* the final `ToolTurnComplete`. This text is streamed to Telegram.
Claude then emits its actual final reply as another `TextChunk` sequence — but
the earlier partial text has already been sent, causing duplication.

### Suggested approach

1. **Audit the event sequence** for a multi-tool request by adding `DEBUG` logging
   to every event in the loop, capturing type and content in order.
2. **Identify whether a `TextChunk` precedes the last `ToolTurnComplete`** — if so,
   that chunk is being treated as final prose when it isn't.
3. **Buffer the final reply** — don't flush to Telegram until `ToolTurnComplete` has
   been received and no further tool calls are pending. Only then begin streaming
   the buffered + subsequent `TextChunk` events.
4. Alternatively, **reset the `StreamingReply` buffer on `ToolTurnComplete`** so
   any pre-final text is discarded before the true final reply streams.

```python
# Sketch — option B: reset buffer on ToolTurnComplete
elif isinstance(event, ToolTurnComplete):
    in_tool_turn = False
    await reply.reset()  # discard any pre-final text, start clean for final reply
```

### Notes
- Coordinate with `US-suppress-inter-tool-text-chunks.md` — both touch the same
  event loop in `handlers.py`. Implement the suppress story first; this story builds
  on that flag infrastructure.
- The `in_tool_turn` flag from the suppress story may be directly reusable here.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Single tool call (e.g. `get_goals`) | Final reply appears once, streams normally |
| Two sequential tool calls (e.g. `get_goals` → `manage_goal`) | Final reply appears exactly once, after both tools complete |
| Three+ sequential tool calls | No duplication, correct ordering |
| Plain conversational reply (no tools) | Unaffected — streams as before |
| Tool call followed by error | Error message appears once, not duplicated |
| DEBUG log capture | Pre-final text chunks visible in `/logs tail` if suppressed |

---

## Out of Scope
- Inter-tool fragment suppression (covered by `US-suppress-inter-tool-text-chunks.md`)
- Displaying a "thinking…" indicator during tool execution (separate story)
- Changes to how tool *results* are displayed
