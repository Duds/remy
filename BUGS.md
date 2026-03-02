# Remy Bug Report

_Last updated: see file history_

---

## Bug 1: ConversationStore missing `sessionsdir`

- **Symptom:** `'ConversationStore' object has no attribute 'sessionsdir'`
- **Impact:** Conversation history not saving/loading between sessions. Context is lost on restart.
- **Likely cause:** Attribute renamed or removed from `ConversationStore` class without updating all references.
- **Priority:** High
- **Status:** ✅ Fixed
- **Fix:** Changed `self._conv_store._sessions_dir` to `self._conv_store.sessions_dir` in `remy/diagnostics/runner.py`

---

## Bug 2: Diagnostics import failure — `_since_dt`

- **Symptom:** `cannot import name '_since_dt' from 'remy.diagnostics'` (`/app/remy/diagnostics/__init__.py`)
- **Impact:** `/logs` tool completely broken — no ability to self-diagnose from inside a conversation.
- **Likely cause:** `_since_dt` was defined somewhere and removed or moved without updating the import.
- **Priority:** High
- **Status:** ✅ Fixed
- **Fix:** Added `_since_dt` to imports and `__all__` in `remy/diagnostics/__init__.py`

---

## Bug 3: `set_proactive_chat` tool not working via natural language

- **Symptom:** Tool call returns failure — requires Telegram chat context not available in tool context.
- **Impact:** Setting proactive chat via conversation doesn't work; `/setmychat` command required instead.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fix:** Added `chat_id` parameter threading through `dispatch()` → `stream_with_tools()` → `_stream_with_tools_path()`. The `set_proactive_chat` tool now receives the chat context and can save the primary chat ID directly.

---

## Bug 4: `/privacy-audit` command uses invalid `stream_with_tools` parameters

- **Symptom:** `/privacy-audit` command likely fails or behaves unexpectedly
- **Impact:** Privacy audit feature broken
- **Location:** `remy/bot/handlers.py` lines 2037–2043
- **Likely cause:** The call uses parameters (`tools`, `tool_executor`, `max_tokens`) that don't exist in the `stream_with_tools()` signature. The correct parameters are `tool_registry` and `user_id`.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fix:** Updated `stream_with_tools()` call to use correct parameters: `tool_registry`, `user_id`, and `system` instead of the non-existent `tools`, `tool_executor`, and `max_tokens`.

---

## Bug 5: Markdown rendering broken in summary/recap messages

- **Symptom:** Markdown formatting (bold, italic, etc.) appears as raw symbols rather than rendered text in Telegram — e.g. `*text*` instead of **text**
- **Impact:** Recap and summary-style responses are visually noisy and hard to read
- **Root cause:** Two delivery paths used the wrong format mode:
  1. `chat.py` `_stream_with_tools_path._flush_display()` sent raw Claude text with `parse_mode="Markdown"` (old mode, no escaping)
  2. `proactive.py` `_send()` also used `parse_mode="Markdown"` with unescaped Claude output
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fix:**
  - `chat.py`: Added `format_telegram_message()` import and changed `_flush_display()` to use `format_telegram_message(truncated)` + `parse_mode="MarkdownV2"` with plain-text fallback
  - `proactive.py`: Added `format_telegram_message()` import; `_send()` now formats with MarkdownV2 and falls back to plain text on failure
- **Reported:** 2026-03-01

---

## Bug 6: Telegram transient disconnections causing slow responses

- **Symptom:** `httpx.RemoteProtocolError: Server disconnected without sending a response` logged as warnings during active conversations
- **Impact:** Responses are delayed while the bot retries the Telegram connection. From the user's perspective, Remy appears slow or unresponsive.
- **Root cause:** `ApplicationBuilder` defaults to HTTP/2 (via `httpx`). When the Telegram server drops the multiplexed TCP connection, the entire HTTP/2 stream is lost and reconnecting requires ALPN negotiation. HTTP/1.1 reconnects faster.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fix:** Added `.http_version("1.1")` to the `ApplicationBuilder` chain in `remy/bot/telegram_bot.py`. HTTP/1.1 connections drop cleanly and reconnect without TLS renegotiation overhead.
- **Reported:** 2026-02-28

