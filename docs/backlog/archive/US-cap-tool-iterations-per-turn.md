# User Story: Cap Tool Iterations Per Turn to Reduce Round-Trip Latency

**Status:** ✅ Done

## Summary

As a user, I want Remy to complete my requests with fewer tool rounds per turn so that replies feel faster and I don't wait 1–4 minutes for complex queries.

---

## Background

Telemetry from 03/03/2026 shows tool execution dominates round-trip latency (~5.4 s avg per turn). Some turns hit 6–12+ sequential tool calls, with outliers reaching 235 s. One turn hit `max iterations (8)` and was cut off. The model often chains many tools (search_files, read_file, append_file, find_files, web_search) before replying.

Current `stream_with_tools` in `remy/ai/claude_client.py` uses a configurable `max_iterations` (default 8). There is no early-exit when the model has sufficient information, and no guidance to batch or combine tool calls.

Related: `remy/ai/claude_client.py`, `remy/bot/pipeline.py`, telemetry in `remy/analytics/call_log.py`.

---

## Acceptance Criteria

1. **Configurable cap.** `max_iterations` is configurable via settings (e.g. `ANTHROPIC_MAX_TOOL_ITERATIONS`) with a sensible default (e.g. 6).
2. **Graceful truncation.** When the cap is hit, Remy sends a coherent reply with what it has (e.g. "I've gathered X, Y, Z. Here's what I found so far…") rather than failing or leaving the user hanging.
3. **Telemetry.** When a turn hits the cap, log it (e.g. `max_iterations_reached`) for monitoring.
4. **No regression.** Simple queries (1–3 tool calls) behave unchanged.
5. **Prompt hint (optional).** System prompt or tool descriptions encourage batching related tool calls where feasible.

---

## Implementation

**Files:** `remy/config.py`, `remy/ai/claude_client.py`, `config/SOUL*.md` (if adding prompt hint).

- Add `anthropic_max_tool_iterations: int = 6` to `Settings`.
- Pass the value into `stream_with_tools()`.
- On `max_iterations` hit: include a hint in the final assistant message context so the model can synthesise a partial reply.
- Log `max_iterations_reached` in the stream loop when the cap is hit.

### Notes

- Consider a separate "soft cap" (e.g. 4) that triggers a prompt nudge: "You have used N tools. Synthesise a reply with what you have unless one more tool call is essential."
- Depends on understanding the current `max_iterations` flow in `claude_client.py`.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Turn with 2 tool calls | Completes normally |
| Turn with 7 tool calls, cap=6 | Stops at 6; model synthesises reply with available info |
| Cap hit | `max_iterations_reached` logged |
| Simple "what time is it?" | Single tool, no change |

---

## Related

- **US-step-limit-buttons** — When the cap is hit, the truncation message now includes inline buttons [Continue] [Break down] [Stop] for one-tap next actions.

---

## Out of Scope

- Changing which tools are available.
- Parallelising tool execution (separate story).
- Per-tool-type caps (e.g. limit web_search only).
