# Subagents Next Plan

**Status:** In progress (first milestone done: board via subagent runner)

Concrete evaluation and implementation plan so Remy becomes UI-only for heavy tasks and board, research, retrospective (and optionally reindex/consolidate) run as subagents. See [remy-ui-and-subagent-boundary.md](../architecture/remy-ui-and-subagent-boundary.md) for the boundary spec and [US-claude-agent-sdk-subagents.md](US-claude-agent-sdk-subagents.md) for the full subagent story.

---

## 1. Goal

- Remy becomes UI-only for heavy tasks; board, research, retrospective run as subagents.
- First milestone: one subagent running via a runner that Remy invokes and that delivers results back.

---

## 2. Prerequisites

- **Evaluate `claude-agent-sdk`:** Install, check API stability, **streaming support** (required for keeping quick-assistant interactive). If the SDK does not stream, keep the hand-rolled loop for that path and only migrate non-streaming tasks to subagents.
- **Scope:** Migrate only fire-and-forget tasks first (board, research, retrospective) so streaming for the main chat path remains unchanged.

---

## 3. Evaluation steps (do first)

- Add `claude-agent-sdk` to a dev branch or spike; run a minimal example (one subagent, one tool).
- Confirm whether the SDK supports streaming text chunks; document the result in this doc.
- **If no streaming:** Document that quick-assistant stays on current `ClaudeClient.stream_with_tools()`; only board, research, retrospective (and similar) move to SDK subagents.

**Evaluation result (implemented):** The Claude Agent SDK Python package (`claude-agent-sdk`) supports streaming. Set `include_partial_messages=True` in `ClaudeAgentOptions`; handle `StreamEvent` with `content_block_delta` / `text_delta` for text chunks. Quick-assistant can remain on the hand-rolled loop until we migrate; board/research/retro are fire-and-forget and can move to SDK subagents when we integrate the SDK.

---

## 4. First subagent and migration order

**Recommended first subagent:** board (or research). Reason: already fire-and-forget, clear input (topic), single text output, existing job tracking.

**Migration order suggestion:**

1. Board
2. Research
3. Retrospective

Reindex/consolidate can stay as in-process background tasks initially unless we want them as subagents later.

**For "board" as first:** Define a thin **subagent runner** in Remy that accepts (`task_type=board`, topic, user_id, chat_id, thread_id, memory_snippet), starts the SDK subagent (or a dedicated process/thread running board-analyst), and on completion calls the same delivery path Remy uses today (`send_message` + `job_store.set_done`). Remy's `/board` handler then becomes: validate input → create job → start working message + chat action → call runner → return.

---

## 5. What stays in Remy (unchanged)

- All Telegram handling, session, memory injection (for context passed to subagents).
- Job store (create job, set_running, set_done/set_failed); WorkingMessage and chat action (upload_document) while waiting.
- Delivery of subagent result to the user (and topic-aware messaging).
- Interactive path: still uses `stream_with_tools` for the default conversational flow until/unless the SDK supports streaming and we migrate that too.

---

## 6. Acceptance criteria (first milestone)

- One heavy task (e.g. board) is executed by a subagent (SDK or equivalent), not by in-process `BoardOrchestrator`.
- Remy's `/board` handler only: parses input, creates job, shows working state, invokes runner, and delivers result when runner calls back.
- No regression: existing tests for board (or chosen first task) still pass; integration test added or updated for "board via subagent."

---

## 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| SDK doesn't support streaming | Keep hand-rolled loop for interactive path; migrate only fire-and-forget tasks to SDK. |
| SDK API stability / version churn | Pin version; add integration tests. |
| Subagent latency higher than current loop | Benchmark before committing. |
| Breaks existing tool schemas | Full regression test run required. |

See also [US-claude-agent-sdk-subagents.md](US-claude-agent-sdk-subagents.md).
