# Remy Bug Report — Archived (2026-03-04)

Archived bugs 1–41 (all fixed/closed). See `BUGS.md` for active bugs.

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
  - Added 5 regression tests to `tests/test_memory_injector_extra.py` covering: long descriptive text, relative paths, oversized components, valid paths working, mixed valid/invalid entries
- **Reported:** 2026-02-28
- **Actually fixed:** 2026-03-02

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
- **Fix:** `StreamingReply._flush()` now includes a `if __debug__: assert len(display) <= 4096` guard. If the assertion fires, the overflow is logged at DEBUG and `display` is trimmed to `_TELEGRAM_MAX_LEN` before the edit — so the hard limit can never be breached.
- **Location:** `remy/bot/streaming.py` — `_flush()`, lines 108–114
- **Priority:** Low
- **Status:** ✅ Fixed

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
- **Cause:** `chrome_114` is not a valid impersonation target in the installed version of `primp`. The `random` fallback works correctly — the message is pure noise.
- **Fix:**
  - `requirements.txt`: bumped `ddgs>=9.0` → `ddgs>=9.2` (the upstream fix for the stale impersonation string).
  - `remy/web/search.py`: added `logging.getLogger("primp.impersonate").setLevel(logging.ERROR)` at module level as a belt-and-suspenders suppressor — the warning is silenced regardless of which `ddgs`/`primp` version is installed.
- **Locations:** `requirements.txt:15`, `remy/web/search.py`
- **Priority:** Low
- **Status:** ✅ Fixed

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
- **Root cause:** Telegram `RemoteProtocolError` disconnects (see Bug 6) cause the bot to retry message delivery. During retry, the message origin check is not filtering outbound messages sent by the bot itself — the bot's own `user_id` was not being checked against `message.from_user.id` before dispatching to the message handler.
- **Fix:** Added `update.effective_user.id == context.bot.id` guard (with `except AttributeError` + warning log) to all four inbound message handlers: `handle_message`, `handle_voice`, `handle_photo`, `handle_document` in both `remy/bot/handlers.py` and `remy/bot/handlers/chat.py`.
- **Locations:** `remy/bot/handlers.py:3008`, `remy/bot/handlers/chat.py:handle_message`
- **Priority:** Critical
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 19: Morning briefing uses stale date when scheduler fires late

- **Symptom:** Morning briefing greets the user with yesterday's date when the scheduled job misfires and fires late.
- **Root cause:** The date/day string is computed eagerly when the job is *registered* or *built*, not lazily at the moment the message is *sent*. When APScheduler catches up a missed job, the pre-baked date is stale.
- **Related:** Bug 7 (missed jobs / coalesce).
- **Fix:** `_format_date_header()` in `BriefingGenerator` now calls `datetime.now(tz)` at execution time rather than returning a pre-baked string.
- **Location:** `remy/scheduler/briefings/base.py` — `_format_date_header()`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 20: Reaction handler silently drops reply — orphaned `tool_use_id`

- **Symptom:** Remy executes a tool (e.g. `manage_memory`) and stores the result successfully, but no reply is sent to the user. The conversation appears to go silent.
- **Root cause:** The reaction handler calls Claude with a message that contains a `tool_result` block whose `tool_use_id` has no corresponding `tool_use` block in the preceding message. Claude returns `400 invalid_request_error: unexpected tool_use_id found in tool_result blocks`.
- **Fix:** Added module-level `_sanitize_messages_for_claude()` which strips `tool_use` and `tool_result` blocks entirely from history before passing to `claude_client.complete()`.
- **Location:** `remy/bot/handlers/reactions.py` — `_sanitize_messages_for_claude()`
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 21: Incomplete chunked read from Claude API causes dropped response

- **Symptom:** Response takes an unusually long time, then either arrives late or is missing entirely. Logged as `stream_with_tools error`.
- **Root cause:** Claude API closes the streaming connection before the full response body is sent — `peer closed connection without sending complete message body (incomplete chunked read)`. No retry logic existed for mid-stream connection drops.
- **Fix:** Added `_is_transient_stream_exc()` helper and wrapped the `async for event in claude_client.stream_with_tools(...)` loop in a `for _attempt in range(2):` retry.
- **Location:** `remy/bot/handlers/chat.py` — `_stream_with_tools_path()`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 22: Reaction handler always attempts a reaction — no no-op path

- **Symptom:** Every user message triggers a Claude call in the reaction handler, even for messages that warrant no reaction.
- **Fix:** Added `_NO_OP_EMOJI = {"✅", "👍", "👀", "🙏"}` set. Early-exit check fires before `conv_store.get_recent_turns()`.
- **Location:** `remy/bot/handlers/reactions.py`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 23: Tool dispatch exception corrupts conversation history

