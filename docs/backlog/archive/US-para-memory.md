# User Story: PARA Memory Files — Structured Knowledge Hierarchy

**Status:** ✅ Done (2026-03-11 — PARAStore, para_write_note, injector, weekly job, migration script)
**Priority:** ⭐⭐⭐ High
**Effort:** High
**Source:** [docs/ideas.md §1](../../ideas.md)

## Summary

As Dale, I want Remy to maintain a structured PARA knowledge hierarchy (Projects, Areas, Resources, Archives) as persistent markdown/YAML files — in addition to its existing SQLite facts/knowledge tables — so that cross-session context about important people, companies, and projects is rich, browsable, and survives indefinitely without compaction loss.

---

## Background

Remy's current memory system stores facts and knowledge in SQLite with embeddings. This story adds file-based PARA (projects, areas/people, areas/companies, resources, archives) with entity folders (`summary.md`, `items.yaml`), daily notes, and tacit knowledge.

---

## Acceptance Criteria (summary)

- PARA directories and entity folders with summary.md + items.yaml.
- Daily notes (`data/memory/YYYY-MM-DD.md`), supersede-not-delete for facts.
- Weekly summary rewrite job; context injection when entities are mentioned.
- `para_write_note` tool; migration script; `superseded_at` on knowledge table.

---

## Files Affected

`remy/memory/para.py`, `remy/memory/database.py`, `remy/memory/injector.py`, `remy/ai/tools/schemas.py`, `remy/ai/tools/memory.py`, `remy/scheduler/proactive.py`, `scripts/migrate_knowledge_to_para.py`, `remy/config.py`, `.env.example`.
