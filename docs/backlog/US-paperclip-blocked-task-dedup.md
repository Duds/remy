# User Story: Blocked-Task Deduplication (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐ Medium
**Effort:** Low
**Source:** [docs/paperclip-ideas.md §4](../paperclip-ideas.md)

## Summary

As Dale, I want Remy to stop re-pinging cowork about tasks that are already blocked waiting for cowork's response — so that the relay thread doesn't fill with duplicate "still blocked" messages and budget isn't wasted on unnecessary LLM calls.

---

## Background

When Remy sets a relay task to `needs_clarification`, it posts a message to cowork explaining what's missing. On the next session, Remy's heartbeat loop sees the task is still `needs_clarification` and — without a dedup rule — re-posts the same "still blocked" message. This:

1. Wastes token budget (LLM call + message)
2. Creates noise in cowork's inbox
3. May cause cowork to re-evaluate already-seen context

Paperclip's fix: when scanning assigned tasks, **skip** a blocked task entirely if **your own prior comment was the last update**. Only re-engage if cowork has responded since Remy's last message.

---

## Acceptance Criteria

1. **Last-activity check.** When Remy loads `needs_clarification` tasks at session start, it checks: "Was my last relay message about this task more recent than cowork's last message on this task?"
2. **Skip if Remy is the last speaker.** If yes → skip the task entirely (no LLM call, no re-ping).
3. **Re-engage if cowork responded.** If cowork has posted a message or note on this task since Remy's last update → process the task normally.
4. **Skip logged.** A `DEBUG` log line records the skip: `"Skipping task {task_id} (needs_clarification, Remy is last speaker)"`
5. **No infinite skip.** If the task has been skipped for >7 days without cowork response, Remy sends one summary ping: "Task {task_id} has been blocked for 7 days — still waiting on your input."
6. **Session-end note.** Any skipped tasks are listed in the session-end audit note (see CLAUDE.md addendum).

---

## Implementation

### Relay client (`remy/relay/client.py`)

Add `get_task_last_messages(task_id) -> list[dict]` to fetch messages in the task's thread, ordered by timestamp.

Add `remy_is_last_speaker(task_id) -> bool`:

```python
async def remy_is_last_speaker(self, task_id: str) -> bool:
    messages = await self.get_task_messages(task_id)
    if not messages:
        return False
    return messages[-1]["from_agent"] == "remy"
```

### Relay tool executor (`remy/ai/tools/relay.py`)

In the task-listing executor, after fetching `needs_clarification` tasks, filter out tasks where `remy_is_last_speaker()` returns `True`.

### 7-day stale ping (`remy/scheduler/proactive.py` or heartbeat)

Check `needs_clarification` tasks older than 7 days where Remy is last speaker. Send one stale ping per task if not already sent this week. Track via a memory fact (e.g. `"stale_ping_sent:{task_id}:{week}"`) to avoid re-pinging.

---

## Files Affected

| File | Change |
|------|--------|
| `remy/relay/client.py` | Add `remy_is_last_speaker()` helper |
| `remy/ai/tools/relay.py` | Filter blocked tasks where Remy is last speaker |
| `remy/scheduler/proactive.py` | Add 7-day stale task ping |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Task is `needs_clarification`, Remy last spoke | Skipped; logged as DEBUG |
| Task is `needs_clarification`, cowork responded since | Task processed normally |
| Task skipped for 7+ days, no cowork response | One stale ping sent; tracked to avoid repeats |
| Stale ping already sent this week | No re-ping |
| Task is `pending` (not blocked) | Normal processing; dedup rule not applied |

---

## Out of Scope

- Tracking cowork's response at the relay DB level (not currently available)
- Auto-escalation after N days (nice-to-have; separate US)
