# User Story: Plan Tracking

⬜ Backlog

## Summary
As a user, I want Remy to document and track multi-step plans that unfold over time —
including repeated attempts at individual actions — so that nothing falls through the cracks
and I can always see where a plan stands.

---

## Background

Goals and reminders handle "what I want to achieve" and "nudge me at a time". Neither is
designed for plans that have internal structure: ordered or parallel steps, steps that may
need to be retried (e.g. "call the mechanic — no answer — try again Thursday"), and an
overall arc from conception to completion.

The existing `goals` table is a flat list of titles and descriptions. It has no concept of
steps, sequencing, attempt history, or retry state. Background jobs track async tasks, not
user-facing plans.

A plan is something in between: it lives for days, weeks, or months; it has discrete
actions; those actions sometimes fail, stall, or need to be reattempted; and Doc needs to
be able to check in and see the full picture at any time.

---

## Acceptance Criteria

1. **Create a plan.** Remy can create a named plan with an optional description and an
   ordered list of steps, stored in SQLite. Each step has a title and optional notes.
2. **Step statuses.** Each step carries one of: `pending`, `in_progress`, `done`,
   `skipped`, `blocked`. The plan itself carries: `active`, `complete`, `abandoned`.
3. **Attempt logging.** Each step supports multiple attempt entries. An attempt records:
   date/time, outcome (e.g. "no answer", "partial", "succeeded"), and free-text notes.
   Attempts are append-only — history is never overwritten.
4. **Update a step.** Remy can mark a step with a new status, add an attempt, or update
   its notes via natural language ("mark step 2 as blocked — waiting on council approval").
5. **View a plan.** `get_plan` tool returns the full plan: title, description, overall
   status, each step with its status and full attempt history.
6. **List plans.** `list_plans` tool returns a summary of all active plans (title, step
   progress count, last activity date).
7. **Natural language interface.** All operations are accessible conversationally — no
   slash commands required (though `/plans` can be added as a convenience alias).
8. **Proactive surfacing.** Plans with steps that have been `pending` or `in_progress`
   for more than 7 days without a new attempt are flagged in the morning briefing.
9. **No new Python dependencies.**

---

## Implementation

**New file:** `drbot/memory/plans.py`
**Modified files:** `drbot/memory/database.py`, `drbot/ai/tool_registry.py`,
`drbot/scheduler/proactive.py`, `drbot/bot/handlers.py`

### Schema (`drbot/memory/database.py`)

```sql
CREATE TABLE IF NOT EXISTS plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT,
    status       TEXT NOT NULL DEFAULT 'active',  -- active | complete | abandoned
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,   -- 1-based ordering
    title       TEXT NOT NULL,
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done | skipped | blocked
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_step_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id     INTEGER NOT NULL REFERENCES plan_steps(id) ON DELETE CASCADE,
    attempted_at TEXT NOT NULL,
    outcome     TEXT NOT NULL,   -- free text: 'no answer', 'partial', 'succeeded', etc.
    notes       TEXT
);
```

### `PlanStore` (`drbot/memory/plans.py`)

```python
class PlanStore:
    async def create_plan(user_id, title, description, steps: list[str]) -> int: ...
    async def add_step(plan_id, position, title, notes) -> int: ...
    async def update_step_status(step_id, status) -> None: ...
    async def add_attempt(step_id, outcome, notes) -> None: ...
    async def get_plan(plan_id) -> dict: ...          # full detail incl. attempts
    async def list_plans(user_id, status='active') -> list[dict]: ...
    async def update_plan_status(plan_id, status) -> None: ...
    async def stale_steps(user_id, days=7) -> list[dict]: ...  # for briefing
```

### Tools (`drbot/ai/tool_registry.py`)

**`create_plan`**
```json
{
  "name": "create_plan",
  "description": "Create a new multi-step plan. Use when the user describes a goal that has discrete actions, may span days or weeks, or where individual steps may need to be retried.",
  "input_schema": {
    "type": "object",
    "properties": {
      "title":       { "type": "string" },
      "description": { "type": "string" },
      "steps":       { "type": "array", "items": { "type": "string" }, "description": "Ordered list of step titles." }
    },
    "required": ["title", "steps"]
  }
}
```

**`get_plan`**
```json
{
  "name": "get_plan",
  "description": "Retrieve a plan by ID or title, including all steps and their full attempt history.",
  "input_schema": {
    "type": "object",
    "properties": {
      "plan_id": { "type": "integer" },
      "title":   { "type": "string", "description": "Fuzzy title search if plan_id not known." }
    }
  }
}
```

**`list_plans`**
```json
{
  "name": "list_plans",
  "description": "List the user's plans with step progress and last activity.",
  "input_schema": {
    "type": "object",
    "properties": {
      "status": { "type": "string", "enum": ["active", "complete", "abandoned", "all"], "description": "Default: active." }
    }
  }
}
```

**`update_plan_step`**
```json
{
  "name": "update_plan_step",
  "description": "Update the status of a plan step and/or log a new attempt.",
  "input_schema": {
    "type": "object",
    "properties": {
      "step_id":    { "type": "integer" },
      "status":     { "type": "string", "enum": ["pending", "in_progress", "done", "skipped", "blocked"] },
      "attempt_outcome": { "type": "string", "description": "If this update is the result of an attempt, describe the outcome (e.g. 'no answer', 'sent email', 'approved')." },
      "attempt_notes":   { "type": "string" }
    },
    "required": ["step_id"]
  }
}
```

**`update_plan_status`**
```json
{
  "name": "update_plan_status",
  "description": "Mark an entire plan as complete or abandoned.",
  "input_schema": {
    "type": "object",
    "properties": {
      "plan_id": { "type": "integer" },
      "status":  { "type": "string", "enum": ["complete", "abandoned"] }
    },
    "required": ["plan_id", "status"]
  }
}
```

### Proactive Surfacing (`drbot/scheduler/proactive.py`)

In the morning briefing, call `PlanStore.stale_steps(user_id, days=7)`. If any steps are
returned, append a section to the briefing:

```
📋 Plans needing attention:
  • "Fence repair" — Step 2 (Get quotes) has been pending for 9 days.
  • "Switch energy provider" — Step 1 (Call AGL) last attempted 12 days ago: no answer.
```

### `/plans` handler (`drbot/bot/handlers.py`)

Convenience alias. Calls `list_plans` for the user and formats output as:

```
📋 Active plans (2):

1. Fence repair [3 steps — 1 done, 1 in progress, 1 pending]
   Last activity: 3 days ago

2. Switch energy provider [4 steps — 0 done, 1 in progress, 3 pending]
   Last activity: 12 days ago
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| "Make a plan to fix the fence — steps: get quotes, hire contractor, supervise work" | Plan created with 3 steps, all `pending` |
| "Log an attempt on step 1 — left voicemail for Jim's Fencing" | Attempt recorded; step moves to `in_progress` |
| "Try again — still no answer" | Second attempt appended; step remains `in_progress` |
| "Mark step 1 done — booked Jim for Friday" | Step status → `done`; attempt logged |
| "What's the status of my fence plan?" | Full plan returned with step statuses and attempt history |
| `/plans` | Summary list of active plans |
| Step pending for 8 days | Appears in morning briefing |
| All steps done → mark plan complete | Plan status → `complete`; no longer in active list |
| Plan abandoned | Status → `abandoned`; excluded from briefing |

---

## Out of Scope

- Step dependencies / DAG ordering (all steps are sequential by position for now)
- Sub-steps (one level only)
- Automatic retry scheduling (retries are manually triggered by Doc)
- Shared plans (single-user only)
- Integration with external project management tools
