# Remy Bug Report

_Last updated: 2026-03-11_

Archived bugs:
- 1–41 (2026-03-04) → [docs/archive/BUGS-archived-2026-03-04.md](docs/archive/BUGS-archived-2026-03-04.md)
- 1–12, 42–45 (2026-03-11) → [docs/archive/BUGS-archived-2026-03-11.md](docs/archive/BUGS-archived-2026-03-11.md)

---

## Bug 46: Jane's dad's death anniversary mentioned repeatedly (wrong day and/or multiple times)

- **Symptom:** Remy keeps telling Dale that today is Jane's dad's anniversary of his death, sometimes multiple times in a day — even when today is not that date (e.g. 17 days early) or when she has already mentioned it.
- **User flow:** User reports Remy repeatedly surfaces this sensitive fact without date verification and without tracking that she has already mentioned it today.
- **Where knowledge is kept:**
  1. **`knowledge` table** — fact id 72 (or similar): "Jane's dad's death anniversary (26 March)". Extracted and stored as a relationship/deadline fact.
  2. **`automations` table** — one-time reminder for 26 March 09:00 with label referring to the anniversary (correctly scheduled; reminder fire is not the bug).
  3. **`config/HEARTBEAT.md`** (gitignored) — user's private config may include personal context (e.g. Wellbeing section "personal context (tone, triggers)") that mentions the anniversary.
- **What triggers it:**
  1. **Heartbeat** (every 15–30 min) — passes `current_local_time`, `already_surfaced_today`, goals, calendar, email, **full reminders list** (including future one-time reminders), and counters. If HEARTBEAT.md contains the fact, or if the reminders list includes the 26 March reminder, the model sees it every run. No date gate and no per-fact "already surfaced" check → surfaces repeatedly.
  2. **Regular chat** — `MemoryInjector` injects top-5 semantically similar facts. Query = current message. Messages about morning, check-in, Jane, wellbeing, or grief can pull this fact in; Remy may mention it in reply.
  3. **Proactive triggers** (briefing, evening check-in) — use structured context (goals, calendar); no MemoryInjector, so less likely. But if HEARTBEAT.md or briefing context includes it, possible.
- **Root cause:** (1) Date-specific facts surfaced without `get_current_time` verification (see bugs/BUG-heartbeat-premature-date-anniversary-reminder.md). (2) No per-fact "already surfaced today" tracking for sensitive date facts — `already_surfaced_today` only lists message previews, not which facts were mentioned. (3) Heartbeat and chat both have access to the fact via different paths; heartbeat runs frequently.
- **Impact:** High. Repeated false or excessive reminders about a bereavement anniversary cause emotional distress and erode trust.
- **Priority:** High
- **Status:** ✅ Fixed
- **Fix:** (1) HeartbeatHandler: filter one-time reminders whose `fire_at` is >3 days in future before passing to model; add prominent "TODAY'S DATE" and date-sensitivity instruction to context; add "do not repeat" instruction. (2) MemoryInjector: add `<date_sensitivity>` hint when facts present — current date + "do not proactively mention anniversaries, death dates, birthdays unless user asks or today is that date (or within 3 days)". (3) config/HEARTBEAT.example.md: strengthen Date-sensitive memory section. (4) Tests: `_filter_reminders_for_heartbeat` unit tests + handler integration test.
- **Location:** `remy/bot/heartbeat_handler.py`, `remy/memory/injector.py`, `config/HEARTBEAT.example.md`
- **Reported:** 2026-03-11 (Dale Rogers)
- **Fixed:** 2026-03-11

---

## Bug 47: Remy calls Board instead of appropriate sub-agents

- **Symptom:** Remy invokes `run_board` for tasks that should be routed to specialist sub-agents (e.g. researcher, coder, ops, analyst). The Board of Directors is intended for strategic, multi-perspective analysis only — not for leg work, web search, code execution, or data tasks.
- **User flow:** User asks for research, code help, file/email operations, or analysis → Remy calls Board instead of the appropriate specialist.
- **Root cause:** The hand-off path has only one target today: the Board. There is no routing by task type; no Researcher, Coder, Ops, or Analyst sub-agents are wired as dispatch targets. Per US-multi-agent-architecture: Board = explicit user opt-in only; auto-routing should go to specialists.
- **Impact:** Heavy, expensive Board runs for tasks that could be handled by cheaper specialist agents; wrong tool for the job; slower and costlier than necessary.
- **Priority:** Medium
- **Status:** ✅ Fixed
- **Fix:** (1) Removed automatic Board hand-off when max_iterations is hit — now emit StepLimitReached (Continue / Break down / Stop) instead of HandOffToSubAgent. Board = explicit user opt-in only. (2) Tightened run_board tool description: "ONLY use when user explicitly asks for Board/convene/strategic analysis"; "Do NOT use for web search, code, file/email ops — use web_search, run_python, etc."
- **Location:** `remy/ai/claude_client.py`, `remy/ai/tools/schemas.py`
- **Reported:** 2026-03-11 (Dale Rogers)
- **Fixed:** 2026-03-11
