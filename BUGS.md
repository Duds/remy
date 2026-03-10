# Remy Bug Report

_Last updated: 2026-03-06_

Archived bugs 1–41 (all fixed) → [docs/archive/BUGS-archived-2026-03-04.md](docs/archive/BUGS-archived-2026-03-04.md)

---

## Bug 9: Calendar events shown without dates — model misassigns days (e.g. #1537 Sunday vs Thursday)

- **Symptom:** When the user asks Remy to "check the calendar" in chat, Remy reports events with wrong day assignments (e.g. #1035 said to be Thursday when it's Monday; #1537 said to be on Thursday when it's actually Sunday). User sees only one event (#1035 Thursday 9pm) while Remy lists many. Eventually Remy acknowledges that "the calendar feed is returning events without proper dates" — "most events are missing their day, only the all-day events (Alex Care, School Photos, Payday, Canberra Day) have dates". Same recurring meeting (#1537) can appear to be on two days or duplicated because instances are indistinguishable without dates.
- **User flow (summary):** User asked to check calendar → Remy listed SMART meetings by weekday but with errors → User corrected (#1035 only on Thursday 9pm; #1537 is Sunday) → Remy "corrected" then still conflated days → User said calendar is correct and the bug is in parsing → Remy confirmed: events listed but parser not associating them with specific days; only all-day events have dates.
- **Root cause:** In `remy/google/calendar.py`, `_parse_event_start()` formats timed events (when `start` has `dateTime`) as **time only**: `dt.strftime("%H:%M")`. The **date** from the ISO string is never included. `format_event()` uses that and produces lines like `• 21:00 — #1035` with no day. All-day events use `start.get("date")` and are formatted with "dd %b", so they do show a date. The **calendar_events** tool (used when the user asks in chat) returns only this formatted list; the model therefore receives a list of events with times but no dates for timed events, and cannot know which day each belongs to — leading to wrong day assignments and confusion (e.g. #1537 on Sunday vs Thursday).
- **Evidence from code:**
  - `_parse_event_start()` (lines 31–37): for `dateTime` it returns only `dt.strftime("%H:%M")`.
  - `format_event()` (lines 134–141): builds `f"• {start} — {title}{loc_suffix}"` where `start` is the result of `_parse_event_start`, so no date for timed events.
  - `/calendar` Telegram handler (handlers/calendar.py) does derive `date_part = dt_str[:10]` for section headers, but the **tool** used in chat (`exec_calendar_events` → `format_event`) does not include date in each line, so the model never gets per-event dates.
- **Logs and telemetry:** No calendar-specific logging or telemetry. The calendar client has a module logger but no log calls in the list/parse/format path. General health telemetry records tool execution timing but not calendar payloads. Recommendation for debugging: add a DEBUG log of raw `event.get("start")` (or first N events) when returning calendar tool results, so future parsing issues can be traced without guessing API shape.
- **Impact:** High. User loses trust in calendar answers; wrong day assignments (e.g. missing Sunday #1537, or listing it on Thursday) cause real scheduling confusion. Recurring meetings that appear multiple times in the feed (one per occurrence) look like duplicates when dates are omitted.
- **Status:** ✅ Fixed
- **Location:** `remy/google/calendar.py` — `_parse_event_start()` and `format_event()`; optionally `remy/ai/tools/calendar.py` if tool output format is extended.
- **Fix:** In `_parse_event_start()`, format timed events (`dateTime`) as "ddd dd MMM HH:MM" (e.g. "Sun 01 Mar 21:00") via `dt.strftime("%a %d %b %H:%M")` so the model and user see an unambiguous day. All-day format left as-is. Added unit test in `tests/test_google.py` that timed events in `format_event` output include weekday and date (e.g. "01 Mar", "Sun").
- **Reported:** 2026-03-05 (Dale Rogers — from conversation transcript)
- **Fixed:** 2026-03-05

---

## Bug 7: Goal-to-plan linking not working (knowledge store vs goals table ID mismatch)

- **Symptom:** Linking a plan to a goal via `create_plan(goal_id=…)` or `update_plan(goal_id=…)` fails with "Goal X not found" even when that goal appears in `get_goals`. Plans never show under goals when using `get_goals(include_plans=True)`.
- **Root cause:** Goals can come from two stores: **GoalStore** (goals table) and **KnowledgeStore** (knowledge table). When `get_goals` uses the knowledge store (default when it is configured), it returns **knowledge.id** as the goal ID. Plan linking validated and stored **goals.id** only (`plans.goal_id` FK). So IDs from `get_goals` were in a different ID space than plan linking, causing validation to reject valid goals and `include_plans` to never find plans (filtered by `goal_id` in goals table).
- **Status:** ✅ Fixed
- **Location:** `remy/memory/database.py`, `remy/memory/plans.py`, `remy/ai/tools/plans.py`, `remy/ai/tools/memory.py`, `remy/ai/tools/session.py`
- **Fix:** (1) Migration 013: add `plans.knowledge_goal_id` so plans can link to goals in the knowledge store. (2) PlanStore: `create_plan` / `update_plan_goal` / `list_plans` / `get_plan` support both `goal_id` (goals table) and `knowledge_goal_id` (knowledge store). (3) Tool executors: validate `goal_id` against goal_store first, then knowledge_store; pass the appropriate id to the store. (4) `get_goals(include_plans=True)` when using knowledge store now filters plans by `knowledge_goal_id`. (5) `get_plan` / `list_plans` resolve knowledge-store goal IDs to titles for display. (6) `update_plan` added to the plans tool category in session help.
- **Reported:** 2026-03-05
- **Fixed:** 2026-03-05

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

---

## Bug 8: Spaces pruned when assembling chat transcript messages

- **Symptom:** When chat messages are assembled from transcripts (e.g. from agent-transcript `.jsonl` or from message content blocks), spaces are being pruned or collapsed. Text that should contain spaces (e.g. between words or between segments) can appear concatenated or inconsistently spaced.
- **Context:** Chat transcripts store messages as a sequence of entries; each message may have `content` as a list of blocks (e.g. `{ "type": "text", "text": "…" }`). When these are flattened into a single string for display, history, or context, assembly logic that filters with `if p`/`if part` (dropping falsy strings) or uses `.strip()` on segments can remove or collapse spaces — e.g. a block that is only a space gets dropped, or leading/trailing spaces are stripped so adjacent blocks run together.
- **Impact:** Readability and correctness of assembled conversation text; possible impact on prompts or context passed to models if spacing changes meaning.
- **Status:** ✅ Fixed
- **Location:** `remy/bot/handlers/base.py` (`_sanitize_messages_for_claude`), `remy/ai/claude_desktop_client.py` (`_extract_text`)
- **Fix:** (1) In `_sanitize_messages_for_claude`, stop filtering parts with `if p` and join with `"".join(parts)` so empty and space-only segments are preserved in order; skip message only when `not joined.strip()`. (2) In `_extract_text`, concatenate text blocks with `"".join(...)` instead of `" ".join(...)` so no extra spaces are inserted between blocks.
- **Reported:** 2026-03-05
- **Fixed:** 2026-03-05

---

## Bug 10: MarkdownV2 entity parse error causes Anthropic retry loop + Telegram disconnect

- **Symptom:** Remy sends a message with MarkdownV2 formatting, Telegram rejects it with a `BadRequest: can't parse entities` error. The Claude client (`stream_with_tools`) then hits max iterations (6), causing multiple retries. Telegram subsequently drops the connection with `Server disconnected without sending a response`. End result: message is never delivered, and Remy disconnects from Telegram.
- **Evidence from logs (session 2026-03-04):**
  - `[WARNING] remy.ai.claude_client: stream_with_tools hit max iterations (6) for user 8138498165` — multiple occurrences
  - `[WARNING] remy.bot.telegram_bot: Telegram transient error: httpx.RemoteProtocolError: Server disconnected without sending a response` — 3+ occurrences
  - Sequence: Anthropic retry at ~11:36:59 → Telegram disconnect at ~11:37:03 confirms the error → retry → disconnect chain
- **Root cause (hypothesis):** The MarkdownV2 space-fix pre-processing is either (a) stripping a space that Telegram requires as a delimiter around a formatting marker (e.g. `*bold*` adjacent to punctuation), or (b) shifting byte offsets so a closing `*` or `_` lands next to an unescaped special character. The entity parse failure is then treated as a retryable error, triggering the max-iterations loop rather than a clean fallback to plain text.
- **Impact:** High. Message delivery fails silently from the user's perspective; multiple retries add latency; Telegram disconnect requires reconnect cycle.
- **Priority:** High
- **Status:** ✅ Fixed
- **Location:** MarkdownV2 formatting/escape logic (likely `remy/bot/pipeline.py` or `remy/utils/markdown.py`); retry/fallback handling in `remy/ai/claude_client.py` (`stream_with_tools`); Telegram send logic in `remy/bot/handlers/chat.py`
- **Fix:** (1) Catch `BadRequest: can't parse entities` in Telegram send path (`remy/bot/streaming.py`, `remy/bot/handlers/chat.py`) and retry with `parse_mode=None`. (2) DEBUG log of raw formatted string before send. (3) Unit tests for edge cases (`*bold*.`, `_italic_,`) in `tests/test_telegram_formatting.py`.
- **Reported:** 2026-03-04 (Dale Rogers — from log analysis)
- **Fixed:** 2026-03-10

---

## Bug 11: Event loop congestion causes APScheduler job misses, 11-minute message delay, and Telegram disconnect

- **Symptom:** User message ("Hey Bae ❤️") took approximately 11 minutes to receive a reply. APScheduler logged two heartbeat job misses (12m09s and 14m01s behind schedule). Relay inbox poll also missed by 46s. Telegram subsequently disconnected with `RemoteProtocolError: Server disconnected without sending a response`.
- **Evidence from logs (session 2026-03-06):**
  - `[WARNING] apscheduler.executors.default: Run time of job "_heartbeat_job (trigger: cron[minute='*/30'])" was missed by 0:12:09.769199`
  - `[WARNING] apscheduler.executors.default: Run time of job "_heartbeat_job (trigger: cron[minute='*/30'])" was missed by 0:14:01.943538`
  - `[WARNING] apscheduler.executors.default: Run time of job "_poll_relay_inbox (trigger: interval[0:01:00])" was missed by 0:00:46.878906`
  - `[WARNING] remy.bot.telegram_bot: Telegram transient error: httpx.RemoteProtocolError: Server disconnected without sending a response`
- **Root cause (hypothesis):** APScheduler is sharing the same asyncio event loop as message handling. A long Claude response (the "Model Routing Observability Report" — multiple tool calls, large output) blocked the event loop for the duration of generation. Scheduled jobs queued behind it were unable to fire. By the time the loop cleared, Telegram had dropped the connection due to inactivity. The subsequent "Hey Bae" message sat unprocessed until reconnection completed.
- **Impact:** High. 11-minute response delay is severe UX degradation. User has no visibility that the bot is alive or processing. Missed heartbeat jobs mean proactive check-ins and relay polling silently stop during long responses.
- **Priority:** High
- **Status:** ✅ Fixed
- **Location:**
  - `remy/scheduler/proactive.py` (APScheduler setup, `_heartbeat_job`, `_poll_relay_inbox`)
  - `remy/ai/claude_client.py` (long-running stream blocking event loop)
  - `remy/bot/handlers/chat.py` (stream event loop)
- **Fix:** (1) **Yield event loop during streaming** — In `stream_with_tools` (`remy/ai/claude_client.py`), after each yielded event (TextChunk, ToolStatusChunk) call `await asyncio.sleep(0)` so the event loop can run other tasks; every 15 yields call `await asyncio.sleep(0.05)` to give APScheduler a short time slice. In the chat handler (`remy/bot/handlers/chat.py`), every 15 stream events call `await asyncio.sleep(0.05)` so scheduler jobs can run during long responses. (2) **Job-miss watchdog** — In `remy/scheduler/proactive.py`, added a listener for `EVENT_JOB_MISSED`: if a job was missed by ≥60 seconds, log at ERROR with job_id and scheduled_run_time (event-loop congestion signal); otherwise log at WARNING. This improves visibility when the event loop is congested.
- **Related:** Bug 10 (MarkdownV2 entity error → retry loop → Telegram disconnect — similar disconnect symptom via different trigger)
- **Reported:** 2026-03-06 (Dale Rogers — 11-minute reply delay observed in conversation)
- **Fixed:** 2026-03-06

---

## Bug 12: Evening check-in does not call `get_counter` — sobriety streak not reflected

- **Symptom:** The 5pm check-in does not reference the sobriety streak counter. The counter value is injected into memory context at snapshot time but the check-in prompt does not explicitly call `get_counter("sobriety_streak")` at fire time, so the live counter value may be stale or ignored entirely.
- **Root cause:** The mediated check-in prompt does not instruct the agent to call `get_counter` at fire time. The counter value in the injected context block (`<counters>`) is a snapshot from when the heartbeat was built, not the live value. The prompt does not reference the counter block or direct the agent to use it.
- **Impact:** Medium. Sobriety milestone support and acknowledgement is a meaningful part of the evening check-in. Missing or stale streak data means the check-in feels generic and misses an opportunity to reinforce progress.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Location:** Evening check-in prompt / `remy/scheduler/proactive.py` (mediated check-in prompt template); counter injection at fire time in `remy/scheduler/proactive.py`.
- **Fix:** Counters are injected at evening check-in fire time in `remy/scheduler/proactive.py`. Prompt in `remy/bot/pipeline.py` updated to state that the 'counters' array in context is live at send time and to acknowledge sobriety_streak.
- **Reported:** 2026-03-06 (Dale Rogers)
- **Fixed:** 2026-03-10