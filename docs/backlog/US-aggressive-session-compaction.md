# User Story: Aggressive Session Compaction for Tool-Heavy Flows

**Status:** ✅ Done

## Summary

As a user, I want Remy to send smaller conversation histories to the model so that tool-heavy turns complete faster and don't balloon to 60k+ tokens.

---

## Background

Logs from 03/03/2026 show session compaction: **170 turns (61,173 tokens) → summary (284 tokens)**. Large histories increase input size, model processing time, and latency. Tool-heavy flows (many search_files, read_file, etc.) accumulate turns quickly.

Current compaction runs when a threshold is hit (e.g. turn count or token budget). The "recent turns" window sent with each request may still be large for long sessions. There may be room to compact more aggressively or to use a smaller recent-turns window specifically for tool-heavy sessions.

Related: `remy/memory/conversations.py`, `remy/memory/compaction.py`, `remy/bot/handlers/chat.py`, `_trim_messages_to_budget`.

---

## Acceptance Criteria

1. **Earlier compaction trigger.** Compaction runs at a lower threshold (e.g. 80 turns or 40k tokens) so sessions don't grow to 170 turns before summarising.
2. **Smaller recent-turns window for tool flows.** When the model is in a tool-heavy turn (e.g. >3 tool calls so far this turn), optionally trim the "recent turns" window more aggressively (e.g. last 10 turns instead of 20) to reduce input size.
3. **Configurable thresholds.** Compaction trigger (turn count, token budget) and recent-turns window size are configurable via settings.
4. **No loss of critical context.** Compaction summary preserves user preferences, key facts, and conversation intent. Regression tests verify summarisation quality.
5. **Telemetry.** Log compaction events (turns before/after, tokens before/after) for monitoring.

---

## Implementation

**Files:** `remy/config.py`, `remy/memory/conversations.py`, `remy/memory/compaction.py`, `remy/bot/handlers/chat.py` (or pipeline).

- Add settings: `compaction_turn_threshold`, `compaction_token_threshold`, `recent_turns_window`, `recent_turns_window_tool_heavy`.
- In `ConversationStore` or compaction logic, trigger compaction when either threshold is exceeded.
- In `_trim_messages_to_budget` or equivalent, when `tool_calls_this_turn > N`, use the smaller `recent_turns_window_tool_heavy`.
- Ensure compaction summary includes: user facts, goals, and recent intent. Validate with existing compaction tests.

### Notes

- Compaction quality is critical; aggressive summarisation must not drop user-specific context.
- The "tool-heavy" detection may need to be passed from the stream loop (which knows tool count) into the message-trimming logic.
- See `remy/memory/compaction.py` for current Claude summarisation and fallback behaviour.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Session at 80 turns | Compaction triggered (if threshold=80) |
| Session at 40k tokens | Compaction triggered (if threshold=40k) |
| Tool-heavy turn, 15 recent turns | Only last 10 included (if window_tool_heavy=10) |
| Normal turn, 15 recent turns | Full window (e.g. 20) included |
| Post-compaction reply | Model still has user context (name, preferences) |

---

## Out of Scope

- Changing the compaction summarisation algorithm.
- Per-user or per-session custom thresholds.
- Streaming compaction (background summarisation during idle).