---

## Bug 7: Scheduled job missed on startup — fires with large delay

- **Symptom:** `Run time of job "ProactiveScheduler._register_automation_job" was missed by 6:56:53` logged on startup
- **Impact:** Without `coalesce=True`, if the bot was down across multiple fire times, APScheduler would queue all missed runs and fire them in rapid succession on restart, causing message floods.
- **Root cause:** All `add_job()` calls had `misfire_grace_time=3600` but were missing `coalesce=True`. The default `coalesce=False` allows multiple rapid catch-up fires.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fix:** Added `coalesce=True` to all 7 `add_job()` calls in `remy/scheduler/proactive.py` (morning_briefing, afternoon_focus, evening_checkin, monthly_retrospective, reindex_files, end_of_day_consolidation, automation jobs). If a job misfired multiple times while the bot was down, it now fires at most once on catch-up.
- **Reported:** 2026-02-28

---

## Bug 8: Memory injection fails on long fact content used as path

- **Symptom:** `[Errno 36] File name too long` when injecting memory context
- **Impact:** Memory injection fails entirely, Remy runs without memory context injected into prompts
- **Root cause:** Two issues in `_get_project_context()` in `remy/memory/injector.py`:
  1. `readme.exists()` was called outside any try/except — `OSError [Errno 36]` propagated uncaught through `asyncio.gather`, crashing the entire `build_context()` call
  2. The DB query fetches all facts with `category: "project"`, but descriptive project facts (not paths) get fed directly into `Path(path_str)`. A long description with no `/` separators becomes a single oversized path component, triggering the OS error on `.exists()` / `stat()`
- **Note:** Previously marked ✅ Fixed in error — the fix was never committed (absent from commit `8ec6af3` which repaired bugs 5/6/7/9/10/11)
- **Priority:** High
- **Status:** ✅ Fixed
- **Fix:**
  - Added pre-loop validation: skip `path_str` that does not start with `/` (not an absolute path)
  - Added pre-loop validation: skip `path_str` where any path component exceeds 255 bytes
  - Moved `readme.exists()` and read inside a per-entry `try/except` so one bad path cannot abort the whole function
  - Added 5 regression tests to `tests/test_memory_injector_extra.py` covering: long descriptive text, relative paths, oversized components, valid paths still working, mixed valid/invalid entries
- **Reported:** 2026-02-28
- **Actually fixed:** 2026-03-02

---

## Bug 10: Responses end mid-sentence with trailing "…"

- **Symptom:** Remy's response appears cut off mid-sentence, ending with "…" (or " …")
- **Impact:** Looks like Remy didn't finish her thought; confusing for the user
- **Root cause 1 (primary):** In `StreamingReply._edit_or_skip()` and `_flush_display()` in the tool path, all exceptions are silently caught. When a transient Telegram disconnection (Bug 6) hits at the moment of the *final* edit — the one that strips the in-progress " …" streaming indicator — the exception is swallowed and the message is left displaying `"partial text …"`.
- **Root cause 2 (secondary):** When Claude ends with a tool call and produces no text afterward, `_flush_display(final=True)` returns early because `current_display` is empty — leaving `"_⚙️ Using tool_name…_"` as the final message.
- **Locations:**
  - `remy/bot/streaming.py` — `finalize()` / `_edit_or_skip()`
  - `remy/bot/handlers/chat.py` — `_stream_with_tools_path()` → `_flush_display()`
- **Priority:** High
- **Status:** ✅ Fixed
- **Fix:**
  - `streaming.py`: `finalize()` retries `_flush()` once (0.5s delay) if `_last_sent` still ends with " …" after the first attempt
  - `chat.py`: retry `_flush_display(final=True)` once after 0.3s when there is text to show; if `current_display` is empty after tool turns, replace tool status message with "✓"
- **Reported:** 2026-03-01

---

## Bug 9: SQLite database corruption (knowledge table)

