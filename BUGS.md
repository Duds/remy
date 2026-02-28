# Remy Bug Tracker

---

## Bug Report Template

```markdown
### BUG-XXX — Short descriptive title

| Field           | Value                                     |
| --------------- | ----------------------------------------- |
| **Date**        | YYYY-MM-DD                                |
| **Reported by** | Dale / Remy / test suite                  |
| **Severity**    | Critical / High / Medium / Low            |
| **Status**      | Open / In Progress / Fixed / Won't Fix    |
| **Component**   | e.g. bot/handlers.py, ai/claude_client.py |
| **Related**     | Link to US, PR, or other bug              |

**Description**
What is happening, and what should be happening instead.

**Steps to Reproduce**

1. Step one
2. Step two
3. Observe the problem

**Expected Behaviour**
What should happen.

**Actual Behaviour**
What actually happens.

**Suspected Cause**
Any hypothesis about root cause — or "Unknown".

**Notes**
Anything else relevant: workarounds, frequency, environment quirks.
```

---

## Closed Bugs

### BUG-004 — HuggingFace Hub unauthenticated requests risk rate limiting

| Field           | Value                                                   |
| --------------- | ------------------------------------------------------- |
| **Date**        | 2026-02-28                                              |
| **Reported by** | Remy (log analysis)                                     |
| **Severity**    | Low                                                     |
| **Status**      | Fixed                                                   |
| **Component**   | `.env.example`                                          |
| **Related**     | —                                                       |

**Description**
Logs showed `huggingface_hub` warning about unauthenticated requests, exposing Remy to anonymous rate limiting on embedding calls.

**Fix**
Added `HF_TOKEN=` to `.env.example` with instructions to generate a free read token at `https://huggingface.co/settings/tokens`. `huggingface_hub` reads this env var automatically — no code change required.

---

### BUG-003 — APScheduler misses jobs on startup; daily reminders show "last run: never"

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Remy (log analysis)                                |
| **Severity**    | High                                               |
| **Status**      | Fixed                                              |
| **Component**   | `scheduler/proactive.py`                           |
| **Related**     | BUG-002                                            |

**Description**
Daily jobs (morning briefing, afternoon focus, evening check-in) and user automation jobs were being silently dropped when the bot restarted after their scheduled fire time. `misfire_grace_time` was 300 s (5 min), too short for a bot that may restart hours after a missed job.

**Fix**
Increased `misfire_grace_time` from `300` to `3600` (1 hour) for all four built-in scheduler jobs and all user automation jobs in `_register_automation_job()`. APScheduler will now fire missed daily jobs within a 1-hour window of restart. The `update_last_run()` call in `_run_automation()` was already in place; it now has a chance to fire since jobs are no longer dropped.

---

### BUG-002 — Reminders created mid-session are not fired by the scheduler

| Field           | Value                                                                                          |
| --------------- | ---------------------------------------------------------------------------------------------- |
| **Date**        | 2026-02-27                                                                                     |
| **Reported by** | Dale / Remy                                                                                    |
| **Severity**    | High                                                                                           |
| **Status**      | Fixed                                                                                          |
| **Component**   | `scheduler/proactive.py`, `ai/tool_registry.py`, `memory/automations.py`, `memory/database.py` |
| **Related**     | —                                                                                              |

**Description**
Reminders created via `schedule_reminder` after bot startup were saved to the database but never fired. The scheduler only registered reminders it knew about at startup. Additionally, there was no mechanism for one-time reminders ("remind me in 1 minute").

**Fix**
Two-part fix:

1. The existing `_exec_schedule_reminder` already called `sched.add_automation()` for live registration of recurring jobs — confirmed working.
2. Added full one-time reminder support:
   - Added `fire_at TEXT` column to the `automations` table via an idempotent migration in `database.py`.
   - Updated `AutomationStore.add()` to accept an optional `fire_at` datetime string; added `AutomationStore.delete()` for post-fire cleanup.
   - Updated `ProactiveScheduler._register_automation_job()` to use APScheduler's `DateTrigger` when `fire_at` is set; one-time jobs delete themselves from the DB after firing.
   - Added `set_one_time_reminder` Claude tool so Remy can handle "remind me in X minutes / at HH:MM" requests natively.

---

### BUG-001 — Inter-tool text fragments leak into Telegram stream

