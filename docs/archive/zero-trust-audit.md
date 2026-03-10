# Zero-Trust Critical Audit — Remy

**Role:** Lead Software Architect & Performance Engineer (agentic AI, FastAPI concurrency, hybrid Ollama + Cloud).  
**Date:** 06/03/2025  
**Scope:** Architectural rot, performance bottlenecks, integration orphans.

---

## 1. Model Orchestration & Latency (Hybrid Stack)

### 1.1 Async Event Loop

**Finding: Largely non-blocking; one latent risk.**

- **Claude / Mistral / Moonshot / Ollama:** All use `AsyncAnthropic` or `httpx.AsyncClient` / `client.stream()`; no synchronous HTTP in the hot path.
- **Classifier** (`remy/ai/classifier.py`): Heuristic-only, no API calls; cache is in-process. No event-loop blocking.
- **Embeddings** (`remy/memory/embeddings.py`): `sentence-transformers` is lazy-loaded in `_load_model()`; `embed()` uses `loop.run_in_executor(None, _do_encode)`. Non-blocking.
- **Voice transcriber** (`remy/voice/transcriber.py`): Model lazy-loaded; `_transcribe_sync()` runs in executor. Non-blocking.
- **Token counting** (`remy/utils/tokens.py`): Production code uses **`estimate_tokens()`** only (character-based). **`count_tokens()`** uses a **synchronous** `anthropic.Anthropic()` client and `client.count_tokens()`; if ever used in an async path it would block. Currently **not called** from any production path; only from the module’s own fallback. **Recommendation:** Either remove `count_tokens()` or implement it with `asyncio.to_thread()` / executor if needed.

**Verdict:** No synchronous calls in `remy/ai/` that currently freeze the event loop. Single latent risk: `count_tokens()` if introduced into the hot path.

### 1.2 Circuit Breaking

**Finding: Single policy; no distinction between “Ollama down” vs “Cloud rate limit”.**

- **`remy/utils/circuit_breaker.py`:** Implements CLOSED → OPEN → HALF_OPEN with configurable threshold and recovery. Used per **provider name** (`claude`, `claude_desktop`, `mistral`, `moonshot`); Ollama is **not** behind a circuit breaker in the router — it’s the fallback when a provider’s circuit is open or the provider fails.
- **Issue:** All failures are treated alike. A **rate limit** (429) and an **Ollama crash** (connection refused) both increment the same failure count and can open the circuit. For Cloud APIs, opening after N failures is correct; for a local Ollama that was restarted, a 60s recovery is fine. The missing piece is **differentiating 429/529 (retry-after)** from **connection/5xx** so that:
  - Rate limits could use a shorter recovery or a dedicated “rate-limit” state.
  - Ollama could use a separate breaker (or no breaker, as today) so that “Ollama down” doesn’t affect Cloud circuit state (it doesn’t today, but the Cloud breaker doesn’t distinguish error type).

**Recommendation:** Optionally add error-type awareness (e.g. 429/529 vs connect/5xx) and consider a separate circuit or no circuit for Ollama fallback; document current behaviour so operators know “open” means “any repeated failure”.

### 1.3 Token Efficiency

**Finding: Efficient; no over-tokenizing or redundant model calls for routing.**

- **Classifier:** Heuristic-only (regex + length), no extra API call. Cached (TTL 300s, max 256 entries). No redundant model call for “simple routing.”
- **Token usage in codebase:** Compaction and injector use **`estimate_tokens()`** (character-based). No redundant `count_tokens()` calls.

**Verdict:** Token efficiency is good; classifier design avoids the 300–800 ms penalty noted in-code.

---

## 2. Structural Integrity & “Stitching”

### 2.1 Module Redundancy (AI Tools vs Telegram Handlers)

**Finding: Duplication is by design (two entry points, shared backends).**

- **Handlers** (`remy/bot/handlers/`): Telegram commands (e.g. `/calendar`, `/email`, `/goals`) and message handling; they call the same backing services (Google clients, `goal_store`, `plan_store`, etc.) and sometimes **call into the tool registry** (e.g. `tool_registry.dispatch("check_status", {}, user_id)` in chat, `tool_registry.dispatch("get_goals", ...)` in core).
- **Tools** (`remy/ai/tools/`): Same capabilities exposed as Anthropic function-calling tools; executors (e.g. `exec_calendar_events`, `exec_read_emails`) use the same `ToolRegistry`-injected clients/stores.
- **Conclusion:** There is **no duplicated business logic**; there are two surfaces (Telegram vs tool names) and one implementation per capability. Handlers that need “status” or “goals” reuse the tool dispatch. This is acceptable; no kill-list item here.

### 2.2 Namespace / Orphan: `remy/ai/claude_code.py` vs `remy/ai/tools/claude_code.py`

