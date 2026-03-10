# User Story: Proactive Check-In Buttons — Decisions Only

**Status:** ✅ Done

<!-- Filename: US-proactive-buttons-decisions-only.md -->

## Summary

As Dale, I want inline buttons on proactive check-ins (and other suggested_actions) to appear only for **decisions** I need to make — e.g. add a calendar item, archive an email, forward to cowork — not for every surfaced item (e.g. every existing calendar event in the briefing).

---

## Background

Proactive messages (morning briefing, afternoon focus, evening check-in) and the smart-reply flow (US-smart-reply-buttons) attach inline keyboards. The pipeline currently attaches [Add to calendar] for **each** calendar item in the briefing context (`context["calendar"]` in `remy/bot/pipeline.py`). Those items are typically **today's existing events** — already on the calendar. Showing a button per event turns informational content ("Here's your day") into a wall of action buttons, and "Add to calendar" on something already on the calendar is misleading.

Buttons should be reserved for **decision points**: actions Dale might choose to take, such as:
- **Add to calendar** — for a *suggested* or *mentioned* event that is not yet on the calendar (e.g. "Sarah asked for 1:1 this week").
- **Archive email(s)** — e.g. after triage or "archive these 5 promos?" with Confirm/Cancel.
- **Forward to cowork** — when the message is a candidate to send to cowork.
- **Dismiss** — acknowledge and clear the message.

Not for: every existing calendar event in the briefing (informational), or every line of a list when no real choice is being offered.

---

## Acceptance Criteria

1. **Proactive pipeline: no [Add to calendar] for existing events.** When the proactive trigger receives `context["calendar"]` that lists **today's existing calendar events** (from the briefing generator), do **not** attach one [Add to calendar] button per event. Those events are already on the calendar; the content is informational only.
2. **Proactive pipeline: [Add to calendar] only for suggested events.** If the briefing (or any proactive content) includes **suggested** events to add (e.g. "Sarah asked for 1:1" or "Meeting requested: X at Y"), those may have [Add to calendar] buttons. The payload must distinguish "existing events" (no button) from "suggested events" (button allowed). If the current briefing generator does not produce "suggested events", then proactive briefings simply do not attach calendar action buttons for the existing-events list.
3. **suggest_actions tool: decisions only.** The `suggest_actions` tool description (and any prompt guidance) states that buttons must be used only for **decision points** — actions Dale might choose to take (add to calendar for something not yet added, archive, forward to cowork, dismiss). Do not suggest a button for every item in a list when the item is informational (e.g. "here's your calendar" with one button per existing event).
4. **Documentation and schema.** SOUL or tool schema explicitly says: "Use suggest_actions only when offering 2–4 **decisions** (e.g. add event, archive, forward to cowork). Do not attach [Add to calendar] to events that are already on the calendar."
5. **Backward compatibility.** User-initiated flows that use `suggest_actions` for genuine decisions (e.g. [Add to calendar] for one suggested event, [Forward to cowork], [Dismiss]) are unchanged. Only the proactive path and the guidance for when to show buttons are tightened.

---

## Implementation

**Files:** `remy/bot/pipeline.py`, `remy/scheduler/briefings/morning.py` (or wherever structured payload is built), `remy/ai/tools/schemas.py` (suggest_actions description), optionally `config/SOUL.md` or briefing prompts.

### 1. Pipeline: stop attaching calendar keyboard for existing events

In `run_proactive_trigger`, the block that does `elif context and (cal := context.get("calendar"))` builds one button per calendar item. The morning briefing's `generate_structured()` currently puts **today's existing events** in `payload["calendar"]`. Options:

- **Option A:** Remove this keyboard for `context["calendar"]` entirely when the payload represents "today's events" (current behaviour). Only attach [Add to calendar] when the context carries a separate key, e.g. `context["suggested_events"]`, that the briefing generator populates when Claude or the generator identifies events to add (e.g. from email or narrative). If `suggested_events` is not yet produced, no calendar buttons on proactive briefings for now.
- **Option B:** Keep a single generic [Add to calendar] or [Add event] that opens a follow-up (e.g. "What event?" or a list of suggested-only items) instead of one button per existing event.

Recommendation: Option A — do not attach [Add to calendar] for `context["calendar"]` when it is the list of existing events. Introduce `suggested_events` (or equivalent) in a follow-up when the briefing can reliably produce suggested events to add.

### 2. suggest_actions schema and SOUL

- Update `suggest_actions` description to state that buttons are for **decisions only**: add to calendar (for something not yet on the calendar), archive, forward to cowork, dismiss. Not for every listed item when the list is informational.
- Optionally add a short line in SOUL or briefing instructions: "Inline buttons only for decisions Dale can make (e.g. add event, archive email), not for every calendar event or list item."

### 3. Briefing generator (if extending)

- When adding "suggested events" (events to add), put them in a separate field (e.g. `suggested_events`) so the pipeline can attach [Add to calendar] only for those. Do not mix with `calendar` (today's existing events).

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Morning briefing with today's events only | No [Add to calendar] buttons for those events; message may have other buttons (e.g. reminder [Snooze] [Done] if reminder) |
| Proactive message with suggested_events (future) | [Add to calendar] only for suggested_events entries |
| User asks "What's on today?" and Claude lists events | suggest_actions not used for each event, or only one "Add an event" if appropriate |
| User gets email triage with "Archive these?" | [Confirm] [Cancel] or [Archive] allowed (decision) |
| Reminder proactive message | [Snooze 5m] [Snooze 15m] [Done] unchanged (these are decisions) |

---

## Out of Scope

- Changing reminder keyboards ([Snooze] [Done]).
- Adding new callback types; this story is about when and what to attach, not new actions.
- One-tap automations list (separate flow).