| Field           | Value                                 |
| --------------- | ------------------------------------- |
| **Date**        | 2026-02-27                            |
| **Reported by** | Dale                                  |
| **Severity**    | Low                                   |
| **Status**      | Fixed                                 |
| **Component**   | `bot/handlers.py` — Path A event loop |
| **Related**     | `US-tool-status-text-leak.md`         |
| **Fixed in**    | commit `7dabac3`                      |

**Description**
Claude's internal status fragments (e.g. "using list_directory", "let me check that") appeared verbatim in Telegram replies. A related symptom was narration lines being repeated: text emitted before a tool call was re-emitted after the tool result returned.

**Fix**
Introduced `in_tool_turn` boolean flag in `_stream_with_tools_path()`. Set to `True` on `ToolStatusChunk`, cleared on `ToolTurnComplete`. `TextChunk` events arriving while `in_tool_turn` is `True` are suppressed (DEBUG-logged only, not fed to `current_display`). `current_display` is reset to `[]` on each `ToolTurnComplete` to prevent pre-tool preamble from being repeated after tool results.

---

## Open Bugs

### BUG-008 — Input validator false-positives on `&&` and "system prompt" in normal messages

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Remy (log analysis)                                |
| **Severity**    | Low                                                |
| **Status**      | Open                                               |
| **Component**   | `remy/ai/input_validator.py`                       |
| **Related**     | —                                                  |

**Description**
The validator fires WARNING-level "Potential shell injection" and "Potential prompt injection" alerts on legitimate messages from Dale. The alerts do not block anything (they are flag-only), but they pollute the log with false positives that make it harder to spot real incidents.

**Observed false triggers (from logs):**
- `Potential shell injection` on commit summaries pasted into chat — because they contain `&&` (e.g. `"Fixed two bugs && added feature"`)
- `Potential prompt injection` on messages discussing the system prompt, e.g. `"Here's a summary of what landed in this commit: classifier.py…"` triggered by the `system.*prompt` pattern matching substrings in unrelated text.

**Root Cause**

In `input_validator.py`:

```python
_SHELL_INJECTION_PATTERN = re.compile(r"... &&|;;|& ...")  # && matches any text
_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"system.*override|system.*prompt|administrator|root.*access", re.IGNORECASE),
    ...
]
```

`&&` is a common English usage (commit messages, code examples, prose) and should require more context to flag. `system.*prompt` matches any sentence that mentions "system" and "prompt" together, which is frequent in technical conversation with a developer-user.

**Fix**
- For `&&`: require it to be preceded or followed by a command-like token (e.g. `\w+\s*&&\s*\w+` where the surrounding words look like shell commands), or remove `&&` from the pattern entirely since `;;` already covers the meaningful shell-specific case.
- For `system.*prompt`: tighten to require the phrase to appear in a clearly adversarial framing (e.g. `"ignore your system prompt"`, `"override the system prompt"`). Use a more specific pattern like `r"ignore.*system.*prompt|override.*system.*prompt"`.

---

### BUG-007 — `no such column: confidence` degrades all memory injection silently

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Remy (log analysis)                                |
| **Severity**    | High                                               |
| **Status**      | Open                                               |
| **Component**   | `remy/memory/database.py`, `remy/memory/injector.py`, `remy/bot/handlers.py` |
| **Related**     | —                                                  |

**Description**
Logs show repeated `Memory injection failed, using base prompt: no such column: confidence` warnings. When this occurs, `MemoryInjector.build_system_prompt()` falls back to the bare SOUL.md prompt — Remy has no access to facts, goals, or knowledge context for the session.

**Root Cause**
Migration 002 in `database.py` adds the `confidence` column to the `knowledge` table:

```python
"ALTER TABLE knowledge ADD COLUMN confidence REAL DEFAULT 1.0;",
```

The migration runner swallows all exceptions with a bare `except Exception: pass`:

```python
for migration_sql in _MIGRATIONS:
    try:
        await self._conn.execute(migration_sql)
        await self._conn.commit()
    except Exception:
        pass  # Column/index already exists
```

If the migration fails for any reason other than "column already exists" (e.g. a locked DB on the Azure Files mount, a transient I/O error, or a prior connection issue during startup), the exception is silently discarded. The app starts normally, but every subsequent query against `knowledge` that references `confidence` raises `OperationalError: no such column: confidence`, which `handlers.py` catches and logs as a WARNING — falling back to the base prompt for the entire session.

**Steps to Reproduce**
1. Deploy with a `remy.db` that predates migration 002 (i.e. has `knowledge` table without `confidence` column).
2. Arrange for the migration to fail silently (e.g. DB locked at startup under Azure Files).
3. Observe: bot starts cleanly, no ERROR logged. Every message silently uses base prompt.

