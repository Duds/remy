# Goal Planning Skill

## Step Decomposition

Break a goal into the smallest independently executable steps. A step is too large if it requires more than one distinct action or produces more than one distinct output.

Step format: **verb + object + measurable outcome**

> Write first draft of X, producing a complete document with all sections filled.
> Schedule meeting with Y, resulting in a calendar invite accepted by all attendees.

Never write a step as a state ("Goal is researched"). Write it as an action with a clear endpoint.

## Identifying Blockers vs Next Actions

A **next action** is something Dale can start immediately. A **blocker** is something that cannot start until an external condition is met.

Mark a step as a blocker only when:
1. It depends on a response, decision, or resource that is not yet available
2. The blocker is outside Dale's control right now

If a step can be started — even partially — it is a next action, not a blocker.

## When a Step is Stalled vs Not Started

Stalled: started, in progress, but no forward movement in the last 3+ days.
Not started: queued but not yet touched — this is normal, not a problem.

Surface stalled steps. Do not surface not-started steps unless the deadline is near.

## Output Format

Return an updated step list with statuses and exactly one identified next action:

```json
{
  "goal_id": <int>,
  "next_action": "The single most important step to do right now.",
  "steps": [
    {"step_id": <int>, "title": "...", "status": "pending|done|blocked", "blocker": "...or null"}
  ]
}
```

If all steps are done, set `next_action` to `"Goal complete — ready to close."`.
