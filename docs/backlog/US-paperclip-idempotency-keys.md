# User Story: Idempotency Keys for Cron / Scheduled Jobs (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐ Medium
**Effort:** Low
**Source:** [docs/paperclip-ideas.md §9](../paperclip-ideas.md)

## Summary

As Dale, I want Remy's scheduled (cron) jobs to be idempotent — so that if APScheduler fires a job twice due to a crash-at-the-wrong-moment or a startup reconciliation race, the job runs exactly once and I don't receive duplicate morning briefings or double-fired daily reminders.

---

## Background

Remy's proactive scheduler (`remy/scheduler/proactive.py`) uses APScheduler with `misfire_grace_time` to reconcile missed jobs on startup. In rare cases — process crash mid-job, Docker restart, or two overlapping containers — a daily job (morning briefing, evening check-in) can fire twice.

The existing `background_jobs` table tracks long-running jobs by `job_type`, but not with a per-day idempotency key. Adding a key of the form `"{job_type}:{YYYY-MM-DD}"` would prevent double execution.

Paperclip calls this pattern `idempotencyKey` on recurring task creation.

---

## Acceptance Criteria

1. **Idempotency key format.** Every scheduled job that should run at most once per day uses a key: `"{job_type}:{YYYY-MM-DD}"` (e.g. `"morning_briefing:2026-03-08"`).
2. **Check before run.** Before executing a daily job, Remy checks the `background_jobs` table for an existing row with the same idempotency key and `status` in `("running", "done")`.
3. **Skip if exists.** If a matching row exists, the job is skipped and a `DEBUG` log line is emitted: `"Skipping {job_type} — already ran today (idempotency key: {key})"`
4. **Insert before run.** If no matching row exists, insert a `background_jobs` row with the idempotency key and `status="running"` **before** executing the job. This prevents a second concurrent invocation from racing past the check.
5. **Mark done after run.** On successful completion, update the row to `status="done"`.
6. **Mark failed on error.** On unhandled exception, update the row to `status="error"` with the exception message. A failed job is not retried automatically on the same day (prevents runaway errors); Dale can manually trigger via Telegram.
7. **Affected jobs.** At minimum: `morning_briefing`, `afternoon_checkin`, `evening_checkin`. One-time `DateTrigger` automations already handle this via row deletion (see `US-automation-double-fire.md`).

---

## Implementation

### Background jobs store (`remy/memory/background_jobs.py`)

Add a `get_by_idempotency_key(key: str)` query:

```python
async def get_by_idempotency_key(self, key: str) -> dict | None:
    row = await self.db.fetchone(
        "SELECT * FROM background_jobs WHERE idempotency_key = ?", (key,)
    )
    return dict(row) if row else None
```

Add `idempotency_key TEXT UNIQUE` column to the `background_jobs` table (migration).

### Proactive scheduler (`remy/scheduler/proactive.py`)

Wrap each daily job with an idempotency guard:

```python
async def _run_daily_job(self, job_type: str, coro):
    today = date.today().isoformat()
    key = f"{job_type}:{today}"
    existing = await self._bg_jobs.get_by_idempotency_key(key)
    if existing and existing["status"] in ("running", "done"):
        logger.debug(f"Skipping {job_type} — already ran today (key: {key})")
        return
    job_id = await self._bg_jobs.create(job_type=job_type, idempotency_key=key, status="running")
    try:
        await coro
        await self._bg_jobs.update(job_id, status="done")
    except Exception as e:
        await self._bg_jobs.update(job_id, status="error", error=str(e))
        raise
```

### DB migration (`remy/memory/database.py`)

Add `idempotency_key TEXT UNIQUE` to `background_jobs` table. Nullable (existing rows unaffected).

---

## Files Affected

| File | Change |
|------|--------|
| `remy/memory/database.py` | Add `idempotency_key` column migration |
| `remy/memory/background_jobs.py` | Add `get_by_idempotency_key()` |
| `remy/scheduler/proactive.py` | Wrap daily jobs with idempotency guard |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Morning briefing runs normally | Row inserted (running → done); message sent |
| Morning briefing called again same day | Existing `done` row found; job skipped |
| Two concurrent invocations | First inserts row; second finds row and skips |
| Job fails | Row updated to `error`; no retry today |
| New day | New idempotency key (`YYYY-MM-DD` different); job runs |
| One-time automation | Uses existing delete-before-fire pattern; unaffected |

---

## Out of Scope

- Idempotency for relay task creation (separate concern)
- Per-week or per-hour idempotency keys (only daily jobs need this now)
- Manual retry of `error` status jobs via Telegram command (nice-to-have, separate US)
