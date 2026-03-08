# User Story: Formal Heartbeat Protocol — 9-Step Work Procedure (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐⭐ High
**Effort:** Medium
**Source:** [docs/paperclip-ideas.md §3](../paperclip-ideas.md)

## Summary

As Dale, I want Remy's relay task handling to follow a formal, predictable 9-step protocol so that tasks are always claimed atomically, context is always read before acting, and results are always posted — reducing zombie tasks and silent failures.

---

## Background

Remy's `CLAUDE.md` defines a task loop informally (check messages → claim → work → update). But in practice:

- Tasks can be claimed without conflict detection (two sessions could claim the same task)
- Context loading (related messages, parent goals) is ad-hoc
- Delegation of subtasks lacks `parent_id` linking
- No "always comment before exiting" enforcement

Paperclip's 9-step heartbeat protocol addresses all of these with explicit rules:

1. **Identity** — Verify agent identity
2. **Approvals** — Handle any pending approval events first
3. **Assignments** — Query `pending` + `in_progress` tasks
4. **Pick Work** — Prioritise `in_progress`; skip blocked tasks where Remy's comment is the most recent (dedup — see `US-paperclip-blocked-task-dedup.md`)
5. **Checkout** — Atomically claim; 409 conflict = skip, never retry
6. **Context** — Read task detail + related messages + parent goal
7. **Do Work** — Execute with tools
8. **Update Status** — Mark `done` / `needs_clarification` with notes; include session date
9. **Delegate** — Create subtasks linked to parent `task_id` and `goal_id`

---

## Acceptance Criteria

1. **Atomic claim guard.** `relay_update_task(status="in_progress")` is the first action taken on any task. If the task is already `in_progress` (claimed by another session), Remy skips it and logs a warning.
2. **In-progress first.** When multiple tasks are pending, Remy resumes any previously claimed `in_progress` tasks before picking new `pending` ones.
3. **Blocked dedup applied.** Blocked tasks where Remy's last message/note is the most recent entry are skipped without re-pinging (see `US-paperclip-blocked-task-dedup.md`).
4. **Context loading.** Before doing work, Remy reads: (a) the full task description + notes, (b) any relay messages in the same thread, (c) linked goal description if `goal_id` is set.
5. **Result always posted.** Every completed task results in a `relay_update_task(status="done", result=...)` call. Every blocked task results in `relay_update_task(status="needs_clarification", notes=...)` + a `relay_post_message` to cowork.
6. **Session date in result.** The `result` or `notes` field includes the ISO date (e.g. `"2026-03-08"`).
7. **CLAUDE.md updated.** The session instructions document the formal 9-step loop.

---

## Implementation

### CLAUDE.md update

Replace the informal task loop with a numbered 9-step checklist. Each step is a single sentence with the tool call or rule.

### Relay client (`remy/relay/client.py`)

Add `claim_task(task_id) -> bool` that:
1. Fetches the task status before claiming
2. If already `in_progress`, returns `False` (conflict guard)
3. Otherwise updates to `in_progress` and returns `True`

```python
async def claim_task(self, task_id: str) -> bool:
    task = await self.get_task(task_id)
    if task and task["status"] == "in_progress":
        logger.warning(f"Task {task_id} already in_progress — skipping (conflict guard)")
        return False
    await self.update_task(task_id, status="in_progress")
    return True
```

### Relay tool executor (`remy/ai/tools/relay.py`)

Update the `relay_get_tasks` executor to:
- Sort results: `in_progress` first, then `pending`
- Filter out blocked tasks where Remy's last activity is the most recent comment

### CLAUDE.md

Document the 9-step protocol as the standard heartbeat loop. The model follows it verbatim at the start of each session.

---

## Files Affected

| File | Change |
|------|--------|
| `CLAUDE.md` | Add formal 9-step heartbeat protocol |
| `remy/relay/client.py` | Add `claim_task()` conflict guard |
| `remy/ai/tools/relay.py` | Sort tasks (in_progress first); apply dedup filter |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Single pending task | Claimed, worked, result posted |
| Task already `in_progress` | Skipped; warning logged |
| Multiple tasks: 1 in-progress, 2 pending | in_progress task handled first |
| Blocked task, Remy's last message is most recent | Skipped (dedup); no re-ping |
| Task with goal_id | Goal description loaded before work starts |
| Work fails mid-task | Status set to `needs_clarification` + message sent to cowork |

---

## Out of Scope

- Board-level escalation chain (separate US)
- Delegation / subtask creation API (relay doesn't yet support `parent_id`)
- Approval gate handling (see `US-paperclip-approval-gates.md`)
