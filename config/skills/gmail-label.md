# Gmail Label Skill

## When to use this skill

Apply this skill when executing a `gmail_label` relay task.  The task `params` will contain:
- `query` — Gmail search query identifying the emails to label
- `label` — The label to apply (must already exist in Gmail unless creation is approved)

---

## Before you start

1. **Resolve the label**: Search Gmail for the exact label name using the Gmail labels list tool.
   - If the label does not exist, do **not** create it silently — flag with `needs_clarification`.
   - If a close match exists (e.g. "4-Personal" for "4-Personal & Family"), note it and ask.

2. **Count the scope**: Run the query with `gmail_search` first to count matching emails.
   - Under 10 emails: proceed directly.
   - 10–50 emails: include the count in the task result; proceed.
   - Over 50 emails: surface count via `needs_clarification` and await confirmation before applying.

---

## Applying the label

- Use the `gmail_label` tool with the exact resolved label name.
- Apply in batches of up to 50 to avoid timeouts.
- Record the exact count applied in the task result.

---

## Label naming conventions

Gmail labels in this account follow a numbered hierarchy:
```
1-Urgent
2-Action Required
3-Work
4-Personal & Family
5-Hobbies & Interests
6-Health & Wellness
7-Finance
8-Reference
9-Archive
```

When the task specifies a label by description (e.g. "personal emails"), map it to the closest numbered label. Document the mapping decision in the task result.

---

## Result format

```
relay_update_task(
    task_id="...",
    status="done",
    result="Applied label '4-Personal & Family' to 32 emails matching query 'from:family.com'. 0 errors."
)
```

If any emails failed to label, report the count and a sample subject line.

---

## Approval gates

> Always surface scope before bulk labelling (>50 emails).  See CLAUDE.md approval gate rules.
