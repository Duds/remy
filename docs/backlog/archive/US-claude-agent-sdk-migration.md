# User Story: Complete Claude Agent SDK Migration and Deprecate Hand-Rolled Tool Loop

**Status:** ✅ Done

## Summary

As a developer, I want the main conversation and heavy tasks (board, research, retrospective) to run through the Claude Agent SDK with three named subagents, and the old hand-rolled tool loop and in-process runners to be deprecated and removed, so that we have a single, maintainable agent layer with clear model isolation and no duplicate code paths.

---

## Background

**Partial work already done:** `claude-agent-sdk` is in requirements; `remy/agents/sdk_runner.py` exists as a stub (optional research via SDK when `REMY_USE_SDK_SUBAGENTS=1`). The archived [US-claude-agent-sdk-subagents](archive/US-claude-agent-sdk-subagents.md) describes the full intent.

**Current state (post-migration):** Chat, board, and research use the Claude Agent SDK. `stream_with_tools` delegates to `sdk_subagents.run_quick_assistant_streaming` and raises when the SDK is not available. Hand-rolled tool loop and in-process BoardOrchestrator fallback removed.

**Goal:** Use the SDK as the single agent runtime. Define three subagents (quick-assistant, board-analyst, deep-researcher). Deprecate and then remove the old loop and the in-process-only paths so there is one code path, with the SDK handling streaming and tool execution.

---

## Acceptance Criteria

1. **SDK is the single agent runtime.** All interactive tool use and all fire-and-forget heavy tasks (board, research, retrospective) are executed via the Claude Agent SDK. No second path that bypasses the SDK.
2. **Three named subagents are defined and used:**
   - **quick-assistant** — default for chat; `claude-sonnet-4-6` (or configurable); all tools; SOUL system prompt. Used by the main Telegram conversation path. **Streaming is preserved** (live Telegram updates).
   - **board-analyst** — read-only tools; board orchestrator system prompt; used when user requests Board of Directors. Runs as a background task; result delivered via existing job_store + Telegram.
   - **deep-researcher** — web search + file read (and any other tools needed for research); researcher system prompt; used for `/research` and research hand-off. Runs as background task; result delivered via job_store + Telegram.
3. **Model isolation.** Each subagent has its own model config (e.g. board-analyst and deep-researcher can use Opus; quick-assistant Sonnet). Changing one does not affect the others.
4. **Subagents cannot spawn subagents.** No `hand_off_to_researcher`, `run_board`, or equivalent “task” tool in the board-analyst or deep-researcher tool lists (they do one job and return).
5. **Old code is deprecated then removed:**
   - **Deprecate:** `ClaudeClient.stream_with_tools()` — add a deprecation warning and route callers to the SDK-based path (or a thin wrapper that uses the SDK).
   - **Deprecate:** In-process-only board path (direct use of `BoardOrchestrator` for the `/board` flow) — board must run via SDK board-analyst subagent.
   - **Deprecate:** In-process-only research path (`run_research_coro` used without SDK) — research must run via SDK deep-researcher subagent.
   - **Remove:** After migration and green tests, remove the deprecated implementation: the hand-rolled tool loop in `claude_client.py`, and any now-dead code paths (e.g. the non-SDK branch in `sdk_runner.py` or duplicate research/board runners).
6. **All existing integration tests pass** after migration. Add or update tests for SDK-based board and research.
7. **Streaming for quick-assistant** works end-to-end (Telegram receives incremental updates as the SDK streams).

---

## Implementation

**Files to create or heavily modify:**

- `remy/agents/sdk_subagents.py` (or extend `sdk_runner.py`) — define the three subagent configs (model, tools, system prompt); expose `run_quick_assistant` (streaming), `run_board_analyst`, `run_deep_researcher`, `run_retrospective` (or map retrospective to a subagent or keep a single non-streaming SDK call).
- `remy/ai/claude_client.py` — add SDK-based entry point that preserves the existing `stream_with_tools` *interface* (async generator of events) so chat/pipeline/tui callers do not need to change signatures; implement that generator by driving the SDK (e.g. quick-assistant with streaming). Mark the current hand-rolled `stream_with_tools` implementation as deprecated and remove it once the SDK path is the default and tests pass.
- `remy/bot/handlers/chat.py` — ensure the tool stream path calls the new SDK-backed client (or the same `stream_with_tools` method that now delegates to the SDK).
- `remy/bot/handlers/automations.py` — `/board` creates job and invokes SDK board-analyst (no direct `BoardOrchestrator.run_board_streaming`).
- `remy/bot/handlers/web.py` — research path invokes SDK deep-researcher (remove reliance on `run_research_coro` as the primary path; SDK is the only path).
- `remy/bot/handlers/admin.py` — retrospective invokes SDK or a single SDK call (no change to job + delivery pattern; only the execution backend switches to SDK).
- `remy/agents/subagent_runner.py` — if still used for hand-off, have it call SDK subagents instead of `claude_client.stream_with_tools`.
- `remy/agents/orchestrator.py` — **deprecate** for direct use from `/board`; board logic may be reimplemented inside the board-analyst subagent prompt/tools or a thin wrapper that calls the SDK. Remove or reduce to a legacy fallback that is never used in production.
- `remy/agents/sdk_runner.py` — replace stub with the real SDK runner used by the three subagents; remove `REMY_USE_SDK_SUBAGENTS` gating (SDK is always used) or keep it only for emergency fallback during rollout.

**Deprecation sequence:**

1. Implement SDK path alongside existing code; feature-flag or config to switch (e.g. `REMY_USE_SDK_SUBAGENTS=1` = use SDK).
2. Switch default to SDK; run full test suite and fix regressions.
3. Add deprecation warnings to `stream_with_tools` (hand-rolled) and to direct `BoardOrchestrator` / `run_research_coro` usage in handlers.
4. Remove hand-rolled loop and deprecated call paths; delete dead code.

**Tool lists:**

- quick-assistant: all tools from current `TOOL_SCHEMAS` (excluding any “spawn subagent” tool if that would create nested subagents).
- board-analyst: read-only (e.g. get_facts, get_goals, get_logs, read_file, calendar, gmail read, etc.); no `run_board`, no `hand_off_to_researcher`, no write/delete tools.
- deep-researcher: web_search, read_file, list_directory (and any other read-only tools needed for research); no board, no hand-off.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| User sends a chat message that triggers tool use | quick-assistant (SDK) streams reply; Telegram shows incremental updates |
| User sends `/board <topic>` | Job created; SDK board-analyst runs; result delivered via Telegram; no in-process BoardOrchestrator |
| User sends `/research <topic>` | Job created; SDK deep-researcher runs; result delivered; no run_research_coro path |
| User requests retrospective | SDK or single SDK call; result delivered as today |
| All integration tests (tool dispatch, board, research, etc.) | Pass without modification or with updated mocks to SDK |
| Hand-rolled stream_with_tools removed | No code path calls the old implementation |

---

## Out of Scope

- Adding new tools or new subagent types (separate stories).
- Automated model selection by query complexity (separate story).
- Changing Telegram bot handler structure beyond wiring to the SDK-backed client.

---

## Dependencies

- Completed: dependency `claude-agent-sdk`, stub in `remy/agents/sdk_runner.py` (see archived US-claude-agent-sdk-subagents).
- Subagents next plan (board/research/retro via runner + job_store) is done; this US switches those runners to SDK subagents and removes the old loop.
