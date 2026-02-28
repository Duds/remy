# User Story: Self-Diagnostics Suite

## Summary

As Dale, I want to trigger a comprehensive self-diagnostics check by sending the phrase "Are you there, God. It's me Dale." so that I can quickly verify all of Remy's subsystems are functioning correctly.

---

## Background

Remy has grown to include multiple subsystems: database connections, memory/RAG, AI provider connectivity, MCP servers, scheduler, tool registry, and more. When something feels "off", there's currently no single command to verify the health of all components.

The trigger phrase is a reference to Judy Blume's classic novel, repurposed as a memorable diagnostic invocation that won't be accidentally triggered in normal conversation.

**Covers:** OPS-001 (operational health monitoring).
**Depends on:** None — reads existing subsystem state.

---

## Acceptance Criteria

1. **Trigger phrase detection.** The exact phrase "Are you there, God. It's me Dale." (case-insensitive, punctuation-flexible) triggers the diagnostics suite instead of a normal AI response.

2. **Comprehensive subsystem checks.** The diagnostics suite tests:

   | Subsystem | Check |
   |-----------|-------|
   | Database | SQLite connection, schema version, table existence |
   | Memory/Embeddings | Embedding model loaded, vector store accessible |
   | Knowledge Store | Can read/write to knowledge table |
   | Conversation History | Recent conversations retrievable |
   | AI Providers | Anthropic, Mistral, Moonshot, Ollama connectivity (lightweight ping) |
   | Tool Registry | All registered tools loadable, no import errors |
   | MCP Servers | Each configured MCP server responds to ping |
   | Scheduler | Proactive scheduler running, next scheduled task |
   | Configuration | Required env vars present, config valid |
   | File System | Write access to data directory, disk space check |

3. **Pass/Fail status per subsystem.** Each check returns:
   - ✅ Pass with optional detail (e.g., "✅ Database — 3 tables, schema v2")
   - ⚠️ Warning with detail (e.g., "⚠️ Disk space — 2.1 GB remaining")
   - ❌ Fail with error detail (e.g., "❌ Anthropic — API key invalid")

4. **Summary header.** Output begins with overall status:
   - "🟢 All systems operational" (all pass)
   - "🟡 Systems degraded" (some warnings, no failures)
   - "🔴 Systems impaired" (one or more failures)

5. **Timing information.** Each check shows execution time. Total diagnostics time shown at end.

6. **Non-blocking checks.** AI provider pings use short timeouts (5s). A slow/unresponsive provider shows as warning, not failure, unless it's the primary provider.

7. **Version and uptime info.** Output includes:
   - Remy version (from `__version__`)
   - Python version
   - Process uptime
   - Last restart timestamp

8. **Diagnostics logged.** Full diagnostics results written to log file for later review.

9. **Graceful partial failure.** If one check crashes, remaining checks still run. Crashed check shows as ❌ with exception type.

---

## Implementation

**Files to create/modify:**
- `remy/diagnostics/__init__.py` — new module
- `remy/diagnostics/runner.py` — `DiagnosticsRunner` class
- `remy/diagnostics/checks.py` — individual check functions
- `remy/bot/handlers.py` — detect trigger phrase, invoke diagnostics
- `remy/__init__.py` — add `__version__` if not present

**Trigger detection in `handlers.py`:**

```python
import re

DIAGNOSTICS_TRIGGER = re.compile(
    r"are you there,?\s*god\.?\s*it'?s me,?\s*dale\.?",
    re.IGNORECASE
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    
    if DIAGNOSTICS_TRIGGER.search(text):
        await run_diagnostics(update, context)
        return
    
    # ... normal message handling
```

**DiagnosticsRunner structure:**

```python
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Awaitable
import asyncio
import time

class CheckStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    duration_ms: float
    details: dict | None = None

class DiagnosticsRunner:
    def __init__(self, config: Config, db: Database, ...):
        self.checks: list[tuple[str, Callable[[], Awaitable[CheckResult]]]] = [
            ("Database", self._check_database),
            ("Memory/Embeddings", self._check_embeddings),
            ("Knowledge Store", self._check_knowledge),
            ("Conversation History", self._check_conversations),
            ("Anthropic", self._check_anthropic),
            ("Mistral", self._check_mistral),
            ("Moonshot", self._check_moonshot),
            ("Ollama", self._check_ollama),
            ("Tool Registry", self._check_tools),
            ("MCP Servers", self._check_mcp),
            ("Scheduler", self._check_scheduler),
            ("Configuration", self._check_config),
            ("File System", self._check_filesystem),
        ]
    
    async def run_all(self) -> list[CheckResult]:
        results = []
        for name, check_fn in self.checks:
            start = time.perf_counter()
            try:
                result = await asyncio.wait_for(check_fn(), timeout=10.0)
            except asyncio.TimeoutError:
                result = CheckResult(name, CheckStatus.FAIL, "Timed out", 10000.0)
            except Exception as e:
                result = CheckResult(name, CheckStatus.FAIL, f"{type(e).__name__}: {e}", 
                                     (time.perf_counter() - start) * 1000)
            results.append(result)
        return results
```