**Finding: `remy/ai/claude_code.py` is an orphan.**

- **`remy/ai/claude_code.py`:** Defines **`ClaudeCodeRunner`** — runs `claude --print --no-ansi` as a subprocess and streams stdout. **Not imported anywhere** in the repo (only `remy/ai/tools/claude_code.py` and tests reference the **tool** `exec_run_claude_code`).
- **`remy/ai/tools/claude_code.py`:** Defines **`exec_run_claude_code`** (tool); uses `asyncio.create_subprocess_exec` directly with task/context/repo_path; **no use of ClaudeCodeRunner**.
- **Verdict:** `remy/ai/claude_code.py` is **dead code**. Either the tool was intended to use `ClaudeCodeRunner` and was reimplemented inline, or the runner was superseded. **Kill list:** remove or repurpose `remy/ai/claude_code.py` after confirming no external use.

### 2.3 Orphan / Disconnected Files

- **`remy/config_audit.py`:** **Not an orphan.** Invoked from `main.py` via `log_startup_config()` at startup. Wired.
- **`remy/ai/tool_registry.py`:** **Deprecated shim.** Re-exports `ToolRegistry` and `TOOL_SCHEMAS` from `remy.ai.tools` and emits a DeprecationWarning. `main.py`, `bot/handlers`, `bot/pipeline.py`, `scheduler/proactive.py`, `diagnostics/runner.py` still import from `remy.ai.tool_registry`. Intended migration: import from `remy.ai.tools` and delete the shim. **Not an orphan;** technical debt.

---

## 3. Dependency & Environment Health

### 3.1 Shadow Dependencies

**Finding: Heavy libs are lazy or executor-bound; no top-level torch/sentence-transformers in hot path.**

- **requirements.txt:** Includes `sentence-transformers`, `faster-whisper`, `pymupdf`, etc. No `torch` listed explicitly (pulled by sentence-transformers).
- **`remy/memory/embeddings.py`:** `sentence_transformers` imported only inside `_load_model()`, which is called from the executor. No top-level import of torch/sentence-transformers.
- **`remy/memory/` (goals, facts, knowledge):** Use `EmbeddingStore` and `ClaudeClient`; no direct torch/sentence-transformers import at module top.
- **`remy/google/`:** Uses `google-api-python-client`, `google-auth-*`; no heavy ML libs at top level.

**Verdict:** No inappropriate top-level heavy imports; embeddings and voice are lazy and executor-isolated.

### 3.2 Docker

**Finding: Main Dockerfile is well-optimised; relay_mcp is minimal.**

- **`Dockerfile` (main app):** Multi-stage; builder pre-downloads sentence-transformers model; runtime is slim with ffmpeg, curl, git; non-root user; HEALTHCHECK; env for ORT/ONNX and cache dirs. No obvious bloat.
- **Ollama:** Not run inside the Remy container; Remy connects to Ollama via `ollama_base_url` (e.g. localhost or a sidecar). No localhost-loopback “bridge” in the image — connection is normal HTTP to a host or another container. Efficient.
- **`relay_mcp/Dockerfile`:** Single stage, minimal deps (`mcp[cli]`, `pydantic`), small footprint. No overlap with main app’s heavy stack.

**Verdict:** Docker is in good shape; no kill-list items here.

---

## 4. Technical Debt & Placeholders

### 4.1 Mock Hunt

**Finding: No test mocks leaked into `remy/`.**

- Grep for Mock/mock in `remy/` (excluding tests): only schema/doc references (e.g. “TODO.md” in tool descriptions). Test-only mocks live under `tests/` (e.g. `tests/test_tools/test_claude_code.py`). **No production mock leakage.**

### 4.2 Placeholder Logic

- **TODO/FIXME:** Present in config (e.g. SOUL paths, compaction thresholds) and tool schema strings (user-facing hints). No “bypass primary agent” logic found; SOUL load and compaction are part of the intended flow.
- **Compact SOUL:** `config.py` prefers `SOUL.compact.md` when `soul_prefer_compact` is True; this is a documented feature, not a hidden bypass.
- **`exec_compact_conversation` (tool):** Returns a message asking the user to use `/compact`; it does not perform compaction itself (conversation store/compaction not available to the tool). Intentional; not a placeholder that bypasses logic.

**Verdict:** No dangerous placeholders or bypasses.

---

## 5. Data & Memory Pipeline

### 5.1 Consistency (remy/memory vs relay_mcp)

**Finding: No excessive serialisation; clean separation.**

