# Proactive Heartbeat Architecture
*Remy nervous system design — drafted in conversation, April 2026*

---

## Overview

The heartbeat system transforms Remy from a purely reactive assistant (responds when asked) into a proactive agent (reaches out when it matters). The design goal is signal without noise — Remy should feel like a thoughtful presence, not a notification feed.

The core metaphor: **a flywheel with a regulator.**
- The flywheel keeps momentum — the system is always spinning, always checking
- The regulator decides whether that energy becomes speech

---

## Architecture

### 1. The Tick — Cron Driver

A cron job fires every **15 minutes** — fast enough to catch time-sensitive events (calendar alerts, sobriety milestones, relay messages), slow enough not to be exhausting.

Each tick wakes the regulator. The regulator decides everything from there.

```
*/15 * * * *  →  regulator.run()
```

---

### 2. The Regulator — Gate Logic

The regulator runs four sequential checks. Later stages are only reached if earlier ones pass. This keeps costs low — expensive reasoning only fires when warranted.

#### Gate 1 — Hard Time Rules *(no tokens, instant)*
- Is Dale in a no-interrupt window? (e.g. 11pm–7am)
- Is it a known focus block? (calendar-aware, optional)
- → **FAIL: sleep. PASS: continue.**

#### Gate 2 — Recency Check *(no tokens, instant)*
- Has there been a conversation in the last 30 minutes?
- If yes: back off unless trigger is flagged URGENT
- → **FAIL: hold. PASS: continue.**

#### Gate 3 — Trigger Queue *(no tokens, queue read)*
- Is there anything in the trigger queue?
- The queue holds registered events from other subsystems (see below)
- → **EMPTY: sleep. HAS ITEMS: continue.**

#### Gate 4 — Reasoning Layer *(tokens, LLM call)*
- Only fires if Gates 1–3 pass
- Pulls context: goals, recent memory, emotional tone, calendar, time of day
- Evaluates each queued trigger: **send / hold / discard**
- Composes message if sending
- → **Output: proactive message or silence**

---

### 3. The Trigger Queue

The queue is the heartbeat's vocabulary. Rather than the reasoning layer scanning cold every tick, other subsystems register events into the queue when they occur.

#### Queue entry structure:
```json
{
  "id": "uuid",
  "source": "sobriety_tracker",
  "type": "milestone_approaching",
  "priority": "normal",        // normal | high | urgent
  "payload": {
    "milestone": "30 days",
    "date": "2026-04-03"
  },
  "registered_at": "2026-04-02T09:00:00",
  "expires_at": "2026-04-03T23:59:59"
}
```

#### Priority levels:
- **urgent** — bypasses recency gate (Gate 2). e.g. missed calendar event, relay message flagged critical
- **high** — normal gates apply but bumped in reasoning evaluation
- **normal** — standard processing

#### Example trigger sources:
| Source | Example triggers |
|---|---|
| Calendar subsystem | Event in 30 min, gap in schedule detected, event tomorrow with no prep |
| Sobriety tracker | Day before milestone, day of milestone |
| Goal engine | Goal stale for N days, plan step overdue |
| Relay | Unread cowork message, task assigned |
| Email | High-priority sender detected |
| Health context | Morning check-in not yet had (if morning briefing configured) |
| Time-of-day | End-of-day nudge if no activity logged |

---

### 4. The Reasoning Layer

When the gate opens, the reasoning layer receives:
- The trigger queue items (filtered to non-expired)
- Current memory context (goals, facts, emotional tone)
- Recent conversation summary (last N messages)
- Current time and day

It answers three questions per trigger:
1. **Is this still relevant?** (things change — a calendar event may have been discussed already)
2. **Is this the right moment?** (tone-aware, recency-aware)
3. **What's the right message?** (brief, human, not robotic)

Output is either a composed message or a discard with optional re-queue for next tick.

---

### 5. Dale's State Model

The regulator maintains a lightweight state model, updated each tick:

```
last_message_time       — timestamp of last inbound message
last_response_time      — timestamp of last outbound message  
avg_response_latency    — rolling average (signals engagement level)
inferred_tone           — last detected tone from conversation
active_hours_today      — count of ticks with activity
```

This lets the regulator make tone-aware decisions:
- Short, clipped replies → throttle back, don't pile on
- Engaged and warm → more latitude to reach out
- Gone quiet mid-afternoon → consider a gentle check-in if queue has something

---

### 6. Sleep State

Beyond time-window rules, the regulator has a **signal-based sleep state.**

If no inbound messages for > 6 hours during normal waking hours:
- High/urgent triggers: still fire
- Normal triggers: hold and re-queue, don't accumulate and dump when Dale returns

The goal: when Dale comes back after a long silence, he gets **one thoughtful message**, not six banked notifications.

---

### 7. Cost Management

The expensive part is Gate 4 (LLM reasoning call). The architecture minimises this:

- Gates 1–3 are pure logic — zero token cost
- Gate 4 only fires when there's something in the queue AND the gates pass
- Queue expiry prevents stale triggers from accumulating and inflating context
- Reasoning call uses a lightweight model (not full Sonnet) unless composing a complex message

Estimated token spend: low. Most ticks never reach Gate 4.

---

### 8. Configuration

Key parameters (tunable via config):

```yaml
heartbeat:
  tick_interval_minutes: 15
  no_interrupt_start: "23:00"
  no_interrupt_end: "07:00"
  recency_backoff_minutes: 30
  silence_sleep_hours: 6
  queue_default_expiry_hours: 24
  state_model_window_messages: 10
```

---

## Design Principles

1. **Rules filter volume, reasoning filters quality.** Cheap gates protect expensive reasoning.
2. **The queue drives speech, not the clock.** The cron is a heartbeat, not a scheduler.
3. **One thoughtful message beats six stacked ones.** The regulator throttles on return from silence.
4. **Read the room.** Dale's state model makes the system tone-aware, not just time-aware.
5. **Silence is a valid output.** Most ticks should result in nothing. That's correct behaviour.

---

## Status

- [ ] Cron driver implementation
- [ ] Regulator gate logic
- [ ] Trigger queue (storage + registration API)
- [ ] Subsystem integrations (calendar, sobriety, goals, relay, email)
- [ ] Reasoning layer prompt + model selection
- [ ] Dale's state model
- [ ] Sleep state logic
- [ ] Config file + tuning

---

*"It's not a heartbeat. It's a nervous system." — Dale, April 2026*
