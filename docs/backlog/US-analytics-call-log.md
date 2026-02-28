# User Story: API Call Log — Storage, Latency & Model Accuracy

⬜ Backlog

## Summary

As the analytics system, I want every model invocation recorded in a structured `api_calls` database table — with token counts, latency, provider, model, and routing category — so that all analytics commands and cost reports have a single, accurate source of truth.

---

## Background

Currently, model usage is tracked only via the `model_used` field on `ConversationTurn` (stored in per-user JSONL files). This has three problems:

1. **Hardcoded strings.** Tool-use turns in `handlers.py:2149` and `handlers.py:2166` write the literal string `"claude:sonnet"` instead of the actual model ID from `settings.model_complex`. If the setting changes, the JSONL data silently lies.

2. **Missing data.** The proactive pipeline (`pipeline.py`) never writes `model_used` — all proactive turns appear as `"unknown"` in `/stats`. Background job calls (`agents/background.py`) are also untracked.

3. **No token counts.** The JSONL only records that a model was called, not how many tokens were consumed. There is no latency data, no category data, and no per-call record.

A dedicated `api_calls` table solves all three by becoming the authoritative log at the call level (one row per API request), independent of the conversation turn log.

**Covers:** ANA-004 (call log table), ANA-005 (latency), ANA-008 (model accuracy fixes in handlers and pipeline).

**Depends on:** `US-analytics-token-capture.md` — `TokenUsage` data must be available before this story can be implemented.

---

## Acceptance Criteria

1. **`api_calls` table exists.** Created via the existing `DatabaseManager` migration path with columns:

   | Column | Type | Notes |
   |---|---|---|
   | `id` | INTEGER PK | autoincrement |
   | `user_id` | INTEGER | FK to users table |
   | `session_key` | TEXT | e.g., `user_123_20260228` |
   | `timestamp` | TEXT | ISO 8601 UTC |
   | `provider` | TEXT | `anthropic`, `mistral`, `moonshot`, `ollama` |
   | `model` | TEXT | exact model ID, e.g., `claude-sonnet-4-6` |
   | `category` | TEXT | classifier output: `routine`, `reasoning`, `coding`, etc. |
   | `call_site` | TEXT | `router`, `tool_use`, `proactive`, `background`, `classifier` |
   | `input_tokens` | INTEGER | |
   | `output_tokens` | INTEGER | |
   | `cache_creation_tokens` | INTEGER | 0 for non-Anthropic |
   | `cache_read_tokens` | INTEGER | 0 for non-Anthropic |
   | `latency_ms` | INTEGER | wall-clock ms from first attempt to last chunk |
   | `fallback` | INTEGER | 0 or 1 — was Ollama used as fallback? |

2. **`ModelRouter` writes a record** after every `_stream_with_fallback()` call completes. The record uses `router._last_model` (already set), the category from `classify()`, and `TokenUsage` from the stream. `call_site="router"`.

3. **Tool-use turns use the real model ID.** The literal strings `"claude:sonnet"` at `handlers.py:2149` and `handlers.py:2166` are replaced with `settings.model_complex`. Additionally, a call log record is written for each `stream_with_tools()` invocation with `call_site="tool_use"`.

4. **Proactive pipeline writes records.** `pipeline.py` writes a call log record for every `stream_with_tools()` invocation with `call_site="proactive"`. The `model_used` field on the persisted `ConversationTurn` is also populated with `settings.model_complex`.

5. **Classifier calls are logged.** `MessageClassifier.classify()` writes a record with `call_site="classifier"`, `category=<result>`, and the token counts from that small completion call.

6. **Background agent calls are logged.** Any `ClaudeClient` calls made from `agents/background.py` write records with `call_site="background"`.

7. **Write is non-blocking.** Call log writes use `asyncio.create_task()` — they must not add latency to the response path.

8. **`latency_ms` measures net call time only.** The clock starts immediately before the first API request attempt and stops when the last chunk is received. Time spent sleeping between retries is excluded.

9. **`fallback=1` when Ollama is used.** Set in `_stream_with_fallback()` when the except branch is taken.

10. **No data loss on write failure.** If the DB write fails, it is logged at WARNING level and silently dropped — it must not crash or slow the response path.

