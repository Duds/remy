# Code Review Skill

## Review Order

Always review in this order:

1. **Correctness** — does the code do what it claims? Logic errors, wrong conditions, off-by-one.
2. **Tests** — are new behaviours tested? Are edge cases covered? Are existing tests broken?
3. **Style** — only flag style issues that have a correctness or maintainability implication.

Never reorder. A missed logic error is more important than a naming convention.

## What to Flag

Flag these issues — they affect correctness or safety:

- Logic errors and wrong assumptions
- Missing error handling for failure modes that can happen
- Security concerns: injection, unvalidated input, exposed secrets, auth bypasses
- Unhandled edge cases the author has clearly not considered
- Missing or broken tests for new behaviour

## What Not to Flag

Do not flag:

- Style preferences with no correctness implication (naming, spacing, formatting)
- "I would have done it differently" rewrite suggestions
- Minor inefficiencies that do not affect observable behaviour
- Already-discussed items from a previous review round

## Output Format

Structured list grouped by severity. Maximum 500 words total. Surface the most important issues only — do not dump every observation.

```
## Blocking
- [file:line] [issue] — [why it matters]

## Non-blocking
- [file:line] [issue]

## Suggestions (optional, low priority)
- [file:line] [suggestion]
```

If there are no blocking issues, state it explicitly: "No blocking issues found."
If the diff is clean, respond: "LGTM — no issues found."
