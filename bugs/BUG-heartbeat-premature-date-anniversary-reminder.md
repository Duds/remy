# BUG: Heartbeat Fires Date-Specific Memory Facts Without Checking Today's Date

**Date:** 2026-03-09  
**Severity:** High — caused emotional distress; surfaced Jane's father's death anniversary on wrong day (twice)  
**Status:** Fixed (2026-03-11) — see Bug 46 in BUGS.md

---

## Summary

The mediated heartbeat/proactive check-in reads memory facts and surfaced a date-specific fact
(Jane's father's death anniversary — 26 March) on 9 March, 17 days early. This happened twice
in the same day.

---

## Observed Behaviour

- Heartbeat fired the fact about Jane's dad's death anniversary (26 March) on 9 March 2026
- The *scheduled reminder* for 26 March is correctly set and not the cause
- The heartbeat is treating date-adjacent memory facts as immediately relevant without
  verifying whether today's date matches or is close enough to warrant surfacing

---

## Root Cause (Hypothesis)

The mediated heartbeat reads memory context and generates a message using Claude. When a memory
fact contains a date, Claude surfaces it as relevant without calling `get_current_time` to verify:

1. Whether today IS that date (exact match — should fire)
2. Whether today is within a deliberate lead-up window (e.g. 1–3 days before — could fire with
   explicit framing like "coming up in 2 days")
3. Whether today is too far away to mention at all (>3 days — should NOT fire)

In this case, 17 days out is clearly outside any reasonable lead-up window.

---

## Impact

- Dale received two distressing false reminders about a bereavement anniversary on the wrong day
- High emotional cost; trust impact on heartbeat reliability

---

## Required Fix

- Heartbeat (and any mediated reminder system) MUST call `get_current_time` before surfacing
  any date-specific memory fact
- Logic gate:
  - `date == today` → surface normally
  - `1 <= days_until <= 3` → surface with explicit framing ("coming up in N days")
  - `days_until > 3` → do NOT surface in heartbeat; let the scheduled reminder handle it
- Apply this rule to ALL date-specific facts (anniversaries, deadlines, birthdays, etc.)
- Also apply to Remy's own in-conversation reasoning — always verify date before citing
  a memory fact as time-relevant

---

## Related

- Memory fact id=72: Jane's dad's death anniversary (26 March)
- Scheduled reminder for 26 March at 09:00 is correctly set — not the source of the bug

---

*Logged by Remy*