- **Symptom:** When a tool raises an exception mid-stream, the user sees a generic error and the turn is silently dropped.
- **Fix:** Wrapped `tool_registry.dispatch()` in a per-tool `try/except`. On failure, a synthetic error `tool_result` block is injected, the loop continues, and `ToolTurnComplete` is still yielded.
- **Location:** `remy/ai/claude_client.py` — tool execution loop
- **Priority:** High
- **Status:** ✅ Fixed
- **Fixed:** 2026-02-27

---

## Bug 24: Final reply duplicated or reordered after multi-tool interactions

- **Symptom:** After multi-step agentic exchanges, Claude's final prose response appeared twice in Telegram, or partial text appeared before tool results had fully flushed.
- **Fix:** Gated `StreamingReply.feed()` calls behind the `in_tool_turn` flag. Pre-final `TextChunk` events received while `in_tool_turn` is `True` are logged at DEBUG but not streamed.
- **Location:** `remy/bot/handlers.py` and `remy/bot/handlers/chat.py`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fixed:** 2026-02-27

---

## Bug 25: `read_file` tool truncates large files

- **Symptom:** File contents cut off mid-way with `[… truncated — NNNNN chars total]` appended
- **Fix:** Increased char cap from 8000 → 50000 in `remy/ai/tools/files.py` line 59.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-02

---

## Bug 26: Scheduler jobs still misfiring despite coalesce=True fix (Bug 7 regression)

- **Symptom:** `Run time of job "ProactiveScheduler._afternoon_focus ... was missed by 1:04:23"` and `_end_of_day_consolidation ... was missed by 1:39:48` in logs
- **Fix:** Increased `misfire_grace_time` from 3600 → 7200 for `afternoon_focus` and `end_of_day_consolidation` jobs.
- **Location:** `remy/scheduler/proactive.py`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 27: `set_message_reaction` fails with `Reaction_invalid`

