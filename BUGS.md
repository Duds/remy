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
