# Relay Feature Removal

**Date:** 10/03/2026  
**Status:** Completed  

This document records the complete removal of the **Relay** feature from Remy and the reasoning behind it.

---

## 1. What was removed

The Relay feature provided inter-agent communication between **Remy** (Telegram bot) and **cowork** (Claude Desktop / Cursor): messages, tasks, and shared notes via a shared MCP server and SQLite database.

### 1.1 Deleted code and assets

| Item | Description |
|------|--------------|
| `relay_mcp/` | Entire MCP server (FastMCP): `server.py`, `__init__.py`, `Dockerfile`, `requirements.txt` |
| `remy/relay/` | Python client for Remy to read/write relay DB: `client.py`, `__init__.py` |
| `remy/ai/tools/relay.py` | Tool executors: `relay_get_messages`, `relay_post_message`, `relay_get_tasks`, `relay_update_task`, `relay_post_note`, `relay_create_task` |
| `docs/relay-setup.md` | Setup guide for shared relay backend |
| `tests/test_relay.py`, `tests/test_tools/test_relay.py`, `tests/test_relay_mcp_server.py` | Relay-related tests |

### 1.2 Removed or changed behaviour

- **Tool registry:** All `relay_*` tool cases removed from `remy/ai/tools/registry.py`.
- **Tool schemas:** All relay tool definitions and the `forward_to_cowork` option in `suggest_actions` removed from `remy/ai/tools/schemas.py`.
- **Callbacks:** `forward_to_cowork_*` handler and [Send to cowork] button support removed from `remy/bot/handlers/callbacks.py`; `relay_post_message` parameter removed from `make_callback_handler`.
- **Config:** `relay_mcp_url`, `relay_mcp_secret`, `relay_db_path`, `relay_can_create_tasks`, and `relay_db_path_resolved` removed from `remy/config.py`.
- **Database schema:** Relay tables (`messages`, `tasks`, `shared_notes`) removed from main DDL in `remy/memory/database.py` (new installs no longer create them).
- **Heartbeat:** `requeue_stuck_relay_tasks()` and its invocation removed from `remy/scheduler/heartbeat.py`.
- **Proactive scheduler:** `_poll_relay_inbox` job and method removed from `remy/scheduler/proactive.py`.
- **Morning briefing:** Relay section, relay payload fields, and `_build_relay_section()` removed from `remy/scheduler/briefings/morning.py`.
- **Pipeline:** Morning-briefing prompt no longer mentions `relay_unread` / `relay_pending`.
- **Docker:** `relay` service removed from `docker-compose.yml`; `remy-up` starts only `remy` and `ollama`.
- **Makefile:** All relay targets removed (`relay-up`, `relay-run`, `relay-stop`, `relay-check`, `relay-setup-check`, `relay-verify`, `relay`); `remy-up` and comments updated.
- **MCP config:** `.mcp.json` no longer defines `relay_mcp` (empty `mcpServers` or project-specific only).
- **Health / webhooks:** Example webhook events changed from `relay_task_done` to `plan_step_complete` in `remy/health.py` and `remy/webhooks.py`.
- **Docs:** `docs/README.md`, `docs/agent-tooling-setup.md`, `docs/architecture/concept-design.md`, `docs/architecture/HLD.md` updated to remove relay; relay-related bugs (Bug 2, 3, 4) removed from `BUGS.md`.
- **Tests:** `test_forward_to_cowork_calls_relay` removed from `tests/test_callbacks.py`; relay tool entries removed from `tests/integration/test_tool_dispatch_coverage.py`.

---

## 2. Reasoning for removal

- **Simplification:** Relay added a second process, a second DB, and cross-agent wiring (Remy ↔ cowork). Removing it reduces moving parts, config surface, and failure modes (e.g. shared-backend bugs, MCP SDK quirks).
- **Limited use:** The feature depended on both Remy and cowork being configured against one shared relay; in practice, usage was low and handoff was often done manually (copy-paste).
- **Maintenance cost:** Relay had its own bugs (e.g. request_context, cross-agent delivery), tests, and docs. Keeping it required ongoing care for a rarely used path.
- **Scope focus:** Remy’s core value is the Telegram-first assistant with memory, calendar, email, goals, and proactive heartbeat. Inter-agent relay is out of scope for the current product focus; handoff can be manual or revisited later with a clearer design.

---

## 3. Impact on users

- **Send to cowork:** The [Send to cowork] inline button and `/relay`-style behaviour are gone. Users who want to move content to Cursor/Claude Desktop can copy-paste or use other workflows.
- **Cursor/Claude Desktop:** Any project or global MCP config that pointed at the Remy relay server will no longer have those tools; remove or update `relay_mcp` (or equivalent) from `.cursor/mcp.json` and Claude Desktop config.
- **Session hooks:** If you had Cursor hooks that called `relay_get_messages` or `relay_get_tasks` at session start (e.g. “If you are Remy, run relay_get_messages…”), remove or update those hooks; the tools no longer exist.
- **Existing data:** Existing `data/relay.db` (or relay tables in the main DB) are not migrated or deleted by this change; you can delete `data/relay.db` manually if desired.

---

## 4. References

- Backlog stories (for context only; no code): `docs/backlog/US-claude-desktop-relay.md`, `US-relay-shared-backend.md`, `US-send-to-cowork.md`, `US-relay-forward-to-cowork-feedback.md`, etc.
- Historical SAD/HLD may still mention relay in diagrams or appendices; treat as superseded by this removal and the updated HLD and concept-design.

---

*End of relay removal document.*
