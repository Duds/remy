---
name: next-pbi
description: Reads TODO.md, BUGS.md, and docs/backlog/ then recommends the highest-priority next PBI. Use when starting work, planning sprints, or when the user asks what to do next.
---

Read the following project files and synthesise a prioritised recommendation for the next PBI to work on:

1. `TODO.md` — roadmap, current phase status, MoSCoW priority table, and the "Next Steps" backlog sections (P1/P2/P3)
2. `BUGS.md` — open bugs with severity and status
3. All files under `docs/backlog/` — individual user story specs

Then produce a clear recommendation structured as follows:

## Recommended Next PBI

**Title:** [name of the PBI]
**Type:** Bug | Feature | Chore
**Priority:** P1 / P2 / P3 (from TODO.md)
**Backlog file:** `docs/backlog/<filename>.md` (if one exists)

**Why this one next:**
- 2–4 bullet points explaining the rationale (dependencies satisfied, value, effort, severity if a bug)

**Acceptance criteria (summary):**
- Key "done" conditions drawn from the backlog spec or TODO.md description

**Files likely to change:**
- List the source files called out in TODO.md or the backlog spec

---

## Runner-up PBIs (ordered)

List the next 2–3 candidates with a one-line rationale each.

---

Use the MoSCoW priority, the P1/P2/P3 ordering, open bug severity (High > Medium > Low), and any explicit dependency notes ("Depends on X above") from TODO.md to rank. Prefer items with existing backlog specs over those without. Prefer P1 over P2 over P3. Prefer open High-severity bugs over new features at the same priority level.
