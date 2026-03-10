# User Story: Backlog Status Refactor

**Status:** ⬜ Backlog

## Summary
As a developer, I want all existing User Story files to be updated to the new template format so that Remy can read the status of any US file at a glance without parsing HTML comments.

---

## Background

The original `_TEMPLATE.md` placed the status tag inside an HTML comment block, which is invisible when files are read programmatically (e.g. by Remy via `read_file`). This means Remy cannot determine whether a story is done, in progress, or deferred without reading the entire file — and even then may miss it.

The template has been updated (2026-02-28) so that status is now a visible bold label on line 2:

```
**Status:** ✅ Done
```

All 34 existing US files need to be updated to match this convention.

---

## Acceptance Criteria

1. **Every US file** (excluding `_TEMPLATE.md`) has `**Status:** <emoji> <label>` as the second line.
2. **Status is accurate** — matches the actual state of the story (not just copied from a default).
3. **HTML comment blocks** referencing the old status tag system are removed or updated to reflect the new convention.
4. **No content loss** — all existing body content (summary, background, acceptance criteria, implementation, test cases) is preserved verbatim.
5. **`_TEMPLATE.md`** already updated — do not modify it again.

---

## Implementation

**Files to modify:** All 34 `US-*.md` files in `remy/docs/backlog/`

Work through each file:
1. Read the file.
2. Identify current status from either the comment block or any existing visible status line.
3. Insert `**Status:** <emoji> <label>` as line 2 (after the `# User Story:` heading).
4. Remove or update the old HTML comment block to strip the redundant status options list (keep the filename convention note).
5. Write the file.

### Status mapping from old format

| Old tag in comment | New visible line |
|---|---|
| `✅ Done` | `**Status:** ✅ Done` |
| `⬜ Backlog` | `**Status:** ⬜ Backlog` |
| `🔄 In Progress` | `**Status:** 🔄 In Progress` |
| `❌ Deferred` | `**Status:** ❌ Deferred` |
| No tag / unclear | Determine from content and confirm with Dale |

### Notes
- Some files have the status as a standalone line at the top (e.g. `✅ Done (2026-02-28)`) rather than in a comment — these still need to be normalised to the bold label format.
- Do the whole batch in one session to avoid leaving the backlog in a half-migrated state.
- Spot-check 3–4 files after completion to confirm format is consistent.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Remy reads any US file | Status visible on line 2, no file reading required beyond first two lines |
| File previously had status in comment | Status now on line 2; comment block cleaned up |
| File previously had freeform status line | Normalised to bold label format |
| Content below status line | Unchanged |

---

## Out of Scope

- Changing any story's actual status (scope, priority, content) — this is format only.
- Automating future status updates — that's a separate workflow question.
