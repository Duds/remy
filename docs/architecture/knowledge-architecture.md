# Remy Knowledge Architecture (as built)

## Overview

Remy stores everything it learns about the user in a single unified **Knowledge Store** backed by SQLite. Prior to this design, facts, goals, and groceries were kept in separate tables and a flat text file — meaning the same intent expressed differently ("buy milk" vs "groceries" vs "shopping") could land in the wrong place or be missed entirely.

The unified store resolves this with a single `knowledge` table and a **drift-resilient extraction layer** that uses Claude to map fuzzy natural language to a consistent set of entity types.

---

## Data Model

### `knowledge` table

| Column         | Type        | Description                                     |
| -------------- | ----------- | ----------------------------------------------- |
| `id`           | INTEGER PK  | Stable numerical ID, always visible to Claude   |
| `user_id`      | INTEGER FK  | Owner (maps to `users.user_id`)                 |
| `entity_type`  | TEXT        | `fact` \| `goal` \| `shopping_item`             |
| `content`      | TEXT        | The item itself (e.g., "Build a robot", "milk") |
| `metadata`     | TEXT (JSON) | Type-specific fields — see below                |
| `embedding_id` | INTEGER FK  | FTS / ANN embedding for semantic search         |
| `created_at`   | TEXT        | ISO datetime                                    |
| `updated_at`   | TEXT        | ISO datetime                                    |

### `metadata` schema by type

| entity_type     | metadata fields                                                                         |
| --------------- | --------------------------------------------------------------------------------------- |
| `fact`          | `{"category": "name\|age\|location\|preference\|relationship\|health\|project\|other"}` |
| `goal`          | `{"status": "active\|completed\|abandoned", "description": "..."}`                      |
| `shopping_item` | `{}` (empty)                                                                            |

### Supporting tables (unchanged)

- `facts` — legacy table, kept for backwards compatibility
- `goals` — legacy table, kept for backwards compatibility
- `knowledge_fts` — FTS5 virtual table with triggers synced to `knowledge`

---

## Component Map

```
User message
     │
     ▼
┌─────────────────────────────┐
│     KnowledgeExtractor      │  remy/memory/knowledge.py
│  (Claude Haiku extraction)  │
│                             │
│  "buy milk" → shopping_item │
│  "finish scraper" → goal    │
│  "I'm 34" → fact            │
└─────────────┬───────────────┘
              │ list[KnowledgeItem]
              ▼
┌─────────────────────────────┐
│       KnowledgeStore        │  remy/memory/knowledge.py
│   (SQLite CRUD + ANN embed) │
│                             │
│  upsert()    get_by_type()  │
│  update()    delete()       │
│  migrate_legacy_data()      │
└──────┬──────────────────────┘
       │
   ┌───┴────────────────────────────────┐
   │                                    │
   ▼                                    ▼
┌────────────────────┐      ┌────────────────────────┐
│   MemoryInjector   │      │      ToolRegistry       │
│  (system prompt)   │      │  (Claude tool calls)   │
│                    │      │                        │
│ <memory>           │      │ get_goals → [ID:N] ... │
│   <facts> ...      │      │ get_facts → [ID:N] ... │
│   <goals> ...      │      │ grocery_list → show/   │
│   <shopping_list>  │      │   add/remove by ID     │
│ </memory>          │      │ manage_goal → by ID    │
└────────────────────┘      └────────────────────────┘
```

---

## Extraction Pipeline

Every user message triggers a background extraction task after the response is sent:

1. `KnowledgeExtractor.extract(message)` — sends message to Claude Haiku with a typed extraction prompt
2. Haiku returns a JSON array of `{entity_type, content, metadata}` objects
3. Each item is validated against the `KnowledgeItem` Pydantic model
4. `KnowledgeStore.upsert()` deduplicates by `(user_id, entity_type, LOWER(content))` and inserts new items
5. An embedding is generated; `knowledge.embedding_id` is updated

---

## ID Visibility Strategy

Previously, tool outputs stripped IDs for "clean" formatting — which made it impossible for Claude to precisely manage items. All memory tools now return stable numerical IDs:

```
Active goals (2):
• [ID:12] Build the web scraper — parsing in progress
• [ID:7] Drop off Alex

Shopping list:
• [ID:43] milk
• [ID:44] celery

(Use the ID with manage_goal / grocery_list to update, complete, or delete)
```

Claude uses these IDs directly in follow-up tool calls (`manage_goal`, `grocery_list remove`).

---

## Memory in the System Prompt

`MemoryInjector.build_context()` is called on every message and produces an XML block:

```xml
<memory>
  <facts>
    <fact category='preference'>Prefers dark mode</fact>
    <fact category='project_context'>[/Users/...] README content...</fact>
  </facts>
  <goals>
    <goal>Build the web scraper — parsing in progress</goal>
  </goals>
  <shopping_list>
    <item>milk</item>
    <item>celery</item>
  </shopping_list>
</memory>
```

Retrieval is tried in order:

1. **ANN (vector)** — semantically similar to the current message
2. **FTS5** — keyword match fallback
3. **Recent** — most recently updated items

---

## Legacy Migration

`KnowledgeStore.migrate_legacy_data(user_id, grocery_file)` ports all existing data in one pass:

- `facts` rows → `knowledge` as `entity_type='fact'`
- `goals` rows → `knowledge` as `entity_type='goal'` with status/description in metadata
- Grocery `.txt` file → `knowledge` as `entity_type='shopping_item'`

Legacy tables remain in the DB and are used as fallback if `knowledge_store` is unavailable.

---

## Input Validator

`sanitize_memory_injection()` sanitizes all memory content before injection into the system prompt. The safe-tag allowlist includes structural tags used by `MemoryInjector` and board sessions:

```python
_SAFE_MEMORY_TAG = re.compile(
    r'^<(?:/?memory|/?facts|/?goals|/?goal|/?topic|fact\b[^>]*|/fact)>$',
    re.IGNORECASE,
)
```

`<topic>` is explicitly whitelisted to prevent noise from `/board` sessions.
