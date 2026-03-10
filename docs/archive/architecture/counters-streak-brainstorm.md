# Count / streak feature — brainstorm

**Goal:** Support a numeric counter (e.g. sobriety streak in days) that the user or the afternoon check-in can reference and update. HEARTBEAT and SOUL already frame the wellbeing check as the sobriety check; the model should be able to read (and optionally update) a "days" or "streak" value.

---

## Options

### 1. New table: `counters` (recommended)

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS counters (
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    name      TEXT NOT NULL,
    value     INTEGER NOT NULL DEFAULT 0,
    unit      TEXT NOT NULL DEFAULT 'days',   -- e.g. 'days', 'hours', ''
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_counters_user ON counters(user_id);
```

**Pros:**

- Single source of truth; no parsing.
- Simple API: `get_counter(user_id, name)`, `set_counter(user_id, name, value)`, optional `increment_counter`, `reset_counter`.
- Heartbeat and tools can read/write; memory injector can include "Sobriety streak: 14 days" in context for the model.
- Extensible: other named counters later (e.g. exercise streak, no-spend days) without schema change.

**Cons:**

- New table + migration; new store class or methods on existing store.

**Integration:**

- **Tool:** e.g. `get_counter(name)`, `set_counter(name, value)` so user can say "I'm on day 5" or "what's my streak?" and the model updates or reads.
- **Memory injector:** When building context for proactive/heartbeat, include a line for known counters (e.g. `sobriety_streak`) so the model can say "Day 14 — how are you doing?" without a separate tool call.
- **Heartbeat:** No schema change to heartbeat_log; the evaluator just receives injected memory that includes the streak if present.

---

### 2. Store in `facts` (category + content)

Use existing facts table: e.g. category `counter` or `sobriety`, content `streak: 14` or JSON `{"streak_days": 14, "updated": "2026-03-06"}`.

**Pros:**

- No schema change; reuses fact storage and embedding (if we want search over "streak").
- Model already sees facts in memory.

**Cons:**

- Updating = find fact by user_id + category (and maybe key), then UPDATE content or replace. Dedup/overwrite logic needed.
- No clean numeric type; parsing and validation on read/write.
- Multiple counters (e.g. sobriety vs exercise) either multiple facts or one JSON blob — both a bit clumsy.

---

### 3. Dedicated fact format (single fact per counter)

One fact per counter: category `counter`, content `sobriety_streak: 14 days`. Convention: `name: value unit`. Update = upsert by (user_id, category, content prefix or a convention).

**Pros:**

- No new table; fits current fact retrieval.

**Cons:**

- Parsing and overwrite semantics; no single source of truth for "current value" without scanning facts. Easy to end up with duplicate or stale facts unless we enforce one fact per counter name (then we're reinventing a key-value table).

---

### 4. Goal or plan abuse

e.g. Goal "Sobriety streak" with a "step" or custom field that holds the number. Or a single plan with one step whose title is "Day 14".

**Cons:**

- Goals/plans are for outcomes and tasks, not for a single integer. Querying "current streak" would be awkward and semantically wrong.

---

## Recommendation

**Option 1 (new `counters` table)** is the cleanest: explicit schema, simple get/set/increment/reset, easy to expose as a tool and to inject into memory for the sobriety check-in. Implementation steps:

1. Add `counters` table in `remy/memory/database.py` (DDL + migration if needed).
2. Add `CounterStore` (or methods on an existing store) with `get`, `set`, `increment`, `reset` by (user_id, name).
3. Add tools: `get_counter`, `set_counter` (and optionally `increment_counter` / `reset_counter`) so the user can report or ask for the streak.
4. In memory injector (or a dedicated path for proactive/heartbeat), include a short line for known counters (e.g. "Sobriety streak: 14 days") when building context so the model and heartbeat evaluator see it without calling the tool.
5. Optionally: allow HEARTBEAT.md or config to list counter names to inject (e.g. `sobriety_streak`) so only relevant counters are shown.

---

## Open questions

- **Auto-increment (implemented):** Counters in `AUTO_INCREMENT_DAILY_COUNTERS` (e.g. `sobriety_streak`) are incremented once per calendar day at 00:01 user timezone. `last_increment_date` prevents double-counting. User can still set/reset/increment manually.
- **Naming:** `sobriety_streak` vs `sobriety_days` vs configurable name. A single well-known name (`sobriety_streak`) keeps the first version simple; we can add more counters later by name.
- **Unit:** Store `unit` (e.g. `days`) so the injector can format "14 days" or "14" depending on display.
