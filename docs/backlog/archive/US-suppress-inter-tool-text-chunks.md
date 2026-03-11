# User Story: Suppress Inter-Tool Text Chunks from Telegram Stream

✅ **Done** — implemented and resolved per commit d050159 (`docs: mark tool-status text leak bug as resolved`)

## Summary
As a user, I do not want to see internal status fragments like "using list_directory"
or "using get_logs" appear in Remy's Telegram replies. Those are Claude's internal
monologue between tool calls — they belong in the logs, not in my chat.

---

## Background

`ClaudeClient.stream_with_tools()` in `remy/ai/claude_client.py` runs an agentic loop.
Between tool invocations, Claude sometimes emits short `TextChunk` events — fragments
like "using list_directory" or "let me check that". These are status thoughts, not
user-facing content.

The current handler in `bot/handlers.py` (Path A — tool-aware path) feeds **all**
`TextChunk` events straight into `StreamingReply.feed()` without checking whether a
tool turn is in progress. This causes the fragments to appear verbatim in Telegram.

---

## Acceptance Criteria

1. **Inter-tool `TextChunk` events are NOT sent to Telegram.**
   - A `TextChunk` arriving after a `ToolStatusChunk` but before the corresponding
     `ToolTurnComplete` must be suppressed from `StreamingReply.feed()`.
2. **Suppressed chunks ARE logged** at `DEBUG` level so they remain visible in `/logs`.
3. **Final response text IS still streamed.** `TextChunk` events that arrive after
   `ToolTurnComplete` (i.e. Claude's actual reply) continue to stream normally.
4. **No changes to `streaming.py` or `claude_client.py`** — fix is isolated to the
   event loop in `bot/handlers.py`.
5. **Existing tool behaviour is unchanged** — tools still execute, results still appear,
   conversation history is still reconstructed correctly.

---

## Implementation

**File:** `remy/bot/handlers.py`
**Location:** Path A — the `async for event in claude_client.stream_with_tools(...)` loop

### Change

Introduce a boolean flag `in_tool_turn` (initial value `False`) in the event loop scope.

```python
in_tool_turn = False

async for event in claude_client.stream_with_tools(
    working_messages, tool_registry, user_id, system=system_prompt
):
    if isinstance(event, TextChunk):
        if in_tool_turn:
            logger.debug("Suppressing inter-tool text: %r", event.text)
        else:
            await reply.feed(event.text)

    elif isinstance(event, ToolStatusChunk):
        in_tool_turn = True
        # existing status display logic (e.g. "⚙️ using list_directory") stays here
        # but goes to a separate ephemeral message or is dropped entirely — NOT feed()

    elif isinstance(event, ToolResultChunk):
        # no change — tool results are not streamed to user anyway
        pass

    elif isinstance(event, ToolTurnComplete):
        in_tool_turn = False
        # existing history reconstruction logic unchanged
```

### Notes
- `ToolStatusChunk` fires when Claude *decides* to call a tool (before execution).
- `ToolTurnComplete` fires after the tool result has been fed back and the next
  Claude iteration is about to begin.
- The flag resets to `False` on `ToolTurnComplete`, so Claude's final prose reply
  (which arrives as `TextChunk` events after the last `ToolTurnComplete`) streams
  normally.
- If Claude calls multiple tools in sequence, the flag toggles correctly for each.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Ask "list my Projects folder" | No "using list_directory" in Telegram reply |
| Ask "check my logs" | No "using get_logs" in Telegram reply |
| Ask "what are my goals?" | No "using get_goals" in Telegram reply |
| Any tool call — final answer | Final prose response streams normally |
| DEBUG logs during tool call | Suppressed text visible in `/logs tail` |
| Multi-tool request (e.g. goals + calendar) | Both tool calls suppressed, final answer streams |

---

## Out of Scope
- Displaying a "thinking…" indicator in Telegram during tool execution (separate story)
- Changes to `streaming.py`
- Changes to `claude_client.py`
