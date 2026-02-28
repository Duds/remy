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

### BUG-006 — `test_web_search_error_returns_empty` mock patch misses DDGS import

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | test suite                                         |
| **Severity**    | Low                                                |
| **Status**      | Fixed                                              |
| **Component**   | `tests/test_phase4.py`                             |
| **Related**     | —                                                  |

**Description**
`test_web_search_error_returns_empty` patched `remy.web.search.DDGS` but the import happens inside the `_sync` closure, bypassing the mock.

**Fix**
Used `patch.dict("sys.modules", {"ddgs": MagicMock()})` to inject a mock at the package level before the import runs inside `_sync()`.

---

### BUG-005 — `test_memory_injector` tests fail with stale `MemoryInjector` constructor signature

| Field           | Value                                                                   |
| --------------- | ----------------------------------------------------------------------- |
| **Date**        | 2026-02-28                                                              |
| **Reported by** | test suite                                                              |
| **Severity**    | Medium                                                                  |
| **Status**      | Fixed                                                                   |
| **Component**   | `tests/test_memory_injector.py`, `tests/test_memory_injector_extra.py` |
| **Related**     | —                                                                       |

**Description**
14 tests errored with `TypeError: MemoryInjector.__init__() takes 5 positional arguments but 6 were given` due to a stale constructor signature after refactoring to `KnowledgeStore`.

**Fix**
Test files already had the correct signature — the bug was stale. Verified all 14 tests pass.

---

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

### BUG-011 — Google auth "No project ID could be determined" warning on startup

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Dale                                               |
| **Severity**    | Low                                                |
| **Status**      | Open                                               |
| **Component**   | `remy/google/auth.py`, `.env`                      |
| **Related**     | —                                                  |

**Description**
On every container startup, the following warning appears in logs:
```
[WARNING] google.auth._default: No project ID could be determined. Consider running `gcloud config set project` or setting the GOOGLE_CLOUD_PROJECT environment variable
```

The warning is benign — Google Workspace APIs (Calendar, Gmail, Docs, Contacts) work correctly without a project ID because they use OAuth2 user credentials, not service account credentials. However, the warning pollutes logs and may cause confusion.

**Steps to Reproduce**
1. Start Remy container
2. Check logs: `docker compose logs remy | grep "No project ID"`

**Expected Behaviour**
No warning, or warning suppressed if project ID is not required.

**Actual Behaviour**
Warning logged on every startup.

**Potential Fixes**
- Set `GOOGLE_CLOUD_PROJECT` env var in `.env` to the GCP project ID used for OAuth consent screen
- Suppress the specific warning via Python logging filters
- Set project ID programmatically before Google client initialisation

**Notes**
Low priority — functionality is not affected. The warning comes from `google-auth` library's default credential detection, which looks for a project ID even when using user OAuth credentials.

---

### BUG-010 — ONNX runtime workaround reduces embedding parallelism

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Dale                                               |
| **Severity**    | Low                                                |
| **Status**      | Open                                               |
| **Component**   | `remy/memory/embeddings.py`, `Dockerfile`          |
| **Related**     | BUG-009                                            |

**Description**
The fix for BUG-009 (ONNX "Artifact already registered" error) works by:
1. Serializing all embedding calls through an asyncio lock
2. Disabling ONNX graph optimization (`ORT_DISABLE_ALL_GRAPH_OPTIMIZATION=1`)
3. Forcing single-threaded execution (`OMP_NUM_THREADS=1`)

While this fixes the crash, it reduces embedding throughput during file indexing. The initial index of ~/Projects and ~/Documents now takes longer than it would with parallel embeddings.

**Potential Future Fixes**
- Upgrade sentence-transformers/ONNX runtime when a thread-safe version is released
- Switch to a different embedding backend (e.g. PyTorch-only mode without ONNX)
- Use a dedicated embedding worker process with a queue to isolate ONNX state
- Batch multiple texts into single encode() calls to amortise the lock overhead

**Notes**
This is a known upstream issue. Monitor:
- https://github.com/microsoft/onnxruntime/issues (search "precompile artifact")
- https://github.com/UKPLab/sentence-transformers/issues

Low priority — the current fix is stable and the performance impact is acceptable for background indexing.

---

### BUG-009 — ONNX runtime "Artifact already registered" breaks all embeddings

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Dale                                               |
| **Severity**    | Critical                                           |
| **Status**      | Fixed                                              |
| **Component**   | `remy/memory/embeddings.py`                        |
| **Related**     | —                                                  |

**Description**
After Docker rebuild, all embedding calls fail with "Artifact of type=precompile already registered in mega-cache artifact factory". This causes:
- File indexing to fail completely (0 files indexed after 181s)
- Semantic search to fall back to FTS
- Degraded search quality across the board

**Root Cause**
The ONNX runtime used by sentence-transformers is not thread-safe. When multiple async tasks call `embed()` concurrently (via `run_in_executor`), the ONNX precompile cache throws this error. The existing `_model_lock` only protected model initialization, not the actual encode() calls.

**Fix**
Added an asyncio lock (`_encode_lock`) that serializes all `embed()` calls. While this reduces parallelism, it prevents the ONNX runtime from corrupting its internal state. The lock is created lazily on first use to avoid issues with event loop availability at module import time.

---

## Closed Bugs

### BUG-008 — Input validator false-positives on `&&` and "system prompt" in normal messages

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Remy (log analysis)                                |
| **Severity**    | Low                                                |
| **Status**      | Fixed                                              |
| **Component**   | `remy/ai/input_validator.py`                       |
| **Related**     | —                                                  |

**Description**
The validator fired WARNING-level "Potential shell injection" and "Potential prompt injection" alerts on legitimate messages from Dale. The alerts did not block anything (flag-only), but polluted logs with false positives.

**Fix**
- Removed `&&` and `&` from `_SHELL_INJECTION_PATTERN` — too common in prose. `;;` remains as it's rare outside shell scripts.
- Tightened `_PROMPT_INJECTION_PATTERNS` to require adversarial framing (ignore/override/bypass) before "system prompt". Technical discussion about system prompts no longer triggers.
- Added 6 test cases in `tests/test_input_validator.py` covering false-positive scenarios and ensuring real injection patterns still match.

---

### BUG-007 — `no such column: confidence` degrades all memory injection silently

| Field           | Value                                              |
| --------------- | -------------------------------------------------- |
| **Date**        | 2026-02-28                                         |
| **Reported by** | Remy (log analysis)                                |
| **Severity**    | High                                               |
| **Status**      | Fixed                                              |
| **Component**   | `remy/memory/database.py`, `remy/bot/handlers.py`  |
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
