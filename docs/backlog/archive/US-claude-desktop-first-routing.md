# User Story: Claude Desktop First, Then API — Routing Hierarchy

**Status:** ✅ Implemented
**Relay prerequisites:** ✅ Inbound poller · ✅ `.mcp.json` wiring

## Summary

As Dale, I want Remy to prefer Claude Desktop (when available) over direct Claude API calls, then follow the existing model routing across Mistral, Moonshot, and Ollama, so that I maximise use of my Claude subscription and minimise redundant API costs when I'm already in a Claude session.

---

## Background

Remy currently routes all Claude traffic through the Anthropic API (`ClaudeClient`). When Dale uses Claude Desktop (e.g. chatting with Cowork via the relay MCP), that session incurs its own usage. If Remy then calls the Claude API separately for the same or related work, Dale pays twice — once for the Desktop session and once for the API.

The desired hierarchy is:

1. **Claude Desktop first** — When the Claude Code CLI is available (and can use subscription when logged in), Remy routes Claude requests there. See [Options & Recommendations](#options--recommendations).
2. **Claude API second** — If the CLI is unavailable, fall back to the existing `ClaudeClient` (Anthropic API).
3. **Existing routing** — For non-Claude paths and fallbacks, continue using the current category-based routing: Mistral, Moonshot, and Ollama as defined in `remy/ai/router.py` and `docs/architecture/model_orchestration_refactor.md`.

This story extends the routing chain without changing the Mistral/Moonshot/Ollama logic. It only inserts a "Claude Desktop" tier before "Claude API" for Claude-bound requests.

---

## Acceptance Criteria

1. **Claude Desktop availability check.** Remy can detect whether the Claude Code CLI is installed and usable (e.g. `claude --version` succeeds) before attempting a Claude request via that path.
2. **Routing hierarchy for Claude-bound requests.** When the router would otherwise call Claude (Haiku or Sonnet), it first tries Claude Desktop; on unavailability or failure, it falls back to Claude API.
3. **Existing routing preserved.** Category-based routing to Mistral, Moonshot, and Ollama remains unchanged. Only Claude-bound paths gain the Desktop-first step.
4. **Circuit breaker compatibility.** Claude Desktop and Claude API share or have separate circuit breaker state so that repeated Desktop failures do not indefinitely block API fallback.
5. **Analytics and logging.** API call log records whether the request was served by `claude_desktop` or `claude` (API), so `/routing` and cost reports reflect the distinction.
6. **Configuration.** Settings `CLAUDE_DESKTOP_ENABLED` and `CLAUDE_DESKTOP_CLI_PATH` allow enabling or disabling the Desktop-first path and specifying the `claude` binary location.

---

## Implementation

**Files:** `remy/ai/router.py`, `remy/ai/claude_desktop_client.py` (new), `remy/config.py`, `remy/analytics/call_log.py`, `docs/architecture/model_orchestration_refactor.md`.

### Approach (recommended: Option 1 — Claude Code CLI)

1. **Claude Desktop client.** Add `ClaudeDesktopClient` that:
   - Checks availability via `claude --version` (or equivalent) — succeeds if CLI is installed and logged in.
   - Streams messages via the same interface as `ClaudeClient` (`stream_message(messages, model=..., system=..., usage_out=...)`).
   - Spawns `claude -p "..." --output-format stream-json --verbose --include-partial-messages`, parses NDJSON lines for `content_block_delta` / `text_delta`, yields chunks. See [Options & Recommendations](#options--recommendations) for alternatives.

2. **Router changes.** In `ModelRouter.stream()`, for every branch that currently calls `_stream_with_fallback("claude", ...)`:
   - If `claude_desktop_enabled` and `ClaudeDesktopClient.is_available()`:
     - Call `_stream_with_fallback("claude_desktop", ...)` first.
   - In `_stream_with_fallback("claude_desktop", ...)`, on failure or unavailability, fall back to `_stream_with_fallback("claude", ...)` (not directly to Ollama).
   - Ollama remains the final fallback when both Claude Desktop and Claude API fail.

3. **Fallback chain.** For Claude-bound requests:
   ```
   claude_desktop → claude (API) → ollama
   ```
   Mistral/Moonshot paths remain: `mistral` → ollama, `moonshot` → ollama.

4. **Circuit breakers.** Use `claude_desktop` and `claude` as separate providers so that a failing Desktop does not trip the API breaker, and vice versa.

5. **Config.** Add:
   - `claude_desktop_enabled: bool = False`
   - `claude_desktop_cli_path: str = "claude"` (path to `claude` binary; default assumes it's on PATH)

### Notes

- Depends on `US-model-orchestration.md` (done) for the existing Mistral/Moonshot/Ollama routing.

---

## Options & Recommendations

Research (Claude docs, Anthropic platform) shows **Claude Desktop does not expose a programmatic inference API**. The relay MCP is for inter-agent messaging, not streaming model output. The following options are viable:

| Option | Streaming | Uses subscription? | Integration effort | Recommendation |
|-------|-----------|-------------------|--------------------|----------------|
| **1. Claude Code CLI** | ✅ Yes (`--output-format stream-json`) | ✅ Yes (if CLI logged in) | Medium — subprocess + NDJSON parsing | **Recommended** — best for Desktop-first billing |
| **2. Claude Agent SDK** | ✅ Yes (`include_partial_messages=True`) | ❌ No (API key) | Medium — new client, async iterator | Good alternative if API billing is acceptable |
| **3. Relay delegation** | ❌ No | ✅ Yes (Cowork in Desktop) | Low — relay already exists | Defer — no streaming; requires relay protocol changes |
| **4. Messages API** | ✅ Yes | ❌ No (API key) | Already in Remy | Current behaviour; fallback only |

### Option 1: Claude Code CLI (recommended for subscription-first)

- **Docs:** [Run Claude Code programmatically](https://docs.anthropic.com/en/docs/claude-code/headless)
- **Streaming:** `claude -p "prompt" --output-format stream-json --verbose --include-partial-messages`
- **Pros:** Uses Claude subscription when logged in; streams token-by-token; no new API key.
- **Cons:** Requires `claude` CLI installed; subprocess overhead; parsing NDJSON.
- **Implementation:** `ClaudeDesktopClient` spawns `claude -p "..."` with `--output-format stream-json`, parses lines for `content_block_delta` / `text_delta`, yields chunks. Availability = `claude --version` succeeds.

### Option 2: Claude Agent SDK

- **Docs:** [Agent SDK overview](https://platform.claude.com/docs/en/agent-sdk/overview), [Streaming output](https://platform.claude.com/docs/en/agent-sdk/streaming-output)
- **Install:** `pip install claude-agent-sdk`
- **Pros:** Native streaming; async; same tool loop as Claude Code (Read, Edit, Bash).
- **Cons:** Uses API key (same billing as Messages API); no subscription benefit.
- **Implementation:** `ClaudeAgentClient` wraps `query()` with `include_partial_messages=True`; filters `StreamEvent` for `text_delta`; yields chunks. Useful if Remy wants Agent SDK tools (e.g. file access) without changing the main flow.

### Option 3: Relay delegation

- **Current relay:** Messages, tasks, notes — no streaming.
- **Pros:** Cowork already in Claude Desktop; no new infra.
- **Cons:** No streaming; relay stores whole messages (max 8k chars); would need new streaming channel (WebSocket/SSE) in relay.
- **Recommendation:** Defer. Add streaming to relay in a separate story if delegation is desired.

### Option 4: Messages API (current)

- **Docs:** [Streaming Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- **Status:** Already implemented in `ClaudeClient`.
- **Role:** Fallback when CLI or Agent SDK unavailable.

### Recommended implementation path

1. **Phase 1:** Implement Option 1 (Claude Code CLI) as `claude_desktop` provider. Enables subscription-first when `claude` is installed and logged in.
2. **Phase 2 (optional):** Add Option 2 (Agent SDK) as an alternative if CLI proves unreliable or user prefers API-key auth.
3. **Out of scope:** Option 3 (relay delegation) until relay supports streaming.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Claude Desktop available, routine task | Request served by `claude_desktop` |
| Claude Desktop unavailable, routine task | Request served by `claude` (API) |
| Claude Desktop fails mid-stream | Fallback to `claude` (API), user notified inline |
| Claude Desktop disabled via config | All Claude requests go to API |
| Mistral/Moonshot routing | Unchanged; no Claude Desktop involvement |
| Circuit open for `claude_desktop` | Fallback to `claude` (API); API breaker unaffected |
| `/routing` output | Shows `claude_desktop` and `claude` as distinct providers |

---

## Out of Scope

- Changing the Mistral, Moonshot, or Ollama routing logic.
- Supporting Claude Desktop on platforms other than macOS (unless trivial).
- Billing or quota reconciliation between Claude Desktop and API (handled by Anthropic).

---

## Relay Infrastructure (prerequisite for Option 3)

Before Option 3 (relay delegation) can be revisited, two gaps in the current relay setup must be closed. These are tracked here because they directly affect whether cowork ↔ remy A2A communication is viable as a routing path.

### Gap 1 — Inbound relay poller

**Problem:** `remy/relay/client.py` is write-only. Remy can post messages to cowork but cannot receive them. When cowork writes a message with `to_agent='remy'` into `relay.db`, nothing reads it or notifies Dale.

**Fix:** Add `get_messages_for_remy()` to `remy/relay/client.py` that reads `messages WHERE to_agent='remy' AND read=0`, marks them read, and returns the results. Then add a proactive scheduler job (in `remy/scheduler/proactive.py`) that polls on a short interval (e.g. 60 s), and for each unread message/task sends a Telegram notification to Dale with the content.

**Files:** `remy/relay/client.py`, `remy/scheduler/proactive.py`

**Acceptance criteria:**
- When cowork posts `relay_post_message(to_agent="remy", ...)`, Dale receives a Telegram message within ~60 s.
- When cowork posts `relay_post_task(to_agent="remy", ...)`, Dale receives a Telegram notification with task type and description.
- Polled messages are marked `read=1` so they are not re-delivered.
- Poller is a no-op when the relay DB does not exist (graceful degradation).

### Gap 2 — MCP wiring (`.mcp.json`)

**Problem:** No `.mcp.json` exists in the project root. Claude Code sessions in this project cannot call `relay_get_messages`, `relay_post_message`, `relay_get_tasks`, etc. as tools. Additionally, when running locally the relay_mcp server defaults to `relay_mcp/relay.db` (empty) rather than `data/relay.db` (the live DB Remy writes to).

**Fix:** Add `.mcp.json` at the project root pointing `relay_mcp` at the correct DB path:

```json
{
  "mcpServers": {
    "relay_mcp": {
      "command": "python",
      "args": ["server.py", "--db", "../data/relay.db"],
      "cwd": "relay_mcp"
    }
  }
}
```

**Files:** `.mcp.json` (new), `relay_mcp/server.py` (DB path already configurable via `--db`)

**Acceptance criteria:**
- `relay_get_messages(agent="remy")` is callable as a tool in Claude Code sessions within this project.
- The relay_mcp server reads from and writes to `data/relay.db` (same DB Remy's Python client uses).
- `.mcp.json` is committed to the repo so it is available to both Remy and cowork Claude sessions.
