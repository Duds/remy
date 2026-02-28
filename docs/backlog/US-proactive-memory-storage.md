# User Story: Proactive Memory Storage

⬜ Backlog — P1

## Summary
As a user, I want Remy to automatically store important things I mention in conversation —
completed tasks, personal updates, people's plans, decisions — without me having to say
"remember this", so that nothing falls through the cracks between sessions.

---

## Background

Remy currently extracts and stores facts from user messages via `FactExtractor` (Claude Haiku),
but this is narrow and passive. It captures biographical facts well ("Dale lives in Canberra")
but misses ephemeral-but-important conversational updates:

- "The tyre's done" → no fact stored; reminder deleted; information gone
- "Alex is away for the weekend" → reminder set, but the underlying fact not persisted
- "I've decided to go with the CommBank mortgage" → decision not stored
- "Kieran's in hospital" → significant personal update; lost at session end

When Dale reports back that Remy "should have known" something told to it earlier in the day,
the root cause is always the same: the information lived in conversation history, not in
persistent memory. Conversation history does not survive session boundaries reliably.

This story covers the **behavioural** fix — what Remy should do in its prompt/soul — as
distinct from the infrastructure improvements in `US-improved-persistent-memory.md`.

The SOUL.md has been updated (2026-03-01) to instruct Remy to store facts proactively.
This US tracks the prompt engineering, testing, and any supporting code changes needed to
make that instruction reliable in practice.

---

## Acceptance Criteria

1. **Completed tasks are stored.** When Dale says something is done, collected, finished, or
   resolved, Remy stores a datestamped fact, e.g. `"Tyre collected from Tyrepower (2026-03-01)"`.

2. **People's plans and whereabouts are stored.** "Alex is away for the weekend" → fact stored
   under category `relationship` or `other` with date context.

3. **Decisions and preferences are stored.** "I've decided to go with X" → stored under
   `preference` or `other`.

4. **Personal updates are stored.** New job, health update, move, relationship change →
   stored under the appropriate category.

5. **Storage is silent.** Remy does not announce "I've stored that fact." It just does it.
   The `manage_memory` call is a side-effect of the reply, not the reply itself.

6. **Outdated facts are updated, not duplicated.** If "Alex is away" was stored and Dale later
   says "Alex is back", Remy updates or removes the old fact. Uses `manage_memory` with
   `action: update` or `action: delete`.

7. **Trivia is not stored.** Remy uses judgement. "It's hot today" is not stored.
   "I've been diagnosed with sleep apnea" is.

---

## Implementation

### Phase 1 — SOUL.md instruction (complete)

Added `## Proactive Memory Storage` section to `config/SOUL.md` on 2026-03-01. This instructs
Remy to call `manage_memory` proactively when Dale mentions anything worth persisting.

No code changes required for Phase 1. The instruction runs entirely through the system prompt.

### Phase 2 — Prompt evaluation and tuning

Run a set of test conversations (see Test Cases below) and observe whether Remy stores the
right facts, avoids storing trivia, and silently updates stale facts.

Tune the SOUL.md instruction if Remy is over- or under-storing.

### Phase 3 — Supporting infrastructure (optional, depends on US-improved-persistent-memory)

If semantic dedup (from `US-improved-persistent-memory.md`) is in place, Remy can store
proactively without worrying about duplicates — the dedup layer will merge near-identical facts.
Without it, over-eager storage may create noise. Consider gating Phase 3 on that story.

**Files potentially modified:**
- `config/SOUL.md` — already updated
- `remy/memory/facts.py` — ensure `manage_memory` tool handles `action: update` and
  `action: delete` cleanly when called with a fact_id sourced from `get_facts`
- `remy/ai/tool_registry.py` — verify `manage_memory` tool schema includes `fact_id` for
  update/delete flows (should already exist; confirm)

---

## Test Cases

| Scenario | Expected |
|---|---|
| "The tyre's done" | Fact stored: `"Tyre collected from Tyrepower (date)"` under `other` |
| "Alex is away for the weekend" | Fact stored: `"Alex away for the weekend (date)"` under `relationship` |
| "I've decided to go with CommBank" | Fact stored under `preference` or `other` |
| "It's really hot today" | No fact stored — trivia |
| "Alex is back" (after away fact stored) | Old fact updated or removed |
| "I started seeing a physio" | Fact stored under `health` |
| "I moved to a new team at work" | Fact stored under `occupation` |
| Remy stores a fact | No announcement to the user — silent side-effect |
| Remy told same fact twice in a session | No duplicate created (exact dedup or semantic dedup) |

---

## Out of Scope

- Automatic extraction from *all* messages via FactExtractor (that's `US-improved-persistent-memory.md`)
- End-of-session memory consolidation (separate story — see TODO.md)
- Completed one-time reminders auto-logging to memory (separate story — see TODO.md)
