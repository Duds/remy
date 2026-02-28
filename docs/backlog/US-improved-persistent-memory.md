# User Story: Improved Persistent Memory

✅ Complete — 2026-02-28

## Summary
As a user, I want Remy's memory of me to stay accurate over time — old facts should be
superseded by newer ones, near-duplicates should be merged, and stale information should not
crowd out recent context — so that Remy's understanding of me improves with every conversation
rather than accumulating noise.

---

## Background

The current memory system works as follows (see `remy/memory/facts.py`, `embeddings.py`,
`injector.py`):

- `FactExtractor` uses Claude Haiku to extract facts from each user message; facts are stored
  in the `facts` SQLite table with a simple string-equality dedup check.
- `EmbeddingStore` embeds each fact with `all-MiniLM-L6-v2` (384 dims) and stores in
  `embeddings_vec` for ANN search. Falls back to FTS5 in container (sqlite-vec ELF mismatch).
- `MemoryInjector.build_context()` runs ANN → FTS5 → recency fallback, injects the top-5
  most relevant facts + top-3 goals as an XML block into every system prompt.

### Known gaps

**1. Conflicting facts accumulate.** The dedup check is `fact.content.lower() in existing`
(exact string match). If Dale says "I live in Sydney" and later "I moved to Canberra", both
facts coexist. There is no conflict detection or supersession.

**2. No staleness tracking.** `facts.confidence` is set to `1.0` and never changed. There is
no `last_referenced_at` column, so there's no way to age out facts from months ago that are
likely stale (old job, old address, resolved health issues).

**3. No source tracking.** There is no link from a fact back to the conversation turn that
produced it. If Remy states something wrong about Dale, there's no way to trace it.

**4. Narrow extraction categories.** The current categories are: `name, age, location,
occupation, preference, relationship, health, project, other`. There is no `medical`,
`finance`, `hobby`, or `deadline` category, so many facts land in `other` and are harder to
retrieve accurately.

**5. Near-duplicate facts from paraphrase.** "Dale works in software" and "Dale is a software
engineer" produce two distinct facts with no merge. Over months, the facts table fills with
slight restatements of the same information.

**6. System prompt bloat.** The injector caps at 5 facts + 3 goals. With a growing facts table,
the 5 slots are often filled by high-recency but low-relevance facts, while the most important
biographical facts are crowded out.

---

## Acceptance Criteria

### 1. Semantic deduplication on upsert
When a new fact is extracted, compare it to existing facts in the same broad category using
ANN cosine distance. If the closest existing fact has distance < 0.15 (i.e. very similar
meaning), **supersede** it: update the content and reset the embedding, rather than inserting
a new row. Log the merge at DEBUG level.

- The existing exact-string dedup remains as a fast pre-check before ANN.
- Threshold is configurable via `settings.fact_merge_threshold` (default: 0.15).
- Only compare within-category to avoid false merges (e.g. two facts both categorised
  "preference" but about different topics).

### 2. `last_referenced_at` column + relevance scoring
Add `last_referenced_at TEXT` to the `facts` table (migration 002).

- Set to `datetime('now')` on insert.
- Updated whenever a fact appears in a `MemoryInjector.build_context()` result.
- The ANN query in `EmbeddingStore.search_similar_for_type()` gains an optional
  `recency_boost` parameter: results within the last 30 days are weighted higher.

### 3. Expanded category taxonomy
Update `_EXTRACTION_SYSTEM` in `facts.py` to recognise:

| Category | Examples |
|---|---|
| `name` | "User's name is Dale" |
| `location` | "Lives in Canberra" |
| `occupation` | "GP, works at a practice in Canberra" |
| `health` | "Recovering from knee surgery" |
| `medical` | "Has ADHD", "prescribed X medication" |
| `finance` | "Has a mortgage", "uses CommBank" |
| `hobby` | "Plays ice hockey", "builds AI agents" |
| `relationship` | "Wife Kathryn", "kids in primary school" |
| `preference` | "Prefers dark mode", "favourite coffee is long black" |
| `deadline` | "Tax deadline 31 Oct", "dental appointment next Thursday" |
| `project` | "Working on remy", "remy project path: ~/Projects/ai-agents/remy" |
| `other` | Catch-all |