---

## Implementation

**Files to modify:**
- `remy/memory/database.py` — add `api_calls` table migration
- `remy/ai/router.py` — write call log after each stream
- `remy/ai/classifier.py` — write call log for classifier calls
- `remy/bot/handlers.py` — fix hardcoded model strings; write call log for tool-use path
- `remy/bot/pipeline.py` — write call log + fix `model_used` for proactive path
- `remy/agents/background.py` — write call log for background calls

**New helper (`remy/memory/database.py` or a new `remy/analytics/call_log.py`):**

```python
async def log_api_call(
    db: DatabaseManager,
    *,
    user_id: int,
    session_key: str,
    provider: str,
    model: str,
    category: str,
    call_site: str,
    usage: TokenUsage,
    latency_ms: int,
    fallback: bool = False,
) -> None:
    """Write one row to api_calls. Fire-and-forget — catches and logs all exceptions."""
    try:
        async with db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO api_calls
                  (user_id, session_key, timestamp, provider, model, category,
                   call_site, input_tokens, output_tokens, cache_creation_tokens,
                   cache_read_tokens, latency_ms, fallback)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, session_key,
                    datetime.now(timezone.utc).isoformat(),
                    provider, model, category, call_site,
                    usage.input_tokens, usage.output_tokens,
                    usage.cache_creation_tokens, usage.cache_read_tokens,
                    latency_ms, int(fallback),
                ),
            )
    except Exception as e:
        logger.warning("Failed to write api_call log: %s", e)
```

**Latency measurement in `ModelRouter._stream_with_fallback()`:**

```python
import time

t0 = time.monotonic()
async for chunk in provider_stream():
    yield chunk
latency_ms = int((time.monotonic() - t0) * 1000)
# then fire-and-forget: asyncio.create_task(log_api_call(...))
```

**Fix hardcoded strings in `handlers.py`:**

```python
# Before (line 2149, 2166):
ConversationTurn(role="assistant", content=asst_serialised, model_used="claude:sonnet")

# After:
ConversationTurn(role="assistant", content=asst_serialised, model_used=f"anthropic:{settings.model_complex}")
```

**DB migration (`database.py`):**

```sql
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_key TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unknown',
    call_site TEXT NOT NULL DEFAULT 'router',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    fallback INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_calls_user_ts ON api_calls(user_id, timestamp);
```

### Notes
- This story depends on `US-analytics-token-capture.md` for `TokenUsage`. Implement token capture first.
- The `session_key` can be obtained from `SessionManager.get_session_key(user_id)` — it is already available at all call sites.
- `category` is available in the router (output of `classify()`). For `tool_use`, `proactive`, and `background` call sites, use `category="tool_use"`, `"proactive"`, or `"background"` respectively since the classifier is not called on those paths.
- The `ConversationAnalyzer.get_stats()` model breakdown currently reads JSONL. After this story it can optionally query `api_calls` instead for more accurate data — but that migration is out of scope here.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Normal router call completes | One row in `api_calls` with correct provider, model, category, tokens, latency |
| Ollama fallback triggered | Row has `fallback=1`, `provider="ollama"`, `model="local"` |
| Tool-use turn (3 iterations) | One row with accumulated token totals, `call_site="tool_use"` |
| Proactive pipeline fires | Row with `call_site="proactive"`, `model_used` populated on `ConversationTurn` |
| Classifier call | Row with `call_site="classifier"`, small token counts |
| DB write fails (e.g., disk full) | WARNING logged, response path unaffected |
| Retry occurs (rate limit, then success) | `latency_ms` excludes sleep time; single row written |
| `model_used` in JSONL for tool-use turns | Contains `f"anthropic:{settings.model_complex}"`, not `"claude:sonnet"` |

---

## Out of Scope

- Migrating existing JSONL `model_used` data into `api_calls` (historical data is not backfilled).
- Querying `api_calls` from analytics commands (handled in `US-analytics-costs-command.md` and `US-analytics-routing-breakdown.md`).
- Time-to-first-token (noted as stretch goal for a future story).
- Per-call cost calculation (handled in `US-analytics-costs-command.md`).
