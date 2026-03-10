# User Story: Context-Aware Reminder Delivery via Remy (Remy-Mediated Reminders)

**Status:** ✅ Done

## Summary

As Dale, I want reminder delivery routed through Remy's AI pipeline by default, so that every proactive message is contextually composed at fire time — not pre-written. Reminders should feel like they come from someone who knows me, not a task scheduler.

---

## Background

Cron-fired reminders currently deliver a static, pre-written notification string directly to Telegram. This is fine for purely logistical triggers (e.g. "leave now or you'll miss the bus") but is tone-deaf for anything health, emotional, or goal-adjacent. A canned "don't drink" message at 5pm is useless at best and alienating at worst. Dale needs Remy to compose the message in real time, with awareness of context, history, and emotional state.

Morning briefings already route through Remy's AI pipeline before delivery (see **US-conversational-briefing-via-remy**). All reminders should do the same, unless explicitly excepted.

**Phase:** 5 — Smart Behavioral Automation (extension).  
**Priority:** S (Should Have).

---

## Key Use Case (Trigger)

Daily 5pm sobriety trigger: Dale's highest-risk window is 5:00–6:30pm (the "bottle shop run" impulse). A static reminder ("don't drink") is counterproductive. Remy should fire at 5pm, assess the day's context (what was discussed, what milestones are active, how Dale seems), and compose a message that meets him where he is.

---

## Acceptance Criteria

1. **`mediated` flag added to `automations` table;** existing reminders default to `false`.
2. **`ProactiveScheduler` checks `mediated` flag at fire time;** routes accordingly.
3. **Mediated path:** Claude receives reminder label + injected memory/goals + recent session summary; output sent as Telegram message.
4. **Non-mediated path:** unchanged — static label delivered directly.
5. **5pm daily sobriety trigger** created as a `mediated` automation.
6. **`list_reminders` output** distinguishes mediated vs direct reminders.
7. **Morning briefing refactored** to use shared `_compose_proactive_message()` helper.
8. **No regression** on existing non-mediated reminders.

---

## Implementation

### Proposed approach

- Add a `mediated` boolean flag to the `automations` table (default `false` for backwards compatibility).
- When `mediated = true`, the `ProactiveScheduler` does **not** send the stored label string directly. Instead, it constructs a system prompt with the reminder label + memory context + recent conversation summary, runs a Claude completion, and sends the AI-generated message.
- Morning briefing already uses this pattern — extract into a shared `_compose_proactive_message(label, context)` helper.
- Exceptions (direct CRON, no mediation): purely logistical, timing-critical reminders where delay or nuance could cause harm (e.g. "appointment in 15 minutes", "leave now"). These keep `mediated = false`.
- `/schedule-daily` and `/schedule-weekly` commands gain an optional `--mediated` flag (default: prompt Dale to choose).
- `list_reminders` tool output includes mediation status per reminder.

### Exceptions (stay as direct CRON)

- Hard appointment alarms where the only job is "don't miss this" (e.g. Phil Woods telehealth 9am).
- Pure logistical/errand reminders with no emotional weight.
- Any trigger where a 5–30 second AI round-trip delay could cause a missed action.

### Notes

- This is the natural extension of **US-conversational-briefing-via-remy** — same pattern, generalised to all reminders.
- Latency: mediated reminders will take 5–30s longer to deliver; acceptable for daily/weekly triggers, not for hard alarms.
- The 5pm sobriety trigger is the primary motivating use case; it should be the first mediated automation created after implementation. Create it via: `/schedule-daily 17:00 --mediated sobriety check` (or similar label).

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Mediated reminder fires | Claude composes message from label + context; message sent to Telegram |
| Non-mediated reminder fires | Stored label string sent directly (unchanged behaviour) |
| `list_reminders` | Shows mediation status per reminder |
| Morning briefing | Uses shared `_compose_proactive_message()`; no behaviour change |
| Existing automations after migration | All have `mediated = false`; fire as before |

---

## Out of Scope

- Changing the set of reminders that *exist* (only delivery path and one new 5pm mediated trigger).
- Real-time sync or re-evaluation of reminder content; composition happens at fire time only.