- **Symptom:** `set_message_reaction failed: Reaction_invalid` logged as warnings
- **Fix:** Replaced `ALLOWED_EMOJI` set — removed `✅` and `😂` (not in Telegram's official reaction list), added `🤩` and `🤣`.
- **Location:** `remy/ai/tools/session.py` — `set_message_reaction` executor
- **Priority:** Low
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 28: Stream crash — incomplete chunked read during tool-use path (Bug 21 regression)

- **Symptom:** `stream_with_tools error for user 8138498165: peer closed connection without sending complete message body (incomplete chunked read)`
- **Fix:** Already addressed by Bug 21's retry mechanism.
- **Location:** `remy/bot/handlers/chat.py`
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 29: Reaction handler tool_use_id errors still firing despite sanitizer (Bug 20 regression)

- **Symptom:** `Reaction handler: Claude call failed: messages.0.content.0: unexpected tool_use_id found in tool_result blocks` — logged twice despite `_sanitize_messages_for_claude()` being present
- **Fix:** Rewrote sanitizer with two passes: (1) drop entire messages containing any `tool_use`/`tool_result` block; (2) merge consecutive same-role messages.
- **Location:** `remy/bot/handlers/reactions.py` — `_sanitize_messages_for_claude()`
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 30: Anthropic `overloaded_error` drops message with no retry and no user feedback

- **Symptom:** `stream_with_tools error for user 8138498165: {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}` — user's message silently dropped.
- **Fix:** Added `overloaded_error` detection in the chat.py error handler. Now shows friendly message "I'm briefly overloaded on my end — please try again in a moment. 🙏"
- **Location:** `remy/bot/handlers/chat.py` — exception handler in `stream_with_tools`
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 31: Calendar briefing shows raw past start date for ongoing multi-day all-day events

- **Symptom:** Morning briefing shows `• 2026-02-27 — Alex Care` on a March 3rd briefing — the date is 4 days old.
- **Fix:** Added `today` parameter to `_parse_event_start()`. When an all-day event's start date is before today, returns `"(ongoing)"` instead of the raw past date.
- **Location:** `remy/google/calendar.py` — `_parse_event_start()` and `format_event()`
- **Priority:** Low
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 32: Google Calendar auth fails — `from __future__` import in wrong position

- **Symptom:** `Google Workspace init failed: from __future__ imports must occur at the beginning of the file (calendar.py, line 9)`
- **Fix:** Moved `from __future__ import annotations` to be the first statement after the module docstring.
- **Location:** `remy/google/calendar.py` — line 9
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 33: Afternoon and evening proactive pings silently skipped after bot restart

- **Symptom:** Afternoon focus (2pm) and evening check-in (7pm) are never delivered. Morning briefing (7am) arrives correctly.
- **Fix:** Added `run_startup_reconciliation()` in `ProactiveScheduler`. On startup, checks a persistent delivery log for whether each daily job has fired today. If current time is past the scheduled hour and no record exists, fires the missed job.
- **Location:** `remy/scheduler/proactive.py` — `run_startup_reconciliation()`, `_record_delivery()`, `_load_delivery_log()`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Feature 34: "Are you there God, it's me, Dale" — hardcoded self-diagnostics trigger

- **Type:** Feature / Easter egg
- **Fix:** Updated `DIAGNOSTICS_TRIGGER` regex to allow comma after "god". `_run_diagnostics()` now uses `tool_registry.dispatch("check_status", ...)` + `tool_registry.dispatch("get_logs", ...)` when tool_registry is available.
- **Location:** `remy/bot/handlers/chat.py`, `remy/bot/handlers.py`, `remy/diagnostics/__init__.py`
- **Priority:** Low
- **Status:** ✅ Fixed
- **Reported:** 2026-03-03

---

## Bug 35: `react_to_message` tool sends a ✅ text message alongside the emoji reaction

- **Symptom:** When Remy calls `react_to_message` as the sole response (e.g. reacting to "Thanks" with 👍), a ✅ tick character is also sent as a separate Telegram text message.
- **Fix:** When the only tool used is `react_to_message` and there is no text response, delete the bot's status message instead of editing it to "✓".
- **Location:** `remy/bot/handlers/chat.py` — `_stream_with_tools_path()`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-04

---

## Bug 36: Orphaned `tool_use_id` in main chat path causes 400 error

- **Symptom:** `Sorry, something went wrong: Error code: 400 - ... unexpected tool_use_id found in tool_result blocks ...`
- **Fix:** Moved `_sanitize_messages_for_claude()` to `base.py` (shared). Applied before `stream_with_tools()` in `chat.py` and `pipeline.py`.
- **Location:** `remy/bot/handlers/base.py`, `remy/bot/handlers/chat.py`, `remy/bot/pipeline.py`
- **Priority:** High
- **Status:** ✅ Fixed
- **Reported:** 2026-03-04

---

## Bug 37: Compaction passes raw string to `claude_client.complete()` — expects `list[dict]`

- **Symptom:** `remy.memory.compaction: Claude summarisation failed, using fallback: Error code: 400 - ... messages: Input should be a valid list`
- **Fix:** Wrapped the prompt in a messages list: `self.claude_client.complete([{"role": "user", "content": prompt}], ...)`.
- **Location:** `remy/memory/compaction.py` — `_generate_summary()`
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-04

---

## Bug 38: Max tool iterations (8) truncates multi-step responses

- **Symptom:** `stream_with_tools hit max iterations (8) for user 8138498165` logged as WARNING.
- **Fix:** (1) Increased limit from 8 → 12. (2) When the limit is hit, yield a final `TextChunk` with "_I reached my step limit for this turn. Ask me to continue or break this into smaller tasks._"
- **Location:** `remy/ai/claude_client.py` — `_MAX_TOOL_ITERATIONS`
- **Priority:** Low
- **Status:** ✅ Fixed
- **Reported:** 2026-03-04

---

## Bug 39: `react_to_message` SOUL config includes invalid emoji (✅)

- **Symptom:** `set_message_reaction failed: Reaction_invalid` when `react_to_message` is called with `✅`.
- **Fix:** Updated `react_to_message` schema in `schemas.py` to remove `✅` and `😂` (invalid per Telegram API), align with `session.py` `ALLOWED_EMOJI`: `{👍 ❤️ 🔥 🤔 👀 🎉 🤩 🤣}`.
- **Location:** `remy/ai/tools/schemas.py` — `react_to_message` tool description and input_schema
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Reported:** 2026-03-04

---

## Bug 40: `KnowledgeStore` has no attribute `add`

- **Symptom:** `AttributeError: 'KnowledgeStore' object has no attribute 'add'` when calling the `save_bookmark` tool.
- **Fix:** `bookmarks.py` now uses `KnowledgeStore.add_item()` and `FactStore.add(user_id, content, "bookmark")`; `list_bookmarks` uses `get_by_type` + filter by `metadata.category == "bookmark"`.
- **Location:** `remy/memory/knowledge.py` — `KnowledgeStore` class; `remy/ai/tools/bookmarks.py`
- **Priority:** Medium
- **Status:** ✅ Closed — fixed in commit 5a632df (US-fix-save-bookmark-knowledge-store)
- **Reported:** 2026-03-04

---

## Bug 41: Git tools have no repo path context

- **Symptom:** `git_log`, `git_diff`, `git_status`, `git_show_commit` return no results or fail silently — they don't know which repo to operate on.
- **Fix:** Set `WORKSPACE_ROOT=/home/remy/Projects/ai-agents/remy` in `docker-compose.yml` for the remy service so git tools resolve against the remy repo.
- **Location:** `remy/ai/tools/git.py`, `remy/config.py`, `docker-compose.yml`
- **Priority:** Low
- **Status:** ✅ Fixed
- **Reported:** 2026-03-04
