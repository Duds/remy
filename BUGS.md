# Remy Bug Report

_Last updated: 2026-03-05_

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
- **Root cause:** Remy and cowork were using **different relay_mcp processes and/or different DB files** (stdio per client vs one shared HTTP server).
- **Status:** ✅ Fixed
- **Priority:** High
- **Location:** `relay_mcp/server.py`, relay MCP config (both Remy and cowork sides)
- **Fix:** Use a **single shared relay backend** per [US-relay-shared-backend](docs/backlog/US-relay-shared-backend.md): run one relay server (`make remy-up` or `make relay-run`), point both Cursor (Remy) and Claude Desktop (cowork) at `http://127.0.0.1:8765/mcp`, and use agent names `remy` and `cowork`. Setup: [docs/relay-setup.md](docs/relay-setup.md). Automated shared-DB test: `make relay-verify`.
- **Reported:** 2026-03-04 (Dale Rogers)
- **Fixed:** 2026-03-04

---

## Bug 4: Forward-to-cowork button shows "✅ Sent to cowork" when message is not delivered to cowork

- **Symptom:** After tapping [Send to cowork], the message is replaced with "✅ Sent to cowork." but cowork never receives the message. User reasonably believes the content was delivered.
- **Evidence:** Same as Bug 3 — Remy wrote to its local relay DB and the callback treated a successful local write as success; cowork read from a different DB/process, so delivery never occurred.
- **Impact:** Misleading UX. User loses trust that the button does anything useful; content may be re-sent manually or lost.
- **Root cause:** Same as Bug 3 — two relay backends. Fixing Bug 3 (single shared relay backend) resolves this bug.
- **Status:** ✅ Fixed
- **Priority:** High (same as Bug 3)
- **Location:** `remy/bot/handlers/callbacks.py` (forward_to_cowork), `remy/relay/client.py`
- **Fix:** Once both agents use the shared relay per [docs/relay-setup.md](docs/relay-setup.md), [Send to cowork] writes to the same DB cowork reads from, so "✅ Sent to cowork." reflects actual delivery. See Bug 3 fix.
- **Reported:** 2026-03-04 (Dale Rogers)
- **Fixed:** 2026-03-04

---

## Bug 5: `create_plan` goal_id FK error — plan created without goal link

- **Symptom:** When calling `create_plan` with a `goal_id`, the plan is created successfully but the goal link silently fails with a foreign key error. Plan exists but is not linked to the intended goal.
- **Evidence:** During "Build Fig" plan creation (2026-03-05), plan was created but goal link (goal 61 — sailing adventure) was not applied.
- **Impact:** Plans appear unlinked from goals in `get_goals(include_plans=True)` and `list_plans`. Goal tracking is incomplete.
- **Root cause:** Invalid or out-of-scope goal_id (e.g. non-existent or belonging to another user) was not validated before INSERT; FK violation could be silent or surface as a raw DB error.
- **Status:** ✅ Fixed
- **Priority:** Medium
- **Location:** `remy/memory/goals.py`, `remy/memory/plans.py`, `remy/ai/tools/plans.py`
- **Fix:** (1) Added `GoalStore.exists_for_user(user_id, goal_id)` to check goal exists and belongs to the user. (2) In `exec_create_plan`, validate goal_id before calling create_plan: reject invalid or non-integer goal_id with a clear message; if goal_id set, require goal_store and call `exists_for_user` — otherwise return a helpful error. (3) In `PlanStore.create_plan`, catch `aiosqlite.IntegrityError` on INSERT and re-raise a clear `ValueError` so FK failures (e.g. goal deleted between check and insert) are user-friendly.
- **Reported:** 2026-03-05 (Dale Rogers)
- **Fixed:** 2026-03-05

---

## Bug 6: Commentary replaced by "✓" when Remy adds buttons during conversation

- **Symptom:** When Remy adds inline buttons during a reply (e.g. via `suggest_actions` — [Add to calendar], [Send to cowork], etc.), her streamed commentary is often replaced by a single "✓" and the buttons. The lost text is often the useful part of the message (e.g. context, explanation, or summary).
- **Impact:** User sees only "✓" and action buttons instead of Remy's full reply. Helpful commentary is lost; the tick is uninformative.
- **Root cause:** In `remy/bot/handlers/chat.py`, on every `ToolTurnComplete` event (lines 388–405) the code does `current_display = []`, clearing the accumulated streamed text. When Remy streams commentary and then calls `suggest_actions` in the same turn, the sequence is: (1) text chunks fill `current_display`, (2) tool runs and `ToolTurnComplete` fires, (3) `current_display` is cleared, (4) stream ends with no further text, so `final_text_accum` is empty. The finalisation logic then either calls `_flush_display(final=True, reply_markup=…)` with empty content (so `_flush_display` uses `truncated = "✓"` at line 245) or hits the `elif tool_turns` branch (lines 522–526) and explicitly `sent.edit_text("✓", reply_markup=reply_markup)`. In both cases the pre–tool-turn commentary has already been discarded.
- **Location:** `remy/bot/handlers/chat.py` — clearing of `current_display` at line 404 on `ToolTurnComplete`; finalisation branch at 522–526 that edits to "✓" when there are tool turns but no remaining text.
- **Related:** Bug 1 (archived) — "✓" when only `react_to_message`; that fix avoided the tick for reaction-only. This bug is when there *is* preceding commentary but it is wiped by the tool-turn clear.
- **Status:** ✅ Fixed
- **Fix:** Stop clearing `current_display` (and `last_edit_len`) on `ToolTurnComplete`. Commentary streamed before the tool call is preserved, so `final_text_accum` is non-empty at finalisation and `_flush_display(final=True, reply_markup=…)` shows the full text with buttons; the "✓" branch is no longer taken when there was preceding commentary.
- **Reported:** 2026-03-04 (Dale Rogers)
- **Fixed:** 2026-03-04