**Expected Behaviour**
Migration failures for any reason other than "already applied" should be logged at ERROR level with the SQL and the exception, so the issue is immediately visible. Memory injection should not silently degrade without a clear alert.

**Actual Behaviour**
Migration failure is swallowed. `no such column: confidence` surfaces only as a WARNING inside `build_context`, making the root cause (failed migration) invisible in the logs.

**Fix**
1. In the migration runner, distinguish "already applied" from unexpected failure:
   ```python
   for migration_sql in _MIGRATIONS:
       try:
           await self._conn.execute(migration_sql)
           await self._conn.commit()
       except aiosqlite.OperationalError as e:
           if "already exists" not in str(e) and "duplicate column" not in str(e):
               logger.error("Migration failed (SQL: %s): %s", migration_sql[:60], e)
   ```
2. In `handlers.py`, upgrade the memory injection fallback from WARNING to ERROR so operator is alerted when it happens.

---

### BUG-006 — `test_web_search_error_returns_empty` mock patch misses DDGS import

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | test suite                                         |
| **Severity**    | Low                                                |
| **Status**      | Open                                               |
| **Component**   | `tests/test_phase4.py`, `remy/web/search.py`       |
| **Related**     | —                                                  |

**Description**
`test_web_search_error_returns_empty` patches `remy.web.search.DDGS` to raise a `RuntimeError`, expecting `web_search()` to swallow the error and return `[]`. Instead, the real DuckDuckGo library is called and returns real results, so the assertion `assert results == []` fails.

**Root Cause**
`DDGS` is imported *inside* the `_sync` closure (`from ddgs import DDGS`), not at module level. `patch("remy.web.search.DDGS", create=True)` injects a name into the `remy.web.search` module namespace, but because the local `from ddgs import DDGS` runs *after* the patch is in place it resolves `ddgs.DDGS` directly from the `ddgs` package — bypassing the module-level mock entirely.

**Steps to Reproduce**
```
pytest tests/test_phase4.py::test_web_search_error_returns_empty -v
```

**Expected Behaviour**
Test passes: mock intercepts the DDGS call, `RuntimeError` is raised inside `_sync`, `web_search` catches it, returns `[]`.

**Actual Behaviour**
Mock is ignored. Real DDGS is used. Real results returned. `AssertionError: assert [{'body': ...}] == []`.

**Fix**
Two options:
1. Patch at the source: `patch("ddgs.DDGS", ...)` so all imports of `DDGS` from the `ddgs` package see the mock.
2. (Preferred) Follow the same pattern as `test_web_search_returns_results` — patch `remy.web.search.asyncio.to_thread` with an `AsyncMock(side_effect=RuntimeError("rate limited"))` so the error is injected at the thread boundary, which is simpler and avoids chasing import paths.

---

### BUG-005 — `test_memory_injector` tests fail with stale `MemoryInjector` constructor signature

| Field           | Value                                                                            |
| --------------- | -------------------------------------------------------------------------------- |
| **Date**        | 2026-02-28                                                                       |
| **Reported by** | test suite                                                                       |
| **Severity**    | Medium                                                                           |
| **Status**      | Open                                                                             |
| **Component**   | `tests/test_memory_injector.py`, `tests/test_memory_injector_extra.py`          |
| **Related**     | —                                                                                |

**Description**
14 tests in `test_memory_injector.py` and `test_memory_injector_extra.py` error at setup with:

```
TypeError: MemoryInjector.__init__() takes 5 positional arguments but 6 were given
```

**Root Cause**
A prior refactor replaced `fact_store` + `goal_store` with a unified `knowledge_store` in `MemoryInjector.__init__`. The current signature is:

```python
def __init__(self, db, embeddings, knowledge_store: KnowledgeStore, fts: FTSSearch)
```

Both test files still construct `MemoryInjector` using the old 5-arg signature:

```python
injector = MemoryInjector(db, embeddings, fact_store, goal_store, fts)  # wrong
```

**Fix**
Update the `components` fixture in both test files to instantiate `KnowledgeStore` and pass it as the third argument:

```python
from remy.memory.knowledge import KnowledgeStore
knowledge_store = KnowledgeStore(db, embeddings)
injector = MemoryInjector(db, embeddings, knowledge_store, fts)
```

Remove the `FactStore` and `GoalStore` imports from the fixture if they are no longer needed. Verify that the existing test assertions still make sense against `KnowledgeStore` behaviour (facts and goals are now stored there).

---