**Individual check example (`_check_database`):**

```python
async def _check_database(self) -> CheckResult:
    start = time.perf_counter()
    try:
        # Check connection
        async with self.db.connection() as conn:
            # Check tables exist
            tables = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = [row[0] for row in await tables.fetchall()]
            
            expected = {"conversations", "messages", "knowledge", "api_calls"}
            missing = expected - set(table_names)
            
            if missing:
                return CheckResult(
                    "Database", CheckStatus.WARN,
                    f"Missing tables: {missing}",
                    (time.perf_counter() - start) * 1000
                )
            
            return CheckResult(
                "Database", CheckStatus.PASS,
                f"{len(table_names)} tables present",
                (time.perf_counter() - start) * 1000
            )
    except Exception as e:
        return CheckResult(
            "Database", CheckStatus.FAIL,
            str(e),
            (time.perf_counter() - start) * 1000
        )
```

**AI provider ping example (`_check_anthropic`):**

```python
async def _check_anthropic(self) -> CheckResult:
    start = time.perf_counter()
    if not self.config.anthropic_api_key:
        return CheckResult("Anthropic", CheckStatus.WARN, "Not configured", 0)
    
    try:
        # Minimal API call to verify connectivity
        client = anthropic.AsyncAnthropic(api_key=self.config.anthropic_api_key)
        # Use a minimal prompt that costs almost nothing
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}]
        )
        return CheckResult(
            "Anthropic", CheckStatus.PASS,
            f"Connected (haiku responded)",
            (time.perf_counter() - start) * 1000
        )
    except anthropic.AuthenticationError:
        return CheckResult("Anthropic", CheckStatus.FAIL, "Invalid API key",
                          (time.perf_counter() - start) * 1000)
    except Exception as e:
        return CheckResult("Anthropic", CheckStatus.WARN, f"Unreachable: {e}",
                          (time.perf_counter() - start) * 1000)
```

**Sample output format:**

```
🔬 *Remy Self-Diagnostics*

🟢 *All systems operational*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ *Database* — 5 tables present _(12ms)_
✅ *Memory/Embeddings* — Model loaded, 1,247 vectors _(45ms)_
✅ *Knowledge Store* — 89 entries, read/write OK _(8ms)_
✅ *Conversation History* — 312 conversations _(15ms)_
✅ *Anthropic* — Connected (haiku responded) _(892ms)_
✅ *Mistral* — Connected _(654ms)_
⚠️ *Moonshot* — Not configured _(0ms)_
✅ *Ollama* — 3 models available _(23ms)_
✅ *Tool Registry* — 24 tools registered _(5ms)_
✅ *MCP Servers* — 4/4 responding _(156ms)_
✅ *Scheduler* — Running, next task in 4h 23m _(2ms)_
✅ *Configuration* — All required vars present _(1ms)_
✅ *File System* — 45.2 GB free, write OK _(18ms)_

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 *System Info*
  Version: 0.4.2
  Python: 3.12.1
  Uptime: 3d 14h 22m
  Last restart: 25/02/2026 09:15

⏱️ Total diagnostics time: 1.83s
```

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Trigger phrase exact match | Diagnostics run, no AI response |
| Trigger phrase with varied punctuation | Still triggers (e.g., "Are you there God? Its me, Dale") |
| Trigger phrase case variations | Still triggers |
| Similar but non-matching phrase | Normal AI response (e.g., "Are you there?") |
| All subsystems healthy | 🟢 status, all ✅ |
| One subsystem warning | 🟡 status, mix of ✅ and ⚠️ |
| One subsystem failure | 🔴 status, shows ❌ with error |
| Check times out | Shows ❌ "Timed out" |
| Check throws exception | Shows ❌ with exception type, other checks continue |
| Database unavailable | ❌ Database, other checks still run |
| No AI providers configured | All show ⚠️ "Not configured" |

---

## Out of Scope

- Automated periodic health checks (separate story for scheduled diagnostics).
- Alerting/notifications on degraded status (separate story).
- Historical diagnostics comparison (separate story).
- Self-healing/auto-recovery actions (separate story).
- Detailed performance profiling (this is health check, not profiling).

---

## Notes

- The trigger phrase should be documented in the user-facing help/commands list.
- Consider adding `/diagnostics` as an alternative trigger for discoverability.
- AI provider pings cost a tiny amount — Haiku with 1 token output is ~$0.000004.
- MCP server checks should use the existing ping/health endpoints if available.
- Disk space warning threshold: < 5 GB remaining.
