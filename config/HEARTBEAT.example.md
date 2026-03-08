# Evaluative Heartbeat — Template

Copy this file to `config/HEARTBEAT.md` (gitignored) to use as your private heartbeat config. Your HEARTBEAT.md is never committed; this file is the public template so forks can make it their own.

If HEARTBEAT.md is missing, the heartbeat runs using this template.

---

## Goals

- Check for overdue or stale goals (no progress for N days).
- Threshold: surface when one or more goals are overdue or stale according to your criteria (define thresholds in this file).

---

## Calendar

- Check events in the next 90 minutes.
- Threshold: surface when there are upcoming events that warrant a nudge (e.g. meeting in 15 minutes). Adjust as needed.

---

## Email

- Check high-priority or unread count.
- Threshold: surface when unread count or high-priority items exceed a limit (define as needed).

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

## Wellbeing Check-in

- **Intent and thresholds:** Define what this check-in is for, your time window and minimum hours between check-ins, any counters to reference, and personal context (tone, triggers). If you leave this section empty or generic, the model will skip or respond HEARTBEAT_OK for this category.
- You receive **current time**, **already surfaced today**, and **counters** (if configured) in the Current state block. If it is within your window and no wellbeing check-in has been sent within the minimum interval, consider a **compassionate, brief check-in**. Warmth and presence over advice; never preachy or generic. One or two short sentences. Do not sound like a reminder app.
- **Model:** Always use Tier 2 (Sonnet) for this evaluation — judgment and compassion, not threshold scoring.

---

## Agent Tasks

- Check agent_tasks for `status = failed` where `surfaced_to_remy = 0` — surface immediately, do not suppress.
- Check agent_tasks for `status = stalled` where `surfaced_to_remy = 0` — surface immediately.
- Check agent_tasks for `status = done` where `surfaced_to_remy = 0` — surface in the next natural heartbeat window.
- Use the task `synthesis` field as message content — never surface raw worker output.
- Set `surfaced_to_remy = 1` after delivery (handled automatically by the heartbeat job).
- Failed and stalled tasks require Dale's decision: present clearly and ask what to do next.

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
