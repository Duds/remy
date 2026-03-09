# Gmail Audit Skill

## When to use this skill

Apply this skill when executing a `gmail_audit` relay task.  These tasks ask you to research, count, or summarise emails — no destructive action is taken.

---

## Research approach

1. **Run the provided query** using `gmail_search`.
2. **Count the results**: Always report total count, not just samples.
3. **Sample for quality**: Read up to 10 subject lines / senders to characterise the batch.
4. **Check date range**: Identify oldest and newest email in the result.

---

## Report structure

Your `result` in `relay_update_task` should follow this format:

```
Query: <exact query used>
Total emails found: <N>
Date range: <oldest> – <newest>
Top senders: <list up to 5>
Sample subjects: <list up to 5>
Recommendation: <label / trash / keep / follow-up>
```

Keep the report concise — one section per point, no prose waffle.

---

## What to look for

| Signal | Meaning |
|---|---|
| Newsletters / marketing from same sender >3 times | Suggest unsubscribe or filter rule |
| Emails >90 days old with no reply | Likely archivable |
| Calendar notifications, Jira/GitHub digests | Candidate for `gmail_delete` |
| Emails from known people | Do NOT suggest deletion — flag for human review |

---

## Output example

```
Query: from:github.com older_than:30d
Total emails found: 147
Date range: 2025-08-01 – 2026-02-28
Top senders: notifications@github.com (147)
Sample subjects: "[PR #42] Update README", "[Issue #88] Bug: …"
Recommendation: Trash — all automated GitHub notifications, no action required.
```

---

## Result format

```
relay_update_task(
    task_id="...",
    status="done",
    result="<structured report above>"
)
```
