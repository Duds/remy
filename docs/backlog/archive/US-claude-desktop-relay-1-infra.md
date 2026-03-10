# User Story: Relay Infrastructure (SQLite + Tool Executors)

**Status:** ✅ Done  
**Parent:** [US-claude-desktop-relay](US-claude-desktop-relay.md)

## Summary

As Remy, I can read from and post to the relay inbox so that bidirectional messages are possible.

---

## Background

The relay MCP server (`relay_mcp/server.py`) already provides messages, tasks, and shared notes in its own SQLite DB. Claude Desktop (cowork) uses it to push tasks and messages to Remy. Remy currently has no way to read or reply: there are no relay tools in the ToolRegistry and no relay store in Remy’s memory layer.

This story adds the **infrastructure** only: persistence shape in Remy’s DB (so relay state can live in a shared DB or be mirrored), a `RelayToolExecutor` that implements the five relay tools, env config, and unit tests for store CRUD. UX (e.g. `/relay` command, briefing) is [Sub-task 2](US-claude-desktop-relay-2-ux.md).

**Related:** `relay_mcp/server.py` (messages, tasks, shared_notes schema), `remy/memory/database.py`, `remy/ai/tools/registry.py`, `remy/ai/tools/schemas.py`, `CLAUDE.md`.

---

## Acceptance Criteria

1. **Relay store in Remy’s DB.** A relay persistence layer exists in `memory/database.py`: tables (or a single table) that can hold relay messages, tasks, and optionally shared notes, with schema compatible with `relay_mcp` so the same DB file can be used by both Remy and the relay server when desired.

2. **RelayToolExecutor.** `remy/ai/tools/relay.py` provides a `RelayToolExecutor` with:
   - `relay_get_messages` — list messages for agent `remy`, optional unread-only, optional mark-read.
   - `relay_post_message` — send a message from `remy` to `cowork` (content, optional thread_id).
   - `relay_get_tasks` — list tasks assigned to `remy`, filter by status (e.g. pending, in_progress, done, needs_clarification, all).
   - `relay_update_task` — update task status (in_progress, done, needs_clarification) with optional result/notes.
   - `relay_post_note` — post a shared note (content, optional tags).

3. **Tool registration.** All five tools are defined in `schemas.py` (TOOL_SCHEMAS or equivalent) and registered in the ToolRegistry so Claude can call them during Remy conversations.

4. **Config.** `.env.example` documents `RELAY_MCP_URL` and `RELAY_MCP_SECRET` (and any `RELAY_DB_PATH` or similar if using direct SQLite). Implementation may use either:
   - **Direct SQLite:** Remy and relay_mcp share the same DB path; executor uses Remy’s DB connection (or a connection to that path) for CRUD.
   - **HTTP client:** Executor calls the relay MCP server over HTTP using `RELAY_MCP_URL` and `RELAY_MCP_SECRET` for auth.

5. **Unit tests.** Tests cover relay store CRUD: insert/select messages, insert/select/update tasks, insert/select notes (and mark-read behaviour for messages). Tests may run against the in-memory or file-based DB used by the executor; no need for a live MCP server in unit tests.

6. **No behavioural change to non-relay features.** Existing tools and flows are unchanged; relay is additive.

---

## Implementation

### 1. Relay tables in `memory/database.py`

Add DDL that matches `relay_mcp` so a shared DB is possible:

- **messages:** `id` (TEXT PK), `from_agent`, `to_agent`, `content`, `thread_id`, `read` (INT 0/1), `created_at`.
- **tasks:** `id` (TEXT PK), `from_agent`, `to_agent`, `task_type`, `description`, `params` (TEXT JSON), `status`, `result`, `notes`, `created_at`, `updated_at`.
- **shared_notes:** `id` (TEXT PK), `from_agent`, `content`, `tags` (TEXT JSON), `created_at`.

Add indexes as in relay_mcp (e.g. `to_agent + read`, `to_agent + status`). Apply via `_DDL` or a migration so existing deployments get the tables.

### 2. `remy/ai/tools/relay.py` — RelayToolExecutor

- Agent identity for Remy: `from_agent = "remy"`, `to_agent = "cowork"` (or configurable) when posting; when reading, filter `to_agent = "remy"`.
- Implement the five methods to read/write the relay store. If using direct SQLite, use the same DB path as the app (inject or resolve via settings). If using HTTP, call the relay MCP HTTP API with `RELAY_MCP_SECRET` (e.g. header or query) as documented by the server.
- Return structures consistent with `relay_mcp` (e.g. JSON-like dicts with `messages`, `unread_count`, `tasks`, `pending_count`, etc.) so callers and Sub-task 2 can rely on a stable shape.

### 3. Schemas and registry

- In `schemas.py`, add input schemas for: `relay_get_messages` (e.g. `unread_only`, optional `mark_read`, `limit`), `relay_post_message` (`content`, optional `thread_id`), `relay_get_tasks` (`status`), `relay_update_task` (`task_id`, `status`, optional `result`, `notes`), `relay_post_note` (`content`, optional `tags`). Match parameter names and types to `relay_mcp` where applicable.
- Register the executor and map tool names to executor methods in the ToolRegistry.

### 4. `.env.example`

Add:

```env
# ── Relay (Claude Desktop ↔ Remy) ─────────────────────────────────────────────
# URL of the relay MCP server (if Remy talks to relay over HTTP). Leave empty to use shared SQLite (same DB path as Remy).
# RELAY_MCP_URL=http://localhost:8765
RELAY_MCP_URL=
# Shared secret for relay API auth (required if RELAY_MCP_URL is set)
RELAY_MCP_SECRET=
```

If the design uses a dedicated relay DB path when not using HTTP, add e.g. `RELAY_DB_PATH` and document it.

### 5. Unit tests

- New test module (e.g. `tests/test_tools/test_relay.py` or under `tests/test_memory/`) that:
  - Creates or uses an in-memory DB with the relay tables.
  - Tests: post message → get messages (unread) → mark read → get again (optional); post task → get tasks → update task → get by status; post note → get notes.
- No dependency on a running relay_mcp process; tests exercise the store and executor logic only.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Insert message, get messages for `remy` (unread_only=True) | Message appears; unread_count ≥ 1 |
| Get messages with mark_read=True, then get again unread_only=True | Second call returns 0 unread for that message |
| Post message from remy to cowork | Row in messages with from_agent=remy, to_agent=cowork |
| Insert task, get_tasks(status=pending) | Task in list |
| Update task to in_progress then done with result | Status and result persisted; get_tasks reflects it |
| Post note with tags, get notes | Note returned with correct tags |
| Executor with no RELAY_MCP_URL (direct DB) | CRUD succeeds against Remy DB |
| All five tools registered | ToolRegistry resolves relay_* names to RelayToolExecutor |

---

## Out of Scope (this story)

- `/relay` slash command and morning briefing (Sub-task 2).
- Remy proactively creating tasks for cowork.
- relay_mcp server changes (schema is already defined there).
- E2E Desktop → Remy → Desktop test (Sub-task 2).
