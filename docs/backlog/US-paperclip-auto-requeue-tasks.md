# User Story: Auto-Requeue Stuck Relay Tasks (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐ Medium
**Effort:** Low
**Source:** [docs/paperclip-ideas.md §10](../paperclip-ideas.md)

## Summary

As Dale, I want relay tasks that Remy claims but fails to complete (due to API errors, crashes, or timeouts) to automatically revert to `pending` after a configurable timeout — so that cowork can reassign them or Remy picks them up again on the next session, rather than leaving them zombie-stuck in `in_progress` forever.

---

## Background

When Remy claims a relay task (`status=in_progress`) but the session crashes, hits an API error, or times out, the task stays `in_progress` indefinitely. Cowork has no way to know the task is stuck, and Remy's next session may skip it (already claimed). This creates "zombie tasks" that pile up and block the relay queue.

Paperclip handles this with: configurable timeout + auto-revert to `pending` + retry count.

---

## Acceptance Criteria

1. **Timeout config.** `RELAY_TASK_TIMEOUT_MINUTES` in `.env` (default: 60). Tasks claimed by Remy that remain `in_progress` longer than this threshold are candidates for requeue.
2. **Requeue on startup.** At session start (after claiming tasks), Remy checks for `in_progress` tasks it owns that are older than the timeout and reverts them to `pending` with a note: `"Auto-requeued after {N} minutes — previous session likely crashed."`
3. **Retry count.** Each requeue increments a `retry_count` field on the task (relay DB schema change). After 3 retries, the task is moved to `needs_clarification` with note: `"Failed 3 times — manual intervention required."`
4. **Requeue logged.** A `WARNING` log line is emitted for each requeued task.
5. **Message to cowork.** On requeue after 3 retries, Remy posts a relay message to cowork: `"Task {task_id} has failed 3 times and needs manual review."`
6. **No false requeues.** Tasks actively being worked on in the current session are not requeued (guarded by session start timing: only requeue tasks claimed before this session started).

---

## Implementation

### Relay DB schema (`relay_mcp/server.py`)

Add `retry_count INTEGER DEFAULT 0` and `claimed_at TIMESTAMP` to the `tasks` table.

Update `relay_update_task` to set `claimed_at = NOW()` when `status` changes to `in_progress`.

### Relay client (`remy/relay/client.py`)

Add `requeue_stale_tasks(timeout_minutes: int) -> list[str]`:

```python
async def requeue_stale_tasks(self, timeout_minutes: int = 60) -> list[str]:
    """
    Find tasks in `in_progress` assigned to remy, claimed more than
    timeout_minutes ago. Revert to pending or needs_clarification.
    Returns list of requeued task IDs.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    stale = await self._find_stale_tasks(cutoff)
    requeued = []
    for task in stale:
        retry_count = task.get("retry_count", 0) + 1
        if retry_count >= 3:
            await self.update_task(
                task["id"],
                status="needs_clarification",
                notes=f"Failed {retry_count} times — manual intervention required.",
                retry_count=retry_count,
            )
        else:
            await self.update_task(
                task["id"],
                status="pending",
                notes=f"Auto-requeued after {timeout_minutes} minutes — previous session likely crashed.",
                retry_count=retry_count,
            )
        requeued.append(task["id"])
    return requeued
```

### Session start (`CLAUDE.md` / relay tool executor)

Call `requeue_stale_tasks()` as the first relay operation at session start, before checking for new tasks.

### Relay MCP server (`relay_mcp/server.py`)

- Add `retry_count` and `claimed_at` columns to tasks table (migration)
- Update `relay_update_task` to set `claimed_at` when transitioning to `in_progress`

---

## Files Affected

| File | Change |
|------|--------|
| `relay_mcp/server.py` | Schema: add `retry_count`, `claimed_at`; set `claimed_at` on in_progress |
| `remy/relay/client.py` | Add `requeue_stale_tasks()` |
| `remy/ai/tools/relay.py` | Call `requeue_stale_tasks()` at session start |
| `CLAUDE.md` | Document requeue step in heartbeat loop |
| `.env.example` | Document `RELAY_TASK_TIMEOUT_MINUTES` |
| `remy/config.py` | Add `relay_task_timeout_minutes: int = 60` |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Task in_progress < timeout | Not requeued |
| Task in_progress > timeout, retry_count=0 | Reverted to pending; retry_count=1; note added |
| Task in_progress > timeout, retry_count=2 | Moved to needs_clarification; retry_count=3; cowork notified |
| Task claimed in current session (< timeout ago) | Not requeued (too recent) |
| Multiple stale tasks | All requeued; all logged |
| No stale tasks | No-op; no log spam |

---

## Out of Scope

- Exponential backoff on retry (not needed at this scale)
- Cross-agent requeue (cowork's stale tasks are cowork's problem)
- Retry count reset on manual intervention (acceptable edge case)
