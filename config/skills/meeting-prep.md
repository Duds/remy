# Meeting Prep Skill

## Timing

Surface meeting prep exactly 30 minutes before the meeting starts. Do not surface earlier — it creates noise. If the heartbeat fires and the meeting is more than 30 minutes away, respond HEARTBEAT_OK for this event.

## What to Surface

For every meeting, check and surface:

1. **Attendees** — names and roles (from calendar or contacts)
2. **Agenda** — from calendar description or linked docs. If missing, flag it: "No agenda set."
3. **Linked documents** — any documents or links in the calendar event
4. **Open decisions** — anything from memory or recent conversations that needs resolution in this meeting

If the meeting has no agenda and no linked documents, flag it explicitly: "⚠️ No agenda or docs attached."

## Recurring 1:1s

If the meeting is a recurring 1:1, check memory for the last discussed topic and surface it as context:

> Last 1:1 with [name] covered: [topic].

Do not surface this if memory has no record of the last session.

## Output Format

Brief bullets. No prose. No greetings. Maximum 150 words.

```
[Meeting title] in 30 min
- Attendees: [list]
- Agenda: [items or "Not set"]
- Docs: [links or "None attached"]
- Open: [decisions needed or "Nothing flagged"]
```

If nothing needs attention (all prep is in order, no open decisions), respond HEARTBEAT_OK.
