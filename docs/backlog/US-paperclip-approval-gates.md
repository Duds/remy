# User Story: Approval Gates for Bulk / High-Stakes Actions (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐⭐ High
**Effort:** Medium
**Source:** [docs/paperclip-ideas.md §6](../paperclip-ideas.md)

## Summary

As Dale, I want Remy to ask for my explicit confirmation before executing bulk or irreversible actions (mass Gmail deletes, bulk label operations, large file writes) — via a Telegram inline button — so that I never accidentally lose emails or files due to a misunderstood instruction.

---

## Background

Remy currently executes Gmail deletes and label operations immediately upon instruction. There is no confirmation step for bulk actions. The existing inline button infrastructure (`remy/bot/handlers/`) supports inline keyboards and callbacks, so this is a natural extension.

Paperclip implements approval gates as: agent POSTs an approval request → waits for a board member to approve/reject → heartbeat is re-triggered with the approval result.

For Remy, the simpler equivalent is: Remy drafts the action → sends a Telegram inline button ("✅ Confirm / ❌ Cancel") → waits for Dale's tap → executes or aborts.

---

## Acceptance Criteria

1. **Gate triggers.** The following actions require approval before execution:
   - Gmail bulk delete (>5 emails matched by query)
   - Gmail bulk label (>10 emails matched by query)
   - Any `gmail_delete` relay task from cowork (always)
   - File write operations >10 KB (configurable)
2. **Confirmation message.** Remy sends a human-readable summary of the action with counts: "About to trash 47 emails matching 'LinkedIn notifications'. Confirm?"
3. **Inline buttons.** Two buttons: `✅ Confirm` and `❌ Cancel`.
4. **Timeout.** If Dale doesn't respond within 5 minutes, Remy auto-cancels and posts: "Action cancelled — no response within 5 minutes."
5. **Execution on confirm.** On `✅ Confirm`, Remy executes the action and posts a result summary.
6. **Abort on cancel.** On `❌ Cancel`, Remy posts "Action cancelled." and does not execute.
7. **Relay task integration.** For `gmail_delete` relay tasks from cowork, after Dale confirms, Remy marks the task `done` with the result. On cancel, marks `needs_clarification` with note "Dale declined the bulk delete."
8. **Single-email operations exempt.** Actions affecting ≤5 emails (or ≤10 for labels) proceed without a gate.

---

## Implementation

### Approval helper (`remy/bot/approval.py` — new file)

```python
async def request_approval(
    bot: Bot,
    chat_id: int,
    summary: str,
    action_fn: Callable,
    timeout_seconds: int = 300,
) -> bool:
    """
    Send an inline confirmation message. Returns True if approved, False if cancelled/timed out.
    """
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data="approve:..."),
        InlineKeyboardButton("❌ Cancel",  callback_data="cancel:..."),
    ]])
    msg = await bot.send_message(chat_id, summary, reply_markup=keyboard)
    # Wait for callback or timeout
    ...
```

### Gmail tool executor (`remy/ai/tools/email.py`)

Before executing a bulk delete or label, call `len(matched_emails)`. If above threshold, call `request_approval()` instead of executing immediately.

### Relay task handler (`remy/ai/tools/relay.py`)

For `gmail_delete` task type, always route through `request_approval()`.

### Callback handler (`remy/bot/handlers/`)

Register `approve:*` and `cancel:*` callback handlers to resolve the pending approval futures.

---

## Files Affected

| File | Change |
|------|--------|
| `remy/bot/approval.py` | New: approval gate helper |
| `remy/ai/tools/email.py` | Add threshold check + approval call |
| `remy/ai/tools/relay.py` | Route gmail_delete tasks through approval |
| `remy/bot/handlers/` | Register approval callback handlers |
| `remy/config.py` | Add `APPROVAL_GMAIL_DELETE_THRESHOLD` (default: 5) and `APPROVAL_GMAIL_LABEL_THRESHOLD` (default: 10) |
| `.env.example` | Document new threshold settings |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Delete 3 emails | No gate; executes immediately |
| Delete 47 emails | Gate shown; waits for confirmation |
| Dale taps ✅ | Action executes; result posted |
| Dale taps ❌ | Action cancelled; "Action cancelled." posted |
| No response for 5 min | Auto-cancel; "Action cancelled — no response." |
| Relay `gmail_delete` task (any size) | Gate always shown; result feeds back to task status |
| Label 8 emails | No gate (below label threshold of 10) |
| Label 15 emails | Gate shown |

---

## Out of Scope

- Approval chains (multiple approvers)
- Paperclip-style board member approval (Remy is single-user)
- Approval logs persisted to relay notes (nice-to-have, not blocking)
