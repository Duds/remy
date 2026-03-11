# User Story: Auto-Requeue Stuck Tasks

**Status:** ⏸️ Out of scope (relay removed) — archived 2026-03-11
**Priority:** ⭐⭐ Medium
**Effort:** Low
**Source:** [docs/ideas.md §10](../../ideas.md)

**Note:** This PBI applies to relay tasks (claim, in_progress, task assignor). Relay was explicitly removed from the solution. Revisit only if relay (or an equivalent task-assignment channel) is reintroduced.

## Summary

As Dale, I want tasks that Remy claims but fails to complete (due to API errors, crashes, or timeouts) to automatically revert to `pending` after a configurable timeout — so that the task assignor can reassign them or Remy picks them up again on the next session, rather than leaving them zombie-stuck in `in_progress` forever.

---

## Background

When Remy claims a task (`status=in_progress`) but the session crashes, hits an API error, or times out, the task stays `in_progress` indefinitely. The task assignor has no way to know the task is stuck, and Remy's next session may skip it (already claimed). This creates "zombie tasks" that pile up and block the task queue.

A typical approach: configurable timeout + auto-revert to `pending` + retry count.

---

## Acceptance Criteria

1. **Timeout config.** `TASK_TIMEOUT_MINUTES` in `.env` (default: 60). Tasks claimed by Remy that remain `in_progress` longer than this threshold are candidates for requeue.
2. **Requeue on startup.** At session start (after claiming tasks), Remy checks for `in_progress` tasks it owns that are older than the timeout and reverts them to `pending` with a note: `"Auto-requeued after {N} minutes — previous session likely crashed."`
3. **Retry count.** Each requeue increments a `retry_count` field on the task (task store schema change). After 3 retries, the task is moved to `needs_clarification` with note: `"Failed 3 times — manual intervention required."`
4. **Requeue logged.** A `WARNING` log line is emitted for each requeued task.
5. **Notification to task assignor.** On requeue after 3 retries, Remy notifies the task assignor: `"Task {task_id} has failed 3 times and needs manual review."`
6. **No false requeues.** Tasks actively being worked on in the current session are not requeued (guarded by session start timing: only requeue tasks claimed before this session started).

---

## Implementation

### Task store schema

Add `retry_count INTEGER DEFAULT 0` and `claimed_at TIMESTAMP` to the `tasks` table.

Update the task update logic to set `claimed_at = NOW()` when `status` changes to `in_progress`.

### Task client

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

### Session start

Call `requeue_stale_tasks()` at session start, before checking for new tasks.

### Task store

- Add `retry_count` and `claimed_at` columns to tasks table (migration)
- Update task status logic to set `claimed_at` when transitioning to `in_progress`

---

## Files Affected

| File | Change |
|------|--------|
| Task store / DB schema | Add `retry_count`, `claimed_at`; set `claimed_at` on in_progress |
| Task client | Add `requeue_stale_tasks()` |
| Session start / heartbeat | Call `requeue_stale_tasks()` at session start |
| `.env.example` | Document `TASK_TIMEOUT_MINUTES` |
| `remy/config.py` | Add `task_timeout_minutes: int = 60` |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Task in_progress < timeout | Not requeued |
| Task in_progress > timeout, retry_count=0 | Reverted to pending; retry_count=1; note added |
| Task in_progress > timeout, retry_count=2 | Moved to needs_clarification; retry_count=3; task assignor notified |
| Task claimed in current session (< timeout ago) | Not requeued (too recent) |
| Multiple stale tasks | All requeued; all logged |
| No stale tasks | No-op; no log spam |

---

## Out of Scope

- Exponential backoff on retry (not needed at this scale)
- Cross-agent requeue (other agents' stale tasks are their own concern)
- Retry count reset on manual intervention (acceptable edge case)
