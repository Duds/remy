# User Story: PARA Memory Files — Structured Knowledge Hierarchy (Paperclip-inspired)

**Status:** 📋 Backlog
**Priority:** ⭐⭐⭐ High
**Effort:** High
**Source:** [docs/paperclip-ideas.md §1](../paperclip-ideas.md)

## Summary

As Dale, I want Remy to maintain a structured PARA knowledge hierarchy (Projects, Areas, Resources, Archives) as persistent markdown/YAML files — in addition to its existing SQLite facts/knowledge tables — so that cross-session context about important people, companies, and projects is rich, browsable, and survives indefinitely without compaction loss.

---

## Background

Remy's current memory system stores facts and knowledge in SQLite with embeddings (`remy/memory/facts.py`, `remy/memory/knowledge.py`). This works well for retrieval but has limitations:

- **No structure**: facts are flat key-value pairs without entity grouping
- **No summaries**: no quick-reference view per person/project; everything must be queried
- **Compaction risk**: aggressive session compaction may lose subtle facts
- **No PARA hierarchy**: no distinction between projects (active), areas (ongoing), resources (reference), archives (inactive)

Paperclip's three-layer PARA memory:
- **Layer 1 — Knowledge Graph** (`$AGENT_HOME/life/`): Entity folders with `summary.md` + `items.yaml`
- **Layer 2 — Daily Notes** (`$AGENT_HOME/memory/YYYY-MM-DD.md`): Raw timeline
- **Layer 3 — Tacit Knowledge** (`$AGENT_HOME/MEMORY.md`): Operational patterns about Dale

---

## Acceptance Criteria

### Core Structure

1. **PARA directories.** Remy creates and maintains: `data/para/projects/`, `data/para/areas/people/`, `data/para/areas/companies/`, `data/para/resources/`, `data/para/archives/`
2. **Entity folders.** Each significant entity has a folder: `data/para/areas/people/john-smith/` containing:
   - `summary.md` — 3-10 bullet quick-reference (loaded first)
   - `items.yaml` — atomic facts (loaded on-demand)
3. **Daily notes.** Each day Remy appends to `data/memory/YYYY-MM-DD.md` — a running timeline of events, decisions, and interactions.
4. **Tacit knowledge file.** `data/MEMORY.md` stores operational patterns about how Dale works (preferences, quirks, workflow patterns).

### Entity Creation Rules

5. **Creation threshold.** A PARA entity folder is created only if:
   - Entity mentioned 3+ times in conversation, OR
   - Direct relationship to Dale (family, coworker, partner, client), OR
   - Significant project/company in Dale's life
   - Otherwise: write to daily notes only.
6. **No premature folders.** Remy does not create entity folders for one-off mentions.

### Fact Lifecycle

7. **Supersede, don't delete.** Facts in `items.yaml` are never deleted; outdated facts are marked:
   ```yaml
   status: superseded
   superseded_by: "updated fact content here"
   superseded_at: "2026-03-08"
   ```
8. **DB schema update.** Add `superseded_by TEXT` column to the `knowledge` table in SQLite to mirror this policy.

### Synthesis

9. **Weekly summary rewrite.** Once per week, Remy rewrites each active entity's `summary.md` from its `items.yaml` facts (top 10 most recent / most relevant active facts).

### Integration

10. **Context injection.** When an entity is mentioned in conversation, `summary.md` for that entity is injected into the system prompt (not `items.yaml` — keep context lean).
11. **Tool support.** A new `para_write_note` tool lets Remy add facts to an entity's `items.yaml` or to the daily notes file.
12. **Existing facts migrated.** A one-time migration script exports existing `knowledge` table rows into the appropriate `items.yaml` files.

---

## Implementation

### Directory layout

```
data/
  para/
    projects/
      remy-relay-setup/
        summary.md
        items.yaml
    areas/
      people/
        dale-rogers/
          summary.md
          items.yaml
      companies/
        anthropic/
          summary.md
          items.yaml
    resources/
    archives/
  memory/
    2026-03-08.md
    2026-03-09.md
    ...
  MEMORY.md
```

### New module (`remy/memory/para.py`)

```python
class PARAStore:
    """File-based PARA memory hierarchy."""

    def get_summary(self, entity_type: str, entity_id: str) -> str | None: ...
    def get_items(self, entity_type: str, entity_id: str) -> list[dict]: ...
    def add_fact(self, entity_type: str, entity_id: str, fact: str) -> None: ...
    def supersede_fact(self, entity_type: str, entity_id: str, fact_id: str, replacement: str) -> None: ...
    def append_daily_note(self, content: str) -> None: ...
    def rewrite_summary(self, entity_type: str, entity_id: str) -> None: ...
    def find_entity(self, name: str) -> str | None: ...  # fuzzy match to folder name
```

### Context injector (`remy/memory/injector.py`)

When building the system prompt, detect entity mentions → load matching `summary.md` → append to context.

### Tool schema (`remy/ai/tools/schemas.py`)

Add `para_write_note` tool: writes a fact to an entity's `items.yaml` or to today's daily notes.

### DB migration (`remy/memory/database.py`)

Add `superseded_by TEXT` and `superseded_at TEXT` columns to `knowledge` table.

### Migration script (`scripts/migrate_knowledge_to_para.py`)

One-time script: export `knowledge` table rows → create appropriate `items.yaml` files grouped by entity.

---

## Files Affected

| File | Change |
|------|--------|
| `remy/memory/para.py` | New: PARA file store |
| `remy/memory/database.py` | Add `superseded_by`, `superseded_at` columns |
| `remy/memory/injector.py` | Load PARA summary for mentioned entities |
| `remy/ai/tools/schemas.py` | Add `para_write_note` tool schema |
| `remy/ai/tools/memory.py` | Add `para_write_note` executor |
| `remy/scheduler/proactive.py` | Add weekly summary rewrite job |
| `scripts/migrate_knowledge_to_para.py` | New: migration script |
| `remy/config.py` | Add `PARA_HOME_PATH` config (default: `data/para`) |
| `.env.example` | Document `PARA_HOME_PATH` |

---

## Test Cases

| Scenario | Expected |
|---|---|
| Entity mentioned once | Written to daily notes only; no folder created |
| Entity mentioned 3+ times | Entity folder created with `summary.md` + `items.yaml` |
| `para_write_note` called | Fact appended to `items.yaml` |
| Fact superseded | Old fact marked `status: superseded`; new fact appended |
| Entity mentioned in conversation | `summary.md` injected into context |
| Weekly synthesis job | `summary.md` rewritten from top-10 active facts |
| Migration script runs | All `knowledge` rows exported to appropriate files |

---

## Out of Scope

- `qmd` CLI for PARA search (see `US-paperclip-qmd-cli.md` if created)
- Automatic entity classification (project vs. area vs. resource) — Remy decides based on context
- Multi-user PARA (Remy is single-user)
- Syncing PARA files with Google Drive (nice-to-have)

---

## Implementation Note

This is the largest of the Paperclip-inspired features. It should be broken into sub-tasks:
1. Create PARA directory structure + `PARAStore` class (no integration yet)
2. Add `para_write_note` tool + daily notes append
3. Wire entity injection into system prompt
4. Add weekly summary rewrite job
5. Migrate existing knowledge data
6. Add `superseded_by` to SQLite schema