- **Symptom:** `database disk image is malformed (11)` errors; `PRAGMA integrity_check` shows btreeInitPage errors
- **Impact:** Knowledge table data (facts, goals) appeared corrupted — content columns showing NULL. Memory system non-functional.
- **Root cause:** Stale WAL pages left over from a previous crash. WAL mode without a startup checkpoint allows corrupt/incomplete journal frames to persist across restarts.
- **Priority:** Critical
- **Status:** ✅ Fixed (recovered + preventive measure added)
- **Fix:**
  - Database self-recovered (WAL auto-recovery on reconnect). `PRAGMA integrity_check` now returns `ok`; 37 facts + 6 goals are accessible.
  - Preventive fix added: `DatabaseManager.init()` in `remy/memory/database.py` now runs `PRAGMA wal_checkpoint(RESTART)` after DDL on every startup. This flushes any stale WAL frames to the main database file before serving requests. Non-fatal — wrapped in try/except so a checkpoint failure does not block startup.
- **Reported:** 2026-03-01

---

## Bug 11: Conversation context lost mid-day (UTC session key rollover)

- **Symptom:** Remy "forgets" everything from the morning's conversation around 11am AEDT. Each new message after that time is handled as if starting a fresh session with no prior context.
- **Impact:** High — conversational continuity is completely broken for half of each working day. Remy can't reference anything discussed before the UTC midnight boundary.
- **Root cause:** `SessionManager.get_session_key()` in `remy/bot/session.py` used `datetime.now(timezone.utc)` to generate the date component of the session filename (e.g. `user_8138498165_20260301.jsonl`). For a user in AEDT (UTC+11), UTC midnight falls at 11am local time. After 11am, the session key rolls to the next UTC date, but no JSONL file exists for that date yet — so `get_recent_turns()` returns an empty list and Remy starts with a blank context.
- **Priority:** High
- **Status:** ✅ Fixed
- **Fix:** `get_session_key()` now reads `settings.scheduler_timezone` and uses `zoneinfo.ZoneInfo` to get the user's local date. Session files now roll over at local midnight (AEST/AEDT) rather than UTC midnight. Existing UTC-dated session files are unaffected — they remain on disk and are accessible via `get_all_sessions()`.
- **Reported:** 2026-03-01

---

## Bug 12: Tool Status Text Leaking into Telegram Messages

- **Symptom:** Messages like "using list_directory" or "using get_logs" appear in Remy's Telegram replies mid-response, as if they are part of the answer.
- **Root cause:** In `bot/handlers.py`, the tool-aware processing loop passes `TextChunk` events directly to `StreamingReply.feed()` regardless of whether they arrive between tool calls (i.e. before `ToolTurnComplete` has fired). Claude emits brief status-style text fragments between tool invocations — these should be logged only, not streamed.
- **Fix:** Gate `StreamingReply.feed()` on a flag (`in_tool_turn: bool`). Set it `True` on `ToolStatusChunk`, `False` on `ToolTurnComplete`. While `in_tool_turn` is `True`, log `TextChunk.text` at DEBUG level but do NOT feed it to the streamer.
- **Location:** `bot/handlers.py` — tool-aware path (Path A), inside the `async for event in claude_client.stream_with_tools(...)` loop.
- **Priority:** Medium
- **Status:** ✅ Fixed

---

## Bug 13: One-time automation double-fire on restart

- **Symptom:** If the bot restarts within the 5-minute APScheduler `misfire_grace_time` window after a one-time automation fired, `load_user_automations()` re-registers the job with a past `DateTrigger` and APScheduler fires it again immediately.
- **Impact:** One-time reminders fire twice after bot restart.
- **Root cause:** `_run_automation()` deletes the DB row _after_ firing. If the bot restarts between fire and delete, the row still exists and the job is re-registered.
- **Fix:** `_run_automation()` now deletes the one-time automation row **before** sending the reminder (`scheduler/proactive.py:331–340`). Comment: `# Perform DB cleanup BEFORE sending to avoid double-firing on crashes`. On restart, `load_user_automations()` finds no row and does not re-register the job.
- **Location:** `scheduler/proactive.py:331`
- **Priority:** Low
- **Status:** ✅ Fixed

