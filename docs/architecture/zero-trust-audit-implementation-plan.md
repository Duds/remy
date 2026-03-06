# Zero-Trust Audit — Implementation Plan

**Source:** [zero-trust-audit.md](./zero-trust-audit.md)  
**Date:** 06/03/2025  
**Goal:** Implement all audit recommendations to raise System Health Score from 7/10 and clear the kill list.

---

## Overview

| # | Recommendation | Priority | Effort | Dependencies |
|---|----------------|----------|--------|--------------|
| 1 | Remove orphan `remy/ai/claude_code.py` | P0 (kill list) | Small | None |
| 2 | Resolve `count_tokens()` blocking risk | P1 | Small | None |
| 3 | Document or refine circuit breaker behaviour | P2 | Small–Medium | None |
| 4 | Migrate tool_registry imports and remove shim | P1 | Medium | None |

---

## 1. Remove Orphan `remy/ai/claude_code.py` (Kill List)

**Audit:** `remy/ai/claude_code.py` defines `ClaudeCodeRunner` and is not imported anywhere. The tool lives in `remy/ai/tools/claude_code.py` and uses `asyncio.create_subprocess_exec` directly; it does not use `ClaudeCodeRunner`.

### Steps

1. **Confirm no external references**
   - Grep repo for `remy.ai.claude_code` or `from remy.ai import claude_code` (only docs/TODO reference the file or runner).
   - Confirm no dynamic imports or string references to `remy/ai/claude_code.py`.

2. **Delete the file**
   - Remove `remy/ai/claude_code.py`.

3. **Update references**
   - **TODO.md:** Line ~61 says “ClaudeCodeRunner removed entirely from production path”. Either leave as-is (it will be true) or reword to “ClaudeCodeRunner removed (orphan deleted per zero-trust audit).”
   - No code changes required; no production code imports this module.

4. **Verify**
   - Run full test suite; `tests/test_tools/test_claude_code.py` tests the tool in `remy/ai/tools/claude_code.py`, not the orphan.
   - Optional: add a short note in the audit or changelog that the kill-list item was completed.

### Acceptance criteria

- [ ] `remy/ai/claude_code.py` no longer exists.
- [ ] All tests pass.
- [ ] No remaining imports of `remy.ai.claude_code` or `ClaudeCodeRunner` in production code.

---

## 2. Resolve `count_tokens()` Blocking Risk

**Audit:** `remy/utils/tokens.py` has a synchronous `count_tokens()` that uses `anthropic.Anthropic()` and `client.count_tokens()`. If ever called from async code it would block the event loop. It is currently **not** used in any production path; only the module’s fallback uses it internally.

### Option A — Remove (recommended)

- **Action:** Remove `count_tokens()`; keep only `estimate_tokens()` and `format_token_count()`.
- **Rationale:** Production uses `estimate_tokens()` only; no call site for `count_tokens()`. Simplest and removes latent risk.
- **Steps:**
  1. Delete the `count_tokens()` function from `remy/utils/tokens.py`.
  2. Update module docstring to describe only character-based estimation.
  3. Grep for any `count_tokens` usage (docs/backlog, etc.) and update or remove references.
  4. Run tests; add or adjust tests if any previously targeted `count_tokens()`.

### Option B — Make async-safe and keep

- **Action:** Implement an async wrapper that runs the sync implementation in a thread (e.g. `asyncio.to_thread()`), and document that the sync `count_tokens()` must not be called from async code.
- **Steps:**
  1. Add `async def count_tokens_async(...)` that calls `asyncio.to_thread(count_tokens, ...)`.
  2. In docstring and comments, state: “Do not call `count_tokens()` from async code; use `count_tokens_async()`.”
  3. If any future code needs token counting from async path, use only `count_tokens_async()`.

### Recommendation

Prefer **Option A** unless you have a concrete need for exact SDK token counts; the audit states production uses `estimate_tokens()` only.

### Acceptance criteria

- [ ] Either `count_tokens()` is removed, or it is documented as sync-only and an async-safe path exists.
- [ ] No sync Anthropic client call can run on the event loop from production async code.
- [ ] Tests and docs updated as needed.

---

## 3. Circuit Breaker: Document or Refine Behaviour

**Audit:** All failures (e.g. 429 rate limit and connection/5xx) are treated alike; the circuit does not distinguish “rate limit” vs “Ollama down”. Recommendation: optionally add error-type awareness and/or document current behaviour.

### 3.1 Document current behaviour (minimum)

- **Action:** Add operator-facing documentation so “open” is clearly defined.
- **Steps:**
  1. In `remy/utils/circuit_breaker.py`, expand the module docstring (and optionally `CircuitBreaker` class docstring) to state:
     - Circuit “open” means “repeated failures of any kind” (rate limit, connection refused, 5xx, etc.).
     - Recovery is time-based (`recovery_timeout`); no distinction between 429 retry-after and other failures.
     - Ollama is not behind a circuit in the router (it is the fallback when a provider’s circuit is open or the provider fails).
  2. Optionally add a short `docs/architecture/` or `docs/operations/` note (e.g. “Circuit breakers”) referencing this behaviour.

### 3.2 Optional: Error-type awareness

