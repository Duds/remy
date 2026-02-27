# User Story: Claude Agent SDK Subagents

## Summary
As a developer, I want to replace the hand-rolled agentic tool loop in `ClaudeClient` with
the Claude Agent SDK so that different task types can run on different models — cheap Haiku
for classification, Opus for deep analysis — without tangling model selection into the main
conversation flow.

---

## Background

`ClaudeClient.stream_with_tools()` in `remy/ai/claude_client.py` manually implements
a tool-use loop: call Claude → parse tool calls → execute tools → feed results back →
repeat. This works but lacks composability. Every "agent type" (board analyst, researcher,
quick assistant) shares the same loop and the same model setting.

The Claude Agent SDK (`claude-agent-sdk`) provides named subagents with their own model,
tools, and system prompts. Subagents run as independent agents and report results back —
no manual loop required.

**This is Phase 7, Step 3. Deferred until Steps 1 & 2 are proven insufficient. This is a
major refactor — do not start without explicit sign-off.**

---

## Acceptance Criteria

1. **`ClaudeClient.stream_with_tools()` is replaced** by SDK-managed agents without
   breaking any existing tool behaviour.
2. **Three named subagents defined:**
   - `quick-assistant` — `claude-sonnet-4-6`, all tools, interactive (current default)
   - `board-analyst` — `claude-opus-4-6`, read-only tools, orchestrates Board of Directors
   - `deep-researcher` — `claude-opus-4-6`, web search + file read, runs on background task
3. **Model isolation:** changing the model for `board-analyst` does not affect
   `quick-assistant`.
4. **Subagents cannot spawn subagents** — no `Task` tool in any subagent's tool list.
5. **All existing integration tests pass** after migration.
6. **Streaming still works** for `quick-assistant` (Telegram live-update experience
   preserved).

---

## Implementation Notes

**Prerequisite:** `pip install claude-agent-sdk`; evaluate API stability before committing.

**Key constraint:** The SDK replaces the `stream_with_tools` loop. Evaluate whether the
SDK supports streaming text chunks (required for `StreamingReply.feed()`) before starting.
If streaming is not supported, the interactive path must remain hand-rolled and only
non-streaming tasks (board, research) migrate to the SDK.

### Suggested subagent definitions

```python
SUBAGENTS = {
    "quick-assistant": SubagentConfig(
        model="claude-sonnet-4-6",
        tools=ALL_TOOLS,
        system=SOUL_PROMPT,
    ),
    "board-analyst": SubagentConfig(
        model="claude-opus-4-6",
        tools=READ_ONLY_TOOLS,
        system=BOARD_ORCHESTRATOR_PROMPT,
    ),
    "deep-researcher": SubagentConfig(
        model="claude-opus-4-6",
        tools=[web_search, read_file, list_directory],
        system=RESEARCHER_PROMPT,
    ),
}
```

---

## Risks

| Risk | Mitigation |
|---|---|
| SDK doesn't support streaming | Keep hand-rolled loop for interactive path |
| SDK API changes between versions | Pin version; add integration tests |
| Subagent latency higher than current loop | Benchmark before committing |
| Breaks existing tool schemas | Full regression test run required |

---

## Out of Scope

- Changes to Telegram bot handler logic
- New tool implementations
- Automated model selection based on query complexity (separate story)