### 4. Source tracking (`source_session` column)
Add `source_session TEXT` to the `facts` table (migration 003). Populated from the current
`session_key` when a fact is inserted. Allows Claude to answer "when did I tell you that?":

```python
# In manage_memory tool response for get_facts:
"[ID 42] occupation: 'Dale is a GP' (from session 2026-01-15, confidence 1.0)"
```

### 5. `get_memory_summary` tool
New tool in `tool_registry.py` that returns a structured overview of stored memory:

```
📋 Memory summary (47 facts, 6 goals):
  Recent (last 7 days): 8 facts
  Categories: location (3), occupation (2), health (5), hobby (4), preference (12), …
  Oldest fact: "User's name is Dale" (2026-01-01)
  Potentially stale (>90 days, not referenced): 3 facts
```

Natural language: "What do you remember about me?", "How many facts do you have about me?"

### 6. No new Python dependencies
Uses existing `EmbeddingStore`, `aiosqlite`, and `FactStore` infrastructure. No new packages.

---

## Implementation

**Modified files:**
- `remy/memory/database.py` — add migrations 002 + 003; update `facts` DDL comment
- `remy/memory/facts.py` — semantic dedup in `upsert()`; expanded categories in extractor
- `remy/memory/embeddings.py` — optional `recency_boost` in `search_similar_for_type()`
- `remy/memory/injector.py` — update `last_referenced_at` when a fact appears in results
- `remy/ai/tool_registry.py` — add `get_memory_summary` tool + executor

### Schema migrations

```sql
-- Migration 002
ALTER TABLE facts ADD COLUMN last_referenced_at TEXT;
UPDATE facts SET last_referenced_at = created_at WHERE last_referenced_at IS NULL;

-- Migration 003
ALTER TABLE facts ADD COLUMN source_session TEXT;
```

### Semantic dedup in `FactStore.upsert()`

```python
async def upsert(self, user_id: int, facts: list[Fact], session_key: str = "") -> None:
    existing_content = await self._get_all_content(user_id)
    for fact in facts:
        # Fast path: exact string match
        if fact.content.lower() in existing_content:
            continue
        # Semantic path: ANN similarity within category
        similar = await self._embeddings.search_similar_for_type(
            user_id, fact.content, source_type="fact", limit=1
        )
        if similar and similar[0]["distance"] < settings.fact_merge_threshold:
            # Supersede: update the similar fact instead of inserting
            await self.update(user_id, similar[0]["source_id"], fact.content)
            logger.debug("Merged fact (d=%.3f): %r → %r",
                         similar[0]["distance"], similar[0]["content_text"], fact.content)
        else:
            await self._insert(user_id, fact, session_key=session_key)
            existing_content.add(fact.content.lower())
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| "I moved to Canberra" (previously "I live in Sydney") | Old fact superseded; only Canberra remains |
| Same fact stated twice in different wording | Merged; fact count stays flat |
| Facts from different categories with similar text | NOT merged (category filter prevents cross-merge) |
| "What do you remember about me?" | `get_memory_summary` tool returns structured overview |
| "When did you learn that?" | `source_session` in fact row returned with date |
| Fact referenced in every query | `last_referenced_at` updated; appears in recency boost |
| Fact not referenced for 90 days | Flagged in `get_memory_summary` as "potentially stale" |

---

## Out of Scope

- Automatic deletion of stale facts (user must confirm — too risky to auto-purge)
- Cross-user memory (all facts are strictly per `user_id`)
- Fact versioning / full history of changes (supersede-in-place is sufficient)
- Integrating conversation-level summaries into the facts table