- **Action:** Differentiate 429/529 (retry-after) from connection/5xx so that:
  - Rate limits could use a shorter recovery or a dedicated “rate-limit” state.
  - Operators can reason about “open” as “rate limited” vs “unavailable”.
- **Steps:**
  1. In `CircuitBreaker._record_failure()`, inspect the exception (e.g. `getattr(e, 'status_code', None)` or `getattr(e, 'response', None)` for HTTP errors).
  2. Classify as “rate_limit” (429/529) vs “connection/5xx” (or similar).
  3. Options:
     - **A:** Use a shorter `recovery_timeout` for rate_limit (e.g. from a new `rate_limit_recovery_timeout` attribute).
     - **B:** Add a separate “rate limit” state and transition logic (e.g. open for N seconds then half-open, independent of failure_threshold).
  4. Log and/or expose in `get_stats()` which kind of failure last occurred (optional).
  5. Document the new behaviour in the same place as 3.1.
- **Scope:** Optional; only if product/ops need finer control. Document-first (3.1) satisfies the audit recommendation.

### Acceptance criteria

- [ ] Current circuit behaviour is documented (what “open” means, no error-type distinction, Ollama not behind breaker).
- [ ] If error-type awareness is implemented: 429/529 vs connection/5xx are handled differently and documented; tests added.

---

## 4. Unify Tool Registry Surface and Remove Deprecated Shim

**Audit:** All imports should use `remy.ai.tools`; then delete `remy/ai/tool_registry.py`.

### 4.1 Production code — change imports

Replace:

```python
from remy.ai.tool_registry import ToolRegistry
# or
from remy.ai.tool_registry import ToolRegistry, TOOL_SCHEMAS
# or
from ...ai.tool_registry import ToolRegistry
# etc.
```

with:

```python
from remy.ai.tools import ToolRegistry
# or
from remy.ai.tools import ToolRegistry, TOOL_SCHEMAS
# (use same relative depth as before: .. or ... as appropriate)
```

**Files to update (production):**

| File | Change |
|------|--------|
| `remy/main.py` | `from .ai.tool_registry` → `from .ai.tools` |
| `remy/bot/handlers/chat.py` | `from ...ai.tool_registry` → `from ...ai.tools` |
| `remy/bot/handlers/core.py` | `from ...ai.tool_registry` → `from ...ai.tools` |
| `remy/bot/handlers/privacy.py` | `from ...ai.tool_registry` → `from ...ai.tools` |
| `remy/bot/handlers/__init__.py` | `from ...ai.tool_registry` → `from ...ai.tools` |
| `remy/bot/pipeline.py` | `from ..ai.tool_registry` → `from ..ai.tools` |
| `remy/scheduler/proactive.py` | `from ..ai.tool_registry` → `from ..ai.tools` |
| `remy/diagnostics/runner.py` | `from ..ai.tool_registry` → `from ..ai.tools` |

**Note:** `remy/diagnostics/logs.py` has a comment “Keep the old private name as an alias so tool_registry.py still works”. After migration, update or remove that comment so it no longer references `tool_registry.py`.

### 4.2 Tests — change imports

| File | Change |
|------|--------|
| `tests/test_tool_registry.py` | `from remy.ai.tool_registry` → `from remy.ai.tools` |
| `tests/test_memory_consolidation.py` | `from remy.ai.tool_registry` → `from remy.ai.tools` (all 3 occurrences) |
| `tests/test_file_index.py` | `from remy.ai.tool_registry` → `from remy.ai.tools` (all 2 occurrences) |
| `tests/test_proactive_memory.py` | `from remy.ai.tool_registry` → `from remy.ai.tools` |

### 4.3 Remove the shim

1. After all imports are updated, delete `remy/ai/tool_registry.py`.
2. Run full test suite and smoke checks.
3. Grep for `tool_registry` (as module name) and `remy.ai.tool_registry` to ensure no remaining references.

### Acceptance criteria

- [ ] No production or test file imports from `remy.ai.tool_registry`.
- [ ] `remy/ai/tool_registry.py` is deleted.
- [ ] All tests pass; no deprecation warnings for `remy.ai.tool_registry`.
- [ ] Single canonical surface: `remy.ai.tools` for `ToolRegistry` and `TOOL_SCHEMAS`.

---

## Execution Order

1. **First:** Item 1 (remove orphan) — quick win, clears kill list.
2. **Second:** Item 2 (`count_tokens`) — small, removes latent risk.
3. **Third:** Item 4 (tool_registry migration) — more files but mechanical; unblocks deletion of shim.
4. **Fourth:** Item 3 (circuit breaker docs, and optionally error-type logic) — improves operability and aligns with audit.

Items 1, 2, and 4 have no dependency on each other and could be done in parallel if desired; 3 is independent.

---

## Done Criteria (Audit)

- Kill list: **`remy/ai/claude_code.py`** removed.
- Hot spot: **`count_tokens()`** never used in async path (removed or made async-safe and documented).
- Circuit breaker: behaviour **documented** (and optionally refined with error-type awareness).
- Refactor: **single tool registry surface**; `remy/ai/tool_registry.py` removed and all call sites use `remy.ai.tools`.

---

*End of implementation plan.*
