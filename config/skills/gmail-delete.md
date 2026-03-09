# Gmail Delete Skill

## When to use this skill

Apply this skill when executing a `gmail_delete` relay task.  The task `params` will contain:
- `query` — Gmail search query identifying emails to trash

Trashing is irreversible in practice (Gmail empties trash after 30 days).

---

## Mandatory pre-check

**Always count before deleting.**

Run the query with `gmail_search` first:
- 0–10 emails: proceed directly.
- 11–50 emails: include the count in the task result; proceed.
- **Over 50 emails**: set `needs_clarification` and include the count + sample subjects.  Do **not** proceed until confirmed.

---

## Safe-to-delete signals

Emails matching these patterns are almost always safe to trash:
- Automated notifications: GitHub, Jira, Trello, LinkedIn, Twitter/X
- Newsletters / marketing (unsubscribe headers present)
- Password reset links >30 days old
- Calendar event confirmations already accepted

---

## Do NOT trash without explicit approval

- Emails from named individuals (family, colleagues, clients)
- Receipts and invoices
- Any email with an attachment not yet downloaded
- Emails < 7 days old (might still be actionable)

---

## Execution

- Trash in batches of up to 50.
- Report exact count trashed in the result.
- If any emails fail (API error), report the count and stop — do not retry blindly.

---

## Result format

```
relay_update_task(
    task_id="...",
    status="done",
    result="Trashed 87 emails matching query 'from:notifications@linkedin.com older_than:14d'. 0 errors."
)
```

---

## Approval gates

> Bulk delete (>50 emails) always requires explicit confirmation before execution.  See CLAUDE.md approval gate rules.
