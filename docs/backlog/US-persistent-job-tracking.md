# User Story: Persistent Background Job Tracking

## Summary
As a user, I want to be able to check the status of any background task Remy is working on,
and re-read completed results after the fact — even if the bot restarts mid-task.

---

## Background

Phase 7, Step 1 (`US-background-task-runner`) gives fire-and-forget execution with an
in-memory `asyncio.create_task()`. If the container restarts while a job is running, the
result is silently lost and the user has no way to know what happened. This story adds a
lightweight SQLite-backed job registry so results survive restarts and remain queryable.

**This is Phase 7, Step 2. Depends on `US-background-task-runner` being complete.**

---

## Acceptance Criteria

1. **Every background job is written to SQLite immediately on creation** (status: `queued`),
   updated to `running` when it starts, and `done` or `failed` on completion.
2. **`/jobs` command** lists the 10 most recent background jobs with status, job type, and
   a truncated result snippet.
3. **`list_background_jobs` tool** allows natural-language queries:
   "is my board analysis done yet?", "what did the retrospective say?"
4. **Crash recovery:** on bot startup, any job still marked `running` is set to `failed`
   with the note "interrupted by restart" — no automatic retry.
5. **Result text stored in full** so the user can ask "show me the board results" even
   after the Telegram message has scrolled away.
6. **No new Python dependencies** — uses the existing `aiosqlite` / SQLite setup.

---

## Implementation

**New file:** `drbot/memory/background_jobs.py`
**Modified files:** `drbot/memory/database.py`, `drbot/agents/background.py`,
`drbot/bot/handlers.py`, `drbot/ai/tool_registry.py`

### Schema (`drbot/memory/database.py`)

```sql
CREATE TABLE IF NOT EXISTS background_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    job_type    TEXT NOT NULL,       -- 'board' | 'retrospective' | 'research'
    status      TEXT NOT NULL,       -- 'queued' | 'running' | 'done' | 'failed'
    input_text  TEXT,
    result_text TEXT,
    created_at  TEXT NOT NULL,
    completed_at TEXT
);
```

### `BackgroundJobStore` (`drbot/memory/background_jobs.py`)

Methods: `create()`, `set_running()`, `set_done()`, `set_failed()`,
`list_recent(user_id, limit=10)`, `get(job_id)`.

On startup, call `store.mark_interrupted()` to flip `running` → `failed`.

### `/jobs` handler

```
/jobs
→ 📋 Recent background jobs:
  #42 board        ✅ done     Started: 14:32  "The board identified three key risks..."
  #41 retrospective ⏳ running  Started: 14:30
  #40 research     ❌ failed   Started: 13:55  interrupted by restart
```

### Tool schema (`tool_registry.py`)

```json
{
  "name": "list_background_jobs",
  "description": "List recent background tasks and their status/results.",
  "input_schema": {
    "type": "object",
    "properties": {
      "status_filter": {
        "type": "string",
        "enum": ["all", "done", "running", "failed"],
        "description": "Filter by job status. Defaults to 'all'."
      }
    }
  }
}
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| Start `/board` task | Row inserted with status `queued` → `running` |
| Board completes | Row updated to `done`; result stored |
| `/jobs` | Shows recent jobs with status badges |
| "Is my board done yet?" | Claude calls `list_background_jobs`; returns status |
| Bot restarts during running job | Job flipped to `failed` with restart note |
| "What did the retrospective say?" | Claude returns `result_text` from DB |

---

## Out of Scope

- Automatic retry of failed jobs
- Job cancellation (no `asyncio.Task` handle is stored)
- Claude Agent SDK subagents (Phase 7, Step 3)
