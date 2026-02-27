# User Story: Tool Dispatch Exception Recovery

✅ Done — 2026-02-27

## Summary
As a user, if a tool call fails mid-stream (network error, validation error, etc.), I should
receive a clear error message rather than a cryptic crash, and my conversation history should
remain valid so I can continue the session normally.

---

## Background

`stream_with_tools()` in `drbot/ai/claude_client.py` (line 232) calls
`tool_registry.dispatch()` with no exception handling:

```python
result = await tool_registry.dispatch(tool_name, tool_input, user_id)
```

If any tool raises (e.g. a network timeout in `GmailClient`, a validation error in
`CalendarClient`, an unhandled edge case in any executor), the exception propagates up and
exits the entire `stream_with_tools()` generator.

The outer handler in `bot/handlers.py` (lines 2222–2231) catches the exception, clears the
task timer, and shows `"❌ Sorry, something went wrong: …"` — so the *user-facing* experience
is tolerable. However, **conversation history is left corrupt**:

1. The assistant's `tool_use` content blocks were accumulated in `assistant_content_blocks`
   (line 198–214) and were about to be appended to `working_messages`.
2. Because the generator exited, the paired `tool_result_blocks` were never added.
3. On the next turn, `working_messages` is rebuilt from the stored conversation history
   (`conv_store.get_recent_turns`). But `ToolTurnComplete` was never yielded, so
   `handlers.py` never called `conv_store.append_turn()` for this exchange.
4. Net result: the conversation turn is dropped cleanly (not stored) — which is actually
   safe. **But the user sees a generic error with no indication of which tool failed or why.**

The real fix is to catch the exception inside the tool execution loop, synthesise an error
`tool_result`, and continue the agentic loop so Claude can acknowledge the failure gracefully.

---

## Acceptance Criteria

1. **Tool dispatch exceptions are caught per-tool**, not globally. Other tool calls in the
   same batch still execute.
2. **An error `tool_result` is injected** into `tool_result_blocks` for the failing tool,
   with a message like `"Tool 'search_gmail' failed: connection timeout"`.
3. **`ToolTurnComplete` is still yielded.** The agentic loop continues. Claude receives the
   error result and can respond appropriately (e.g. "I couldn't fetch your emails — want
   me to try again?").
4. **The exception is logged** at `ERROR` level with tool name, input (sanitised), and
   traceback.
5. **No change to existing behaviour for successful tool calls.**
6. **No new dependencies.**

---

## Implementation

**File:** `drbot/ai/claude_client.py`
**Location:** The tool execution loop (lines 222–244)

### Change

Wrap `tool_registry.dispatch()` in a per-tool try/except:

```python
for tool_block in tool_use_blocks:
    tool_name = tool_block["name"]
    tool_use_id = tool_block["id"]
    tool_input = tool_block.get("input", {})

    try:
        result = await tool_registry.dispatch(tool_name, tool_input, user_id)
    except Exception as exc:
        logger.error(
            "Tool dispatch failed for %s (id=%s): %s",
            tool_name, tool_use_id, exc, exc_info=True,
        )
        result = f"Tool '{tool_name}' encountered an error: {exc}"

    yield ToolResultChunk(tool_name=tool_name, tool_use_id=tool_use_id, result=result)
    tool_result_blocks.append({
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": result,
    })
```

The loop then reaches `yield ToolTurnComplete(...)` as normal. Claude sees the error string
as a tool result and can handle it conversationally.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Tool succeeds | Behaviour unchanged |
| Single tool raises `ConnectionError` | Error result injected; Claude acknowledges failure |
| Second tool in a batch raises | First tool result preserved; second gets error result; loop continues |
| Tool raises, Claude replies "I couldn't fetch that" | Conversation history saved correctly; next turn works |
| Non-tool path (Path B router) | Unaffected |

---

## Out of Scope

- Retry logic for transiently failing tools (keep it simple — let the user ask again)
- Exposing the full traceback to the user (error string only; full details in `/logs`)
- Changes to `bot/handlers.py` — exception handlers there remain as a safety net
