# User Story: Single Shared Relay Backend (Fix Remy ↔ Cowork Delivery)

**Status:** ✅ Done

**Fixes:** [Bug 3](../../BUGS.md) (Relay cross-agent messages not delivered), [Bug 4](../../BUGS.md) (Forward-to-cowork shows success but message not delivered)

## Summary

As Dale, I want Remy and cowork (Claude Desktop) to use one relay backend so that messages and tasks sent from either agent are visible to the other, and [Send to cowork] actually delivers.

---

## Background

Today Remy and cowork each talk to their own relay_mcp process and/or DB:

- **Remy (Cursor):** `.mcp.json` (or project MCP config) runs `relay_mcp/server.py --stdio --db data/relay.db`. Each Cursor session spawns its own process using `data/relay.db` in the remy repo.
- **Cowork (Claude Desktop):** Uses a separate MCP config (outside this repo), often with a different CWD or `--db` path, so it uses a different DB (e.g. `relay_mcp/relay.db` elsewhere).

Messages written by Remy never appear in cowork’s inbox and vice versa. The relay MCP already supports a single HTTP server and one DB; both agents must be configured to use that shared endpoint instead of per-client stdio.

**Related:** `BUGS.md` (Bug 3, Bug 4), `relay_mcp/server.py`, `remy/relay/client.py`, `Makefile` (relay-run, relay-up), `.cursor/mcp.json` (HTTP relay entry).

---

## Acceptance Criteria

1. **Single relay process.** One relay server process runs (e.g. `make relay-run` or `make relay-up`) with a single `--db` path (e.g. `data/relay.db` in the remy repo or a documented shared path).

2. **Remy uses the shared backend.** Remy (when running in Cursor for this project) connects to the relay via the shared HTTP endpoint (e.g. `http://127.0.0.1:8765/mcp`), not stdio. So Remy’s MCP config for the relay points at that URL (or via mcp-proxy), and Remy’s Python `post_message_to_cowork` path uses the same DB (either by using the relay HTTP API or by pointing at the same `data/relay.db` file that the shared server uses).

3. **Cowork uses the same backend.** Claude Desktop’s MCP config is updated (outside this repo, but documented here) so cowork connects to the same relay server (HTTP) and thus the same DB. Agent names are consistent: `remy` and `cowork` (lowercase).

4. **End-to-end delivery.** Remy posting a message (via [Send to cowork] or `relay_post_message`) results in that message being visible to cowork at next `relay_get_messages`; cowork posting to Remy is visible to Remy’s relay tools and `/relay`.

5. **Documentation.** README or `docs/` describes how to run the shared relay and how to point Cursor (Remy) and Claude Desktop (cowork) at it. Any project-specific override (e.g. Cursor using HTTP relay instead of stdio when in remy) is documented.

6. **Optional: Cursor project override.** If the remy repo’s MCP config currently starts relay via stdio, add or document an override so that when working in this project, Cursor uses the shared HTTP "relay" server from `.cursor/mcp.json` (or equivalent) instead of spawning a per-session stdio relay.

---

## Implementation

**Files:** `Makefile` (existing relay-run/relay-up), `README.md` or `docs/relay-setup.md`, `.cursor/mcp.json` or project MCP config, `.env.example` (RELAY_MCP_URL if used by Remy’s Python client), and Claude Desktop config (documented only, outside repo).

### 1. Confirm shared relay server and DB

- Ensure `make relay-run` (and Docker `make relay-up` if used) start a single HTTP server with `--db data/relay.db` (or a documented path). No code change if already so.

### 2. Remy → shared backend

- **If Remy uses MCP for relay:** Update Cursor MCP config for this project so the "relay" server is the HTTP endpoint (e.g. `http://127.0.0.1:8765/mcp`) instead of stdio. That may mean removing or overriding the stdio `relay_mcp` entry so the shared "relay" from `.cursor/mcp.json` is used when working in remy.
- **If Remy uses Python-only relay (e.g. `remy/relay/client.py`):** Ensure `post_message_to_cowork` and relay reads use the same DB as the shared server. Today the client uses `settings.data_dir` → `data/relay.db`. As long as the shared server uses that same path when run from the remy repo, no change. If the shared server is run elsewhere, add `RELAY_DB_PATH` (or use `RELAY_MCP_URL` for an HTTP client) and document it.

### 3. Cowork → same backend (documentation)

- Add a short doc (e.g. `docs/relay-setup.md` or a section in README) that explains:
  - Run the shared relay: `make relay-run` (and ensure one DB path).
  - Point Claude Desktop at that server via HTTP (mcp-proxy or native HTTP MCP if supported), with the same base URL.
  - Use agent names `remy` and `cowork` (lowercase).

### 4. Verification

- Add a manual or automated check: Remy posts a message → cowork (or a test script) reads messages and sees it; and the reverse. Can be a short "Verification" section in the doc or an integration test that uses the shared DB.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Start shared relay with `make relay-run` | One process, one DB file |
| Remy sends via [Send to cowork] | Message appears in relay DB and cowork’s `relay_get_messages` |
| Cowork sends to Remy | Message appears in Remy’s relay inbox / `/relay` |
| Both agents use same DB path | Same rows visible to both |
| Doc updated | README or docs/relay-setup.md describes steps for Cursor + Claude Desktop |

---

## Out of Scope

- Changing relay_mcp protocol or schema.
- Remy-specific UX copy changes for "Sent to cowork" (see [US-relay-forward-to-cowork-feedback](US-relay-forward-to-cowork-feedback.md)).
- Running relay in production (this story is about local/single-machine setup).
