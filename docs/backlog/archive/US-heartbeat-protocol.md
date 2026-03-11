# User Story: Formal Heartbeat Protocol — 9-Step Work Procedure

**Status:** ⏸️ Out of scope (relay removed) — archived 2026-03-11
**Priority:** ⭐⭐⭐ High
**Effort:** Medium
**Source:** [docs/ideas.md §3](../../ideas.md)

**Note:** This PBI assumes relay tasks (cowork ↔ Remy). Relay was explicitly removed from the solution. Revisit only if relay (or an equivalent task-assignment channel) is reintroduced.

## Summary

As Dale, I want Remy's task handling to follow a formal, predictable 9-step protocol so that tasks are always claimed atomically, context is always read before acting, and results are always posted — reducing zombie tasks and silent failures.

---

## Background

Remy's `CLAUDE.md` defines a task loop informally (check messages → claim → work → update). But in practice:

- Tasks can be claimed without conflict detection (two sessions could claim the same task)
- Context loading (related messages, parent goals) is ad-hoc
- Delegation of subtasks lacks `parent_id` linking
- No "always comment before exiting" enforcement

The 9-step heartbeat protocol addresses all of these with explicit rules:

1. **Identity** — Verify agent identity
2. **Approvals** — Handle any pending approval events first
3. **Assignments** — Query `pending` + `in_progress` tasks
4. **Pick Work** — Prioritise `in_progress`; skip blocked tasks where Remy's comment is the most recent (dedup — see `US-blocked-task-dedup.md`)
5. **Checkout** — Atomically claim; 409 conflict = skip, never retry
6. **Context** — Read task detail + related messages + parent goal
7. **Do Work** — Execute with tools
8. **Update Status** — Mark `done` / `needs_clarification` with notes; include session date
9. **Delegate** — Create subtasks linked to parent `task_id` and `goal_id`

---

## Acceptance Criteria

1. **Atomic claim guard.** Claiming a task (status="in_progress") is the first action taken on any task. If the task is already `in_progress` (claimed by another session), Remy skips it and logs a warning.
2. **In-progress first.** When multiple tasks are pending, Remy resumes any previously claimed `in_progress` tasks before picking new `pending` ones.
3. **Blocked dedup applied.** Blocked tasks where Remy's last message/note is the most recent entry are skipped without re-pinging (see `US-blocked-task-dedup.md`).
4. **Context loading.** Before doing work, Remy reads: (a) the full task description + notes, (b) any related messages in the same thread, (c) linked goal description if `goal_id` is set.
5. **Result always posted.** Every completed task gets a result recorded. Every blocked task gets status set to needs_clarification with notes, plus a message to the requester.
6. **Session date in result.** The `result` or `notes` field includes the ISO date (e.g. `"2026-03-08"`).
7. **CLAUDE.md updated.** The session instructions document the formal 9-step loop.

---

## Implementation

### CLAUDE.md update

Replace the informal task loop with a numbered 9-step checklist. Each step is a single sentence with the tool call or rule.

### Task client

Add `claim_task(task_id) -> bool` that:
1. Fetches the task status before claiming
2. If already `in_progress`, returns `False` (conflict guard)
3. Otherwise updates to `in_progress` and returns `True`

### Task executor

Update the task executor to:
- Sort results: `in_progress` first, then `pending`
- Filter out blocked tasks where Remy's last activity is the most recent comment

### CLAUDE.md

Document the 9-step protocol as the standard heartbeat loop. The model follows it verbatim at the start of each session.

---

## Files Affected

| File | Change |
|------|--------|
| `CLAUDE.md` | Add formal 9-step heartbeat protocol |
| Task client | Add `claim_task()` conflict guard |
| Task executor | Sort tasks (in_progress first); apply dedup filter |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Single pending task | Claimed, worked, result posted |
| Task already `in_progress` | Skipped; warning logged |
| Multiple tasks: 1 in-progress, 2 pending | in_progress task handled first |
| Blocked task, Remy's last message is most recent | Skipped (dedup); no re-ping |
| Task with goal_id | Goal description loaded before work starts |
| Work fails mid-task | Status set to needs_clarification + message sent to requester |

---

## Out of Scope

- Board-level escalation chain (separate US)
- Delegation / subtask creation API (parent_id linking)
- Approval gate handling (see `US-approval-gates.md`)