- **remy/memory/database.py:** Remy’s SQLite (e.g. `remy.db`) — aiosqlite, used for conversations, goals, plans, embeddings, jobs, etc.
- **relay_mcp:** Own schema in its own DB file (e.g. `relay.db`); sync `sqlite3` in the MCP server.
- **remy/relay/client.py:** Uses **aiosqlite** to write to the **same relay schema** (messages, tasks, shared_notes). When Remy and relay_mcp share a volume, they can point to the same `relay.db`; Remy writes via `relay/client`, MCP reads/serves. Data is not “serialised/deserialised” between Remy and relay_mcp beyond normal SQL; no duplicate serialisation layer.

**Verdict:** Stitch is appropriate; no excessive (de)serialisation.

### 5.2 Heartbeat Integrity

**Finding: No memory leak or infinite loop.**

- **`remy/scheduler/heartbeat.py`:** `run_heartbeat_job()` is invoked once per scheduler tick (e.g. cron `*/30 * * * *`). It: checks quiet hours, gets chat_id/user_id, runs `HeartbeatHandler.run()`, writes **one** row to `heartbeat_log` in a single `db.get_connection()` context, commits, emits hooks. No self-rescheduling, no recursion, no unbounded accumulation of state.
- **HeartbeatHandler:** Gathers context (goals, plans, calendar, email, etc.), calls Claude once, enqueues one message if not HEARTBEAT_OK. No loop.

**Verdict:** Safe in a containerised environment.

---

## Deliverables

### System Health Score: **7 / 10**

**Rationale:**

- **Strengths:** Async-first AI and I/O, heuristic classifier, embeddings/voice in executor, circuit breakers in place, Docker and deps disciplined, heartbeat and relay data flow sane. No production mocks or bypass placeholders.
- **Deductions:** One **orphan file** (`remy/ai/claude_code.py`); **circuit breaker** does not distinguish rate-limit vs connection failure; **deprecated shim** (`remy/ai/tool_registry.py`) still in use; **latent** blocking risk in `count_tokens()` if ever used in async path. Not “brutal 4” — the system is production-capable and structured — but not “9” until the orphan is removed, circuit behaviour is documented or refined, and the tool_registry migration is done.

---

### The “Kill List”

| Item | Action |
|------|--------|
| **`remy/ai/claude_code.py`** | Remove (orphan). The tool lives in `remy/ai/tools/claude_code.py` and does not use `ClaudeCodeRunner`. Confirm no external references, then delete. |

**Do not delete:** `remy/config_audit.py` (used at startup). **Do not delete** `remy/ai/tool_registry.py` until call sites are migrated to `remy.ai.tools`.

---

### Critical Performance Hotspots

| Location | Issue | Severity |
|----------|--------|----------|
| **`remy/utils/tokens.py`** `count_tokens()` | Sync `anthropic.Anthropic()` and `client.count_tokens()`; would block event loop if called from async code. Currently unused in hot path. | **Low** (latent) |
| **`remy/ai/router.py`** `_stream_with_fallback()` | Holds lock only around state checks; the actual `await claude.stream_message(...)` is outside the breaker lock. No issue. Long-running stream can delay other requests sharing the same event loop — normal for streaming. | **N/A** |
| **`remy/memory/embeddings.py`** `embed()` | Uses `run_in_executor` and semaphore (2); safe. First call triggers model load under lock — one-off startup cost. | **N/A** |
| **`remy/bot/handlers/chat.py`** | Compaction check after assistant turn uses `get_compaction_service()` and `check_and_compact()`; compaction uses Claude and token estimation. Bounded by config (token/turn thresholds). | **Monitor** (expected cost) |

**No “specific line” that will definitely spike latency** beyond normal model/network behaviour; the only fixable hotspot is ensuring **`count_tokens()` is never used in the async path** (or is made async-safe).

---

### Architectural Refactor: One Recommendation

**Unify Tool Registry Surface and Remove the Deprecated Shim**

- **Current state:** Two ways to get `ToolRegistry`: `remy.ai.tool_registry` (deprecated shim) and `remy.ai.tools` (canonical). `main.py` and several core modules still import from `remy.ai.tool_registry`.
- **Recommendation:**  
  - **Agent-to-tool mapping:** Keep a **single** definition of tools and dispatch in `remy/ai/tools/` (schemas in `schemas.py`, registry and dispatch in `registry.py`, executors in per-domain modules).  
  - **Refactor:** Change all imports from `remy.ai.tool_registry` to `remy.ai.tools` (e.g. `from remy.ai.tools import ToolRegistry, TOOL_SCHEMAS`). Then delete `remy/ai/tool_registry.py`.  
  - **Benefit:** One place for “what tools exist” and “how they’re dispatched”; no confusion between `remy/ai/tool_registry.py` and `remy/ai/tools/registry.py`; cleaner agent-to-tool mapping for future tool additions.

---

*End of audit.*
