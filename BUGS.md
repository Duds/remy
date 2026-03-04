# Remy Bug Report

_Last updated: 2026-03-04_

Archived bugs 1–41 (all fixed) → [docs/archive/BUGS-archived-2026-03-04.md](docs/archive/BUGS-archived-2026-03-04.md)

---

## Bug 2: Relay MCP tools fail with 'str' object has no attribute 'request_context'

- **Symptom:** `relay_get_tasks` and `relay_get_messages` (and other relay_mcp tools) fail immediately with `AttributeError: 'str' object has no attribute 'request_context'` when called from Claude Desktop (cowork) or Cursor.
- **Impact:** Relay between Cowork and Remy is completely non-functional — no messages or tasks can be read or posted via the MCP server.
- **Root cause:** The MCP Python SDK does not inject a request context object as the second argument to tool handlers; it can pass a string (e.g. request ID). The server was using `ctx.request_context.lifespan_state["db"]`, so `ctx` was a string.
- **Status:** ✅ Fixed
- **Location:** `relay_mcp/server.py`
- **Fix:** Removed the `ctx` parameter from all nine tool handlers. DB connection is now held in a module-level `_db_connection` set during lifespan and accessed via `_get_db()`. Handlers take only the Pydantic `params` argument.
- **Reported:** 2026-03-03 (Dale Rogers)
- **Fixed:** 2026-03-04

---

## Bug 1: `react_to_message` still emitting "✓" tick message — Bug 35 regression

- **Symptom:** After calling `react_to_message` as the sole response, a standalone "✓" (or similar tick character) is still sent as a separate Telegram text message. Thought to have been fixed in Bug 35 (archived).
- **Evidence:** Log entry `2026-03-04 00:11:38` shows `react_to_message` executing successfully. Despite Bug 35's fix, the "✓" text message is still appearing in the conversation alongside the emoji reaction.
- **Impact:** Same as Bug 35 — defeats the purpose of using a reaction instead of a text reply. Conversational noise.
- **Root cause:** Bug 35 fix was applied only to `chat.py`. The `handlers.py` path had no react_to_message handling. Additionally, `_flush_display` could edit to "✓" before the delete logic ran when `reply_markup` was present.
- **Related:** Bug 35 (archived), Bug 10 (archived — streaming "✓" fallback logic)
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Location:** `remy/bot/handlers/chat.py`, `remy/bot/handlers.py`, `remy/bot/pipeline.py`
- **Fix:** Reordered logic to check for `react_to_message`-only BEFORE `_flush_display`, then delete the status message instead of editing to "✓". Added identical handling to `handlers.py` (was missing entirely) and `pipeline.py`. Used `_REACTION_ONLY_TOOLS = frozenset({"react_to_message"})` for clarity. Wrapped delete in `try/except BadRequest` and log failures at DEBUG.
- **Reported:** 2026-03-04
- **Fixed:** 2026-03-04

---

## Bug 3: Relay cross-agent messages not delivered — Remy ↔ Cowork routing broken

- **Symptom:** `relay_post_message` executes successfully and returns a message ID on Remy's side. Cowork's `relay_get_messages` returns empty — no messages ever arrive. The reverse is also true: no messages from cowork have ever appeared in Remy's relay inbox. Both agents are effectively isolated despite the relay MCP appearing functional on each end individually.
- **Evidence:**
  - Remy sent messages with IDs `4882d954`, `446801bd`, `914baf90`, `bb559afd` — none were received by cowork.
  - Cowork relay inbox has remained empty throughout the session.
  - Remy relay inbox also empty — no inbound messages from cowork.
  - APScheduler log shows `_poll_relay_inbox` jobs running (and occasionally missing their slot), confirming polling is active but finding nothing.
  - No relay-specific errors logged on Remy's side — tool calls return success, so the failure is silent.
- **Impact:** Complete failure of Remy ↔ Cowork communication channel. Multi-agent coordination (task delegation, shared notes, cross-agent queries) is non-functional.
- **Root cause (suspected):** One or more of:
  1. **Different relay backend instances** — Remy and cowork may be connecting to different relay server processes or databases, so messages written by one are never visible to the other.
  2. **Agent name/address mismatch** — Remy sends to `"cowork"` but the registered agent name in the relay backend may differ (e.g. capitalisation, spacing, or a different identifier entirely).
  3. **Shared DB not shared** — Both agents may have their own local SQLite relay DB rather than pointing at a single shared instance (network path, shared volume, or single server process).
  4. **relay_mcp server not running as a shared service** — If each Claude instance spins up its own MCP server process, there's no shared state between them.
- **Status:** 🔴 Open
- **Priority:** High
- **Location:** `relay_mcp/server.py`, relay MCP config (both Remy and cowork sides)
- **Suggested investigation:**
  1. Confirm both agents are configured to connect to the *same* relay MCP server URL/socket (check `mcp_settings.json` / `claude_desktop_config.json` on both sides).
  2. Check whether the relay DB is a single shared file or two separate instances — `sqlite3 <path> "SELECT * FROM messages ORDER BY created_at DESC LIMIT 10;"` on both sides to compare.
  3. Verify agent name registration — what name does cowork register as? What name does Remy address messages to?
  4. If relay runs as a subprocess per-client (stdio transport), consider switching to a persistent HTTP/SSE server so both agents share one process and one DB.
- **Investigation (2026-03-04):**
  - **Cause:** Remy and cowork almost certainly talk to **different relay_mcp processes and/or different DB files**.
  - **Remy (Cursor):** `.mcp.json` runs `relay_mcp/server.py --stdio --db data/relay.db`. Each Cursor session spawns its **own** relay_mcp process using `data/relay.db` in the remy repo. So Remy’s messages are written to that file.
  - **Cowork (Claude Desktop):** Uses a separate MCP config (outside this repo). If it runs relay_mcp via **stdio** with a different `--db` or CWD, it uses a **different** DB (e.g. default `relay_mcp/relay.db` elsewhere). Messages never cross.
  - **Shared HTTP path:** `.cursor/mcp.json` defines a "relay" server that connects to `http://127.0.0.1:8765/mcp` (one shared process). `make relay-run` and Docker both start a single HTTP server with `--db data/relay.db`. So one process + one DB is already supported; both agents must use that HTTP endpoint instead of stdio.
  - **Fix:** (1) Run a single relay server: `make relay-run` or `make relay-up`. (2) Point **both** Cursor (Remy) and Claude Desktop (cowork) at that server via HTTP (e.g. mcp-proxy to `http://127.0.0.1:8765/mcp`), not stdio. (3) Ensure agent names match: `remy` and `cowork` (lowercase). (4) Optional: remove or override the stdio `relay_mcp` entry in `.mcp.json` for this project so Cursor uses the shared HTTP "relay" server from `.cursor/mcp.json` when working in remy.
- **Reported:** 2026-03-04 (Dale Rogers)
- **Fixed:** —

---

## Bug 4: Forward-to-cowork button shows "✅ Sent to cowork" when message is not delivered to cowork

- **Symptom:** After tapping [Send to cowork], the message is replaced with "✅ Sent to cowork." but cowork never receives the message. User reasonably believes the content was delivered.
- **Evidence:** Same as Bug 3 — Remy writes to its local relay DB and the callback treats a successful local write as success, so it always shows "✅ Sent to cowork." when the write succeeds. Cowork reads from a different DB/process, so delivery never occurs.
- **Impact:** Misleading UX. User loses trust that the button does anything useful; content may be re-sent manually or lost.
- **Root cause:** Same as Bug 3 — two relay backends. The callback in `remy/bot/handlers/callbacks.py` (forward_to_cowork) calls `post_message_to_cowork()` which returns success after writing to the local DB only. There is no check that cowork is actually reading from that DB.
- **Related:** Bug 3 (relay cross-agent messages not delivered). Fixing Bug 3 (single shared relay backend) resolves this bug.
- **Status:** 🔴 Open
- **Priority:** High (same as Bug 3)
- **Location:** `remy/bot/handlers/callbacks.py` (forward_to_cowork), `remy/relay/client.py`
- **Fix:** Implement [US-relay-shared-backend](docs/backlog/US-relay-shared-backend.md) so both agents use one relay process/DB. Optionally (see [US-relay-forward-to-cowork-feedback](docs/backlog/US-relay-forward-to-cowork-feedback.md)): soften copy to "Queued for cowork" when using local-only DB, or add observability so we can confirm delivery.
- **Reported:** 2026-03-04 (Dale Rogers)
- **Fixed:** —
