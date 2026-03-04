# User Story: /relay Command + Briefing Hook

**Status:** ✅ Done  
**Parent:** [US-claude-desktop-relay](US-claude-desktop-relay.md)  
**Depends on:** [US-claude-desktop-relay-1-infra](US-claude-desktop-relay-1-infra.md)

## Summary

As Dale, I can check the relay inbox from Telegram and Remy surfaces pending messages in the morning briefing.

---

## Background

Sub-task 1 adds the relay store and `RelayToolExecutor` (relay_get_messages, relay_post_message, relay_get_tasks, relay_update_task, relay_post_note). This story adds the **UX**: a `/relay` slash command so Dale can see what’s in the relay without asking in natural language, and an optional hook in the morning briefing so Remy mentions unread relay traffic. It also ensures the tools are wired so Claude auto-calls them when appropriate (e.g. at session start per CLAUDE.md) and adds an integration test for a full Desktop → Remy → Desktop round-trip.

**Related:** `remy/bot/handlers.py`, proactive/briefing flow, `CLAUDE.md`, `config/SOUL.compact.md`.

---

## Acceptance Criteria

1. **`/relay` slash command.** A `/relay` command is registered in the bot. When Dale sends `/relay`, Remy shows:
   - Unread relay messages (from cowork) with count and short summary or list.
   - Pending relay tasks assigned to Remy with count and short summary or list.
   - If the inbox is empty: a clear “Relay inbox is clear — nothing from cowork.” (or similar).

2. **Natural language.** Phrases like “check my relay inbox”, “what’s in the relay?”, “any messages from cowork?” continue to be handled via the same relay tools (no separate handler required beyond tool use).

3. **Morning briefing (optional).** If the morning briefing runs, it may check the relay inbox (same pattern as calendar/email). If there are unread messages or pending tasks from cowork, include a one-liner in the briefing (e.g. “📬 1 unread message from cowork.” / “📋 2 pending tasks from cowork.”). Omit if empty.

4. **Tools wired for Claude.** `relay_get_messages` and `relay_get_tasks` are available and described so that Claude is encouraged to call them at session start (or when the user asks about relay/cowork). No change to Sub-task 1’s registration; this story only confirms wiring and any prompt/session-start behaviour.

5. **Integration test.** An integration test (or E2E scenario) covers a full round-trip: Desktop (cowork) posts a message or task → Remy reads it (via tool or `/relay`) → Remy posts a reply or updates the task → Desktop can read the reply/result. Test may use a shared SQLite DB or a running relay_mcp instance, as long as the path is automated.

6. **SOUL / docs.** Capabilities in `SOUL.compact.md` (or equivalent) mention relay; Commands list includes `/relay`.

---

## Implementation

### 1. `/relay` in `bot/handlers.py`

- Register a command handler for `relay` (e.g. `CommandHandler("relay", _handle_relay)` or the project’s pattern).
- Handler implementation:
  - Call the relay executor (or tool layer) to get unread messages and pending tasks for agent `remy` (e.g. `relay_get_messages(unread_only=True)` and `relay_get_tasks(status="pending")`).
  - Format a single Telegram message: e.g. “📬 N unread message(s)”, list or summary of messages; “📋 M pending task(s)”, list or summary of tasks; or “Relay inbox is clear — nothing from cowork.”
  - Handle errors (e.g. relay unavailable) with a user-friendly message; no crash.

### 2. Morning briefing hook (optional)

- Locate the morning briefing builder (e.g. `ProactiveScheduler._morning_briefing()` or equivalent).
- Add a relay check: call `relay_get_messages(unread_only=True)` and `relay_get_tasks(status="pending")`. If either returns non-empty, append a line to the briefing (e.g. “📬 1 unread message from cowork.” / “📋 2 pending tasks from cowork.”). If both empty, add nothing.

### 3. Claude session-start / wiring

- Ensure system prompt or session-start instructions (e.g. in CLAUDE.md or Remy’s injected context) tell Claude to call `relay_get_messages` and `relay_get_tasks` at the start of a session when acting as Remy. Sub-task 1 already registers the tools; this story only confirms they are invoked as intended (no code change required if already documented in CLAUDE.md).

### 4. Integration test

- Add a test that:
  - Seeds the relay store (or calls relay_mcp) with one message or task for `remy`.
  - Invokes the code path that reads the relay (e.g. `/relay` handler or direct executor calls).
  - Asserts the message/task is returned.
  - Has Remy post a reply or update the task.
  - Asserts the reply/update is visible (e.g. cowork can read it via relay_get_messages or relay_get_tasks). Use shared DB or a test relay instance; avoid manual steps.

### 5. SOUL.compact.md

- **Capabilities:** Add “Relay (read/reply cowork inbox, task updates)” or similar.
- **Commands:** Add `/relay — show pending relay inbox from cowork`.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Dale sends `/relay`, inbox has 1 unread message | Remy replies with count and message summary/list |
| Dale sends `/relay`, inbox has 2 pending tasks | Remy replies with count and task summary/list |
| Dale sends `/relay`, inbox empty | “Relay inbox is clear — nothing from cowork.” (or equivalent) |
| Morning briefing runs, 1 unread message | Briefing includes a line about 1 unread message from cowork |
| Morning briefing runs, relay empty | No relay line in briefing |
| Cowork posts message → Remy reads → Remy replies | Integration test: reply visible to cowork side |
| Cowork posts task → Remy claims and completes | Integration test: task status and result visible to cowork side |

---

## Out of Scope

- Remy initiating tasks to cowork (separate story).
- Changing relay_mcp server API or schema.
- Extra slash commands beyond `/relay` for relay (this story).
