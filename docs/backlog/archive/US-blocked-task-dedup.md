# User Story: Blocked-Task Deduplication

**Status:** ⏸️ Out of scope (relay removed) — archived 2026-03-11
**Priority:** ⭐⭐ Medium
**Effort:** Low
**Source:** [docs/ideas.md §4](../../ideas.md)

**Note:** This PBI applies to relay tasks (cowork ↔ Remy). Relay was explicitly removed from the solution; there is no relay task store or message thread in Remy. Revisit only if relay (or an equivalent task-assignment channel) is reintroduced.

## Summary

As Dale, I want Remy to stop re-pinging about tasks that are already blocked waiting for a response — so that the task thread doesn't fill with duplicate "still blocked" messages and budget isn't wasted on unnecessary LLM calls.

---

## Background

When Remy sets a task to `needs_clarification`, it posts a message explaining what's missing. On the next session, Remy's heartbeat loop sees the task is still `needs_clarification` and — without a dedup rule — re-posts the same "still blocked" message. This:

1. Wastes token budget (LLM call + message)
2. Creates noise in the requester's inbox
3. May cause the requester to re-evaluate already-seen context

The fix: when scanning assigned tasks, **skip** a blocked task entirely if **your own prior comment was the last update**. Only re-engage if the requester has responded since Remy's last message.

---

## Acceptance Criteria

1. **Last-activity check.** When Remy loads `needs_clarification` tasks at session start, it checks: "Was my last message about this task more recent than the requester's last message on this task?"
2. **Skip if Remy is the last speaker.** If yes → skip the task entirely (no LLM call, no re-ping).
3. **Re-engage if requester responded.** If the requester has posted a message or note on this task since Remy's last update → process the task normally.
4. **Skip logged.** A `DEBUG` log line records the skip: `"Skipping task {task_id} (needs_clarification, Remy is last speaker)"`
5. **No infinite skip.** If the task has been skipped for >7 days without requester response, Remy sends one summary ping: "Task {task_id} has been blocked for 7 days — still waiting on your input."
6. **Session-end note.** Any skipped tasks are listed in the session-end audit note (see CLAUDE.md addendum).

---

## Implementation

### Task client

Add `get_task_last_messages(task_id) -> list[dict]` to fetch messages in the task's thread, ordered by timestamp.

Add `remy_is_last_speaker(task_id) -> bool`:

```python
async def remy_is_last_speaker(self, task_id: str) -> bool:
    messages = await self.get_task_messages(task_id)
    if not messages:
        return False
    return messages[-1]["from_agent"] == "remy"
```

### Task executor

In the task-listing executor, after fetching `needs_clarification` tasks, filter out tasks where `remy_is_last_speaker()` returns `True`.

### 7-day stale ping (`remy/scheduler/proactive.py` or heartbeat)

Check `needs_clarification` tasks older than 7 days where Remy is last speaker. Send one stale ping per task if not already sent this week. Track via memory to avoid re-pinging.

---

## Files Affected

| File | Change |
|------|--------|
| Task client | Add `remy_is_last_speaker()` helper |
| Task executor | Filter blocked tasks where Remy is last speaker |
| `remy/scheduler/proactive.py` | Add 7-day stale task ping |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Task is `needs_clarification`, Remy last spoke | Skipped; logged as DEBUG |
| Task is `needs_clarification`, requester responded since | Task processed normally |
| Task skipped for 7+ days, no requester response | One stale ping sent; tracked to avoid repeats |
| Stale ping already sent this week | No re-ping |
| Task is `pending` (not blocked) | Normal processing; dedup rule not applied |

---

## Out of Scope

- Tracking requester response at the task DB level (not currently available)
- Auto-escalation after N days (nice-to-have; separate US)