---

## Bug 14: Streaming reply overflow split safety

- **Symptom:** Very long messages (>4000 chars, no space before limit) fall back to splitting at exactly 4000 chars. The `" …"` suffix can push the display string to 4003 chars, still within Telegram's 4096 limit but worth monitoring.
- **Fix:** Add a `len(display) <= 4096` assertion in debug mode.
- **Location:** `bot/streaming.py:84`
- **Priority:** Low
- **Status:** Open

---

## Bug 15: Telegram catch-all error handler missing

- **Symptom:** Logs show `telegram.ext.Application: No error handlers are registered, logging exception.` — unhandled exceptions fall through with no structured handling.
- **Impact:** Unhandled Telegram exceptions produce noisy log spam with no Telegram notification for Dale.
- **Root cause:** No error handler registered on the `Application` instance.
- **Fix:** Register a catch-all error handler on the `Application` instance (`application.add_error_handler(error_handler)`). Handler logs at ERROR level with context (user ID, update type); optionally notifies Dale via Telegram for unexpected/critical errors.
- **Location:** `bot/handlers.py` or `main.py`
- **Priority:** Low
- **Status:** ✅ Fixed

---

## Bug 16: primp impersonation header warning

- **Symptom:** `[WARNING] primp.impersonate: Impersonate 'chrome_114' does not exist, using 'random'` — logged repeatedly during web requests.
- **Cause:** `chrome_114` is not a valid impersonation target in the current version of `primp`.
- **Fix:** Update the impersonation string to a valid value (e.g. `chrome_120`) or remove the explicit impersonation and rely on the `random` fallback intentionally.
- **Priority:** Low
- **Status:** Open

---

## Bug 17: Final message edit strips MarkdownV2 rendering

- **Symptom:** During streaming, markdown renders correctly (bold, italic etc.) in Telegram. When the final message is settled, the text reverts to raw markdown symbols (e.g. `*bold*` instead of **bold**).
- **Root cause:** `_flush_display(final=True)` is called twice (lines 319 and 324 in `chat.py`). The first call succeeds with `parse_mode="MarkdownV2"`. The second call (0.3s later) sends the identical formatted text — Telegram raises `BadRequest: Message is not modified`. The old `except Exception:` block caught this and then called `sent.edit_text(truncated)` with **no `parse_mode`**, which succeeded and overwrote the rendered message with raw CommonMark text.
- **Location:** `remy/bot/handlers/chat.py` — `_flush_display()` inner function
- **Fix:** Imported `BadRequest` from `telegram.error`. Changed `except Exception:` to `except BadRequest as e:`. If the error is "message is not modified", return immediately (the message is already correctly formatted). Only fall back to plain text for actual MarkdownV2 parse failures.
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 18: Bot responses re-ingested as user input — infinite loop

- **Symptom:** Remy's own responses are fed back into the message handler as new user messages. Each response triggers another response, which is again re-ingested, creating an exponentially deepening loop. User sees Remy apparently "repeating the question" and then asking why the question is being repeated, recursively.
- **Impact:** Bot becomes completely unusable until restarted. Loop continues indefinitely.
- **Root cause:** Telegram `RemoteProtocolError` disconnects (see Bug 6) cause the bot to retry message delivery. During retry, the message origin check is not filtering outbound messages sent by the bot itself — likely because the bot's own `user_id` is not being checked against `message.from_user.id` before dispatching to the message handler.
- **Evidence:**
  - Two `RemoteProtocolError` warnings logged this session
  - Input validator flagged one of Remy's own outbound messages as a shell injection attempt — confirms outbound messages are passing through the inbound validation pipeline
- **Likely location:** `remy/bot/telegram_bot.py` or `remy/bot/handlers.py` — message dispatch / update handler
- **Fix:** Before dispatching any incoming `Message` update to the handler, check `message.from_user.id == context.bot.id` and discard if true. Bot messages should never be treated as user input.
- **Priority:** Critical
- **Status:** 🔴 Open
- **Reported:** 2026-03-02

---

## Bug 19: Morning briefing uses stale date when scheduler fires late

