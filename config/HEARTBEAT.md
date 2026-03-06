# Evaluative Heartbeat — Evaluation Checklist

The heartbeat runs on a schedule (default: every 30 minutes during waking hours). It queries current state and evaluates whether anything warrants contacting the user. If not, it exits silently (HEARTBEAT_OK).

**HEARTBEAT.local.md is optional.** You do not need to create it. The heartbeat runs using this file (HEARTBEAT.md) alone. Only create `config/HEARTBEAT.local.md` if you want to add personal thresholds, wellbeing signals, or private overrides (it is gitignored). Copy from `config/HEARTBEAT.example.md` if you do.

No personal detail belongs in this file — use HEARTBEAT.local.md for private thresholds.

---

## Goals

- Check for overdue or stale goals (no progress for N days).
- Threshold: surface when one or more goals are overdue or stale according to your criteria (define in HEARTBEAT.local.md if needed).

---

## Calendar

- Check events in the next 90 minutes.
- Threshold: surface when there are upcoming events that warrant a nudge (e.g. meeting in 15 minutes). Adjust in HEARTBEAT.local.md.

---

## Email

- Check high-priority or unread count.
- Threshold: surface when unread count or high-priority items exceed a limit (define in HEARTBEAT.local.md).

---

## Reminders

- Check pending one-time reminders.
- Threshold: surface when a reminder is due or overdue.

---

## Daily Orientation (e.g. good morning)

- You receive **current time** (date, time, timezone, day of week) and **already surfaced today** (what messages were already sent).
- If it is **morning** (past wake time, e.g. 07:00) and **no daily orientation has been sent today**, consider a brief good-morning-style message: goals, calendar, or email summary if relevant.
- Surface at most **once per day**; if "already surfaced today" lists a daily orientation, respond HEARTBEAT_OK for this category.

---

## End-of-Day Reflection

- Is it past the configured wind-down hour with no end-of-day check yet?
- Were goal steps completed or missed?
- Surface at most once per day (check already surfaced today).

---

## Wellbeing Check-in (e.g. afternoon sobriety reminder)

- **Stub:** Personal thresholds and signals belong in HEARTBEAT.local.md only (time window, e.g. 13:00–19:00, minimum hours between check-ins).
- You receive **current time** and **already surfaced today**. If it is within the afternoon/evening window and no wellbeing check-in has been sent today (or within the minimum hours), consider a compassionate, brief check-in.
- **Model:** Always use Tier 2 (Sonnet) for this evaluation — judgment and compassion, not threshold scoring.

---

## Model Selection

- **Threshold checks and HEARTBEAT_OK decisions:** Tier 0 — local model (e.g. Qwen3 1.7B /no_think).
- **Observation logging and brief summaries:** Tier 1 — fast/cheap remote model.
- **Goal/calendar/email judgment, daily orientation, end-of-day:** Tier 2 — Sonnet.
- **Wellbeing check-in:** Always Tier 2 — Sonnet.
- **Never use Tier 3 (Opus) in the heartbeat.**

---

## Silence Rules

- If the combined evaluation result is "nothing warrants attention", respond with exactly: `HEARTBEAT_OK`
- Do not send a message to the user when responding HEARTBEAT_OK.
- When surfacing content, keep it concise and actionable.