- **Symptom:** Morning briefing greets the user with yesterday's date when the scheduled job misfires and fires late.
- **Evidence:** `apscheduler` warning logged: `Run time of job "ProactiveScheduler._morning_briefing" was missed by [N]` — when the catch-up fires, the date string had already been computed at schedule time (the previous day).
- **Root cause:** The date/day string passed into the briefing message is computed eagerly when the job is *registered* or *built*, not lazily at the moment the message is *sent*. When APScheduler catches up a missed job, the pre-baked date is stale.
- **Related:** Bug 7 (missed jobs / coalesce). Bug 7's fix prevents multiple catch-up fires, but doesn't fix the stale date on the single catch-up fire that does run.
- **Fix:** Compute the current date inside `_morning_briefing()` (and any other proactive message that includes a date) at the moment of execution — not at registration time. Use `datetime.now(tz)` inside the function body, not outside it.
- **Priority:** Medium
- **Status:** 🔴 Open
- **Reported:** 2026-03-02

---

## Bug 12: Reaction handler silently drops reply — orphaned `tool_use_id`

- **Symptom:** Remy executes a tool (e.g. `manage_memory`) and stores the result successfully, but no reply is sent to the user. The conversation appears to go silent.
- **Impact:** User receives no confirmation or response after tool use. High confusion — task appears to have failed when it succeeded.
- **Root cause:** The reaction handler calls Claude with a message that contains a `tool_result` block whose `tool_use_id` has no corresponding `tool_use` block in the preceding message. Claude returns `400 invalid_request_error: unexpected tool_use_id found in tool_result blocks`. The exception is caught but the reply is never delivered.
- **Error:** `messages.0.content.0: unexpected tool_use_id found in tool_result blocks: toolu_01JWHGfpNBhZDx4w8. Each tool_result block must have a corresponding tool_use block in the previous message.`
- **Location:** `remy/bot/handlers/reactions.py` — reaction handler Claude call
- **Priority:** High
- **Status:** Open
- **Reported:** 2026-03-02

---

## Bug 13: Incomplete chunked read from Claude API causes dropped response

- **Symptom:** Response takes an unusually long time, then either arrives late or is missing entirely. Logged as `stream_with_tools error`.
- **Impact:** User experiences slow or silent Remy. Compounds with Telegram disconnections (see Bug 6) to create multi-second dead periods.
- **Root cause:** Claude API closes the streaming connection before the full response body is sent — `peer closed connection without sending complete message body (incomplete chunked read)`. No retry logic exists for mid-stream connection drops.
- **Error:** `remy.bot.handlers.chat: stream_with_tools error for user 8138498165: peer closed connection without sending complete message body (incomplete chunked read)`
- **Location:** `remy/bot/handlers/chat.py` — `stream_with_tools` error handler
- **Priority:** Medium
- **Status:** Open
- **Reported:** 2026-03-02

---

## Bug 12 — Amendment (2026-03-02)

**Additional requirement for fix:** The reaction handler must also handle the case where no reaction is needed. Currently the handler always attempts to call Claude to decide on a reaction, which means every message triggers a Claude call and risks the orphaned `tool_use_id` error. The fix should include a no-op / early-exit path so that when Claude determines no reaction is warranted, the handler exits cleanly without making a tool call at all. This avoids unnecessary API calls and eliminates the surface area for the malformed message bug.

---

## Bug 14: Reaction handler always attempts a reaction — no no-op path

- **Symptom:** Every user message triggers a Claude call in the reaction handler, even for messages that warrant no reaction (e.g. simple thumbs-up acknowledgements from the user, confirmations, or reactions to reactions).
- **Impact:** Unnecessary API calls on every message; compounds Bug 12 by increasing the frequency of the malformed `tool_use_id` error.
- **Root cause:** The reaction handler has no early-exit or no-op path. Claude is always called and always expected to emit a `react_to_message` tool call. There is no supported return path for "no reaction needed."
- **Location:** `remy/bot/handlers/reactions.py`
- **Priority:** Medium
- **Status:** Open
- **Reported:** 2026-03-02
