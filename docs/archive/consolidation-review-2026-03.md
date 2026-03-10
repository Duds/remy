# Remy — Structural Consolidation Review
**Date:** March 2026
**Scope:** Full architectural review of the Telegram-based AI agent
**Purpose:** Stabilise, unify, and remove accidental complexity

---

## 1. Architectural Diagnosis

### 1.1 What the system is

Remy is a single-user Telegram-based personal AI assistant. Its core loop is:

1. Receive a Telegram message
2. Load conversation history + inject memory context
3. Call Claude with Anthropic native tool use
4. Execute tool calls (calendar, email, files, goals, reminders, etc.)
5. Stream the response back to Telegram
6. Persist conversation and extract facts/goals asynchronously

Everything else is infrastructure around this loop: scheduling, multi-model routing, sub-agent orchestration, delivery guarantees, and integrations.

### 1.2 Observed architectural inconsistencies

#### (a) Five overlapping execution abstractions

There are five separate classes that all mean "run something and deliver a result to Telegram":

| Class | Location | Responsibility |
|---|---|---|
| `BackgroundTaskRunner` | `agents/background.py` | Fire-and-forget with job tracking |
| `SubagentRunner` | `agents/subagent_runner.py` | Wraps `BoardOrchestrator` for background delivery |
| `BoardOrchestrator` | `agents/orchestrator.py` | Runs 5 named sub-agents sequentially |
| `TaskOrchestrator` | `agents/task_orchestrator.py` | Delegates to `TaskRunner` workers; synthesises results |
| `TaskRunner` | `agents/runner.py` | Manages asyncio worker pool with DB persistence |

`SubagentRunner` is a thin wrapper around `BoardOrchestrator` that exists only to call `BackgroundTaskRunner.run()`. It adds no logic and should not exist as a separate class. `TaskOrchestrator` and `TaskRunner` are a separate orchestration system (SAD v10 §11) that partially overlaps with `BoardOrchestrator` — the `TaskRunner` even has a `board` worker type that internally calls `BoardOrchestrator`, creating a double-wrapping. `TaskOrchestrator` and `TaskRunner` exist in the codebase but are never instantiated in `main.py`; `ToolRegistry.task_runner` is always `None`. The `run_board` tool falls back to inline `BoardOrchestrator` execution.

#### (b) Dual memory stores that are both active

```
KnowledgeStore     ← described as "unified" replacement
FactStore          ← legacy; still being written to
GoalStore          ← legacy; still being written to
```

`main.py` creates all three. `ToolRegistry` receives all three. `make_handlers()` receives both `fact_store` and `goal_store` alongside `knowledge_store`. The comment in `main.py` says `KnowledgeStore` supersedes `FactStore`+`GoalStore` for *new* data, but both code paths remain active, leaving an incomplete migration with no clear cutover point.

#### (c) The model router is bypassed on the primary path

`ModelRouter` classifies messages (routine, reasoning, coding, summarisation, persona, safety) and routes to Claude, Mistral, Moonshot, or Ollama accordingly. However, the main message handler (`chat.py`) calls `claude_client.stream_with_tools()` directly — bypassing the router entirely. The router is only used as a fallback when `tool_registry` is `None`, which does not happen in production. The router's multi-provider classification logic is therefore effectively dead code in normal operation.

Additionally, `task_orchestrator.py` creates its own `anthropic.AsyncAnthropic` client directly, bypassing both `ClaudeClient` and the router, so that call site has no circuit breaking, logging, token tracking, or fallback.

#### (d) Explosion of dependencies at the wiring layer

`make_handlers()` accepts 25 parameters. `ProactiveScheduler.__init__()` takes 18 dependencies. `ToolRegistry.__init__()` takes 23 keyword arguments. `main.py` instantiates 16 memory-related objects before startup is complete. This wiring complexity makes the system very difficult to reason about and to test — a change to one component may require threading a new argument through 4–5 layers.

#### (e) The `_late` dict anti-pattern

A mutable `dict` named `_late` is used to late-bind `proactive_scheduler`, `outbound_queue`, `bot`, and `diagnostics_runner` after `post_init`. This is a workaround for circular initialisation dependencies. It is fragile (no type safety, silently returns `None` on miss) and obscures what the real dependency graph is.

#### (f) Duplicate command/tool surface

Every Google Workspace integration has both a Telegram slash command *and* a native tool:

- `/gmail-unread` + `read_emails` tool
- `/calendar` + `calendar_events` tool
- `/contacts` + `search_contacts` tool
- `/goals` + `get_goals` tool
- `/plans` + `list_plans` tool
- `/search` + `web_search` tool

This means feature behaviour is implemented twice (command handler + tool executor), and parity is maintained manually. Users also have two ways to invoke the same capability with potentially different formatting or behaviour.

#### (g) Five nearly identical proactive system prompt functions

`pipeline.py` contains five functions with the same shape: `{SOUL.md} + "---" + scenario text + JSON context`:

- `_reminder_system_prompt(label)`
- `_briefing_system_prompt(context)`
- `_evening_checkin_system_prompt(context)`
- `_afternoon_checkin_system_prompt(context)`
- `_afternoon_check_system_prompt(context)`

These are not substantially different from each other and could be collapsed into a single parameterised template.

#### (h) Relay accessed via two different pathways

The relay MCP server (`relay_mcp/server.py`) is accessed via:
1. `remy/relay/client.py` — direct Python calls to relay functions
2. `remy/ai/tools/relay.py` — Anthropic tool wrappers that call the same relay client

Both exist, both are active, and the tool wrappers are thin pass-throughs. There is no reason for both layers.

#### (i) Dead or vestigial client code

`MistralClient` and `MoonshotClient` are instantiated unconditionally in `main.py`; `ClaudeDesktopClient` is optional in `ModelRouter` but `main.py` never passes it. Since the router is bypassed in the primary path, all three add startup cost with minimal benefit in production.

---

## 2. Target System Architecture

### 2.1 Conceptual model

Remy is a **single-user agentic loop** with five concerns:

```
┌──────────────────────────────────────────────────────────┐
│  Telegram Interface                                       │
│  (inbound messages, commands, callbacks, streaming out)   │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  Agent Core                                               │
│  (session, memory injection, Claude call, tool loop)      │
└──────┬─────────────────┬──────────────────────────────────┘
       │                 │
┌──────▼──────┐  ┌───────▼──────────────────────────────────┐
│  Memory     │  │  Tools                                    │
│  (SQLite:   │  │  (calendar, email, files, web, relay,     │
│  knowledge, │  │   goals, plans, counters, git, Python,    │
│  convo,     │  │   board, analytics, automations)          │
│  embeddings)│  └──────────────────────────────────────────┘
└─────────────┘
┌──────────────────────────────────────────────────────────┐
│  Scheduler                                                │
│  (proactive triggers → Agent Core loop)                   │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  Integrations                                             │
│  (Google Workspace, Ollama fallback, Relay MCP)           │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Component boundaries

| Component | Responsibility | Does NOT own |
|---|---|---|
| `telegram_interface` | Receive updates, dispatch to agent, send/stream replies | Business logic |
| `agent_core` | Session lock, memory injection, Claude call, tool loop | Tool implementation |
| `memory` | Persist and retrieve knowledge, conversations, goals, plans | AI calls |
| `tools` | Implement tool capabilities (one file per domain) | Telegram interaction |
| `scheduler` | Fire proactive triggers at the right time | Building content |
| `integrations` | Google API clients, relay client | Tool dispatch |
| `config` | Settings, SOUL.md, feature flags | Everything else |

### 2.3 Architectural principles

1. **Single execution path.** All messages (user-initiated and proactive) pass through the same agentic loop (`stream_with_tools`). No parallel paths.

2. **Commands are thin.** Slash commands validate input and call the agentic loop or dispatch a tool directly. They do not contain business logic.

3. **One memory store.** `KnowledgeStore` is the single source of truth. `FactStore` and `GoalStore` are read adapters during migration, not write targets.

4. **Tools are the capability surface.** Every user-visible capability is a tool. Commands that duplicate tool functionality are removed or become one-liners that invoke the tool.

5. **Explicit dependency injection.** No mutable late-binding dicts. Components receive what they need at construction. If circular dependencies exist, extract an interface.

6. **One background execution primitive.** `BackgroundTaskRunner` is the single pattern for fire-and-forget work. Other orchestration wrappers (`SubagentRunner`, `TaskRunner`, `TaskOrchestrator`) either merge into it or are removed.

7. **Observability by default.** All Claude calls go through `ClaudeClient`. No direct `anthropic.AsyncAnthropic` usage outside `ClaudeClient`.

---

## 3. Telegram Interaction Model

### 3.1 Observed problems

- `/help` lists 50+ commands. Users cannot discover or remember the surface.
- There are two ways to invoke most capabilities: a command and natural language via tools.
- Some commands (`/relay`) parse JSON internally, duplicating tool logic.
- Proactive message UX is inconsistent: some have snooze buttons, some have calendar buttons, some have nothing.
- The working/typing indicator logic is spread across `chat.py`, `pipeline.py`, `background.py`, and `streaming.py`.

### 3.2 Proposed model

**Principle:** Remy is primarily a conversational agent. Commands are shortcuts for power users, not the main interface. Reduce the command surface to what genuinely benefits from an explicit trigger.

#### Core commands (keep as explicit triggers)

```
/start          — greet and show brief capability overview (3–4 lines, not 50+)
/cancel         — stop current task
/briefing       — trigger morning briefing now
/status         — system health summary
/setmychat      — register proactive message target chat
/compact        — compress conversation history
/delete_conversation — privacy: clear history
```

#### Domain commands (keep; they benefit from explicit invocation)

```
/board <topic>  — Board of Directors analysis (long-running; clearly async)
/diagnostics    — comprehensive self-check
/logs [filter]  — raw log access
/stats [period] — usage stats
/costs          — API cost summary
```

#### Remove from commands; keep only as tools (accessed via natural language)

Everything else: goals, plans, calendar, email, contacts, files, web, relay, automations, grocery, bookmarks, research, retrospective, consolidate, etc. These work better as natural language — "what's on my calendar tomorrow?" beats `/calendar 1`.

#### Consistent feedback patterns

| Scenario | Behaviour |
|---|---|
| Short response (< 2s) | Stream directly; no placeholder |
| Long-running task | Send `_Working…_` placeholder; edit in place with result |
| Background task | Send `_Starting <task>…_`; send new message on completion |
| Tool call during streaming | Edit message to `_⚙️ Using <tool>…_`; restore streaming |
| Error | Edit placeholder to brief user-facing error; log full error |
| Proactive trigger | Send proactive message; attach action buttons if applicable |

#### Proactive message consistency

All proactive triggers (reminder, morning briefing, evening check-in, afternoon check-in) should produce the same output structure: a contextual message from Remy with zero or more action buttons. The system prompt is the only variable; the delivery mechanism is identical.

---

## 4. Feature Rationalisation

### 4.1 Keep (core value)

- Agentic loop with Anthropic tool use (`stream_with_tools`)
- Memory system: conversations, knowledge/facts/goals (unified), plans, counters
- Google Workspace integration (Gmail, Calendar, Docs, Contacts)
- Proactive scheduler: morning briefing, reminders, evening check-in
- File system tools (read, write, find, RAG index)
- Web search and research synthesis
- Relay MCP (multi-agent communication with cowork)
- Board of Directors (`BoardOrchestrator` with 5 sub-agents)
- Voice transcription
- Outbound message queue (crash-safe delivery)
- Analytics: API cost tracking, call logging, goal status

### 4.2 Merge / simplify

| What | Into |
|---|---|
| `SubagentRunner` | `BackgroundTaskRunner` directly; remove the wrapper class |
| `TaskOrchestrator` + `TaskRunner` | Either wire them properly or remove; don't maintain dead orchestration code |
| `FactStore` + `GoalStore` (write paths) | `KnowledgeStore` — complete the migration, remove legacy write paths |
| 5 proactive system prompt functions | Single `build_proactive_system_prompt(scenario, context)` |
| `_late` dict | Named dataclass or initialisation order fix |
| Duplicate command/tool pairs | Commands call tool executors; no duplicate logic |
| `_call_claude()` in `task_orchestrator.py` | Replace with `ClaudeClient` call |

### 4.3 Deprecate / remove

| What | Reason |
|---|---|
| `ModelRouter` (multi-provider classification) | Bypassed in primary path; adds complexity without benefit |
| `MessageClassifier` | Only used by router |
| `ClaudeDesktopClient` | Experimental; adds fragile subprocess dependency |
| `MistralClient` | Only used by bypassed router |
| `MoonshotClient` | Only used by bypassed router |
| Ollama as a fallback in the primary agentic loop | The tool loop requires structured tool use; Ollama's output is unreliable here. Retain for explicit `/ollama` escape hatch if needed. |
| 40+ slash commands | Collapse to ≤ 15; remainder accessible via natural language |
| `config_audit.py` | Inline into logging setup or `main.py` startup block |

### 4.4 Evaluate

- `HeartbeatHandler`: useful concept but currently wires 9 dependencies; assess whether it can be simplified into a scheduled tool call. See [BUG-heartbeat-premature-date-anniversary-reminder](../bugs/BUG-heartbeat-premature-date-anniversary-reminder.md) for a related correctness issue (date-specific facts surfaced without date verification)
- `DiagnosticsRunner`: valuable, but 9 dependencies; could be a tool that collects from well-defined status methods
- `FileIndexer` + RAG: useful feature but adds 4 background tasks at startup; should start lazily without blocking

---

## 5. Recommended Python Project Structure

```
remy/
│
├── config/                   # Configuration
│   ├── settings.py           # Pydantic BaseSettings (env vars)
│   ├── soul.md               # Remy's personality and system prompt
│   └── task.md               # Task context for sub-agents
│
├── core/                     # Agent core loop
│   ├── agent.py              # stream_with_tools wrapper; main agentic loop
│   ├── pipeline.py           # Proactive trigger execution (reuses agent.py)
│   ├── session.py            # Per-user session state and lock
│   └── streaming.py          # Telegram streaming helpers
│
├── telegram/                 # Telegram interface (thin layer)
│   ├── bot.py                # Application setup, handler registration
│   ├── commands.py           # All slash command handlers (≤15 commands)
│   ├── callbacks.py          # Inline keyboard callbacks
│   └── formatting.py         # Markdown/MarkdownV2 helpers
│
├── tools/                    # Tool implementations (one file per domain)
│   ├── registry.py           # ToolRegistry: schema list + dispatch
│   ├── memory.py             # get_goals, get_facts, manage_memory, ...
│   ├── calendar.py           # calendar_events, create_calendar_event
│   ├── email.py              # read_emails, search_gmail, label_emails, ...
│   ├── contacts.py           # search_contacts, update_contact_note, ...
│   ├── files.py              # read_file, write_file, find_files, ...
│   ├── web.py                # web_search, price_check
│   ├── relay.py              # relay_get_messages, relay_post_message, ...
│   ├── plans.py              # create_plan, update_plan_step, ...
│   ├── automations.py        # schedule_reminder, list_reminders, ...
│   ├── analytics.py          # get_stats, get_costs, generate_retrospective
│   ├── board.py              # run_board (wraps BoardOrchestrator)
│   ├── session.py            # compact_conversation, end_session, help, ...
│   └── ...
│
├── memory/                   # Persistence layer
│   ├── database.py           # DatabaseManager (SQLite, WAL, schema)
│   ├── knowledge.py          # KnowledgeStore + KnowledgeExtractor (unified)
│   ├── conversations.py      # ConversationStore
│   ├── plans.py              # PlanStore
│   ├── automations.py        # AutomationStore
│   ├── counters.py           # CounterStore
│   ├── embeddings.py         # EmbeddingStore (ANN)
│   ├── fts.py                # FTSSearch (keyword fallback)
│   ├── injector.py           # MemoryInjector (builds <memory> block)
│   ├── file_index.py         # FileIndexer (RAG over local files)
│   └── compaction.py         # Conversation compaction
│
├── scheduler/                # Proactive scheduling
│   ├── proactive.py          # ProactiveScheduler (APScheduler jobs)
│   ├── heartbeat.py          # HeartbeatHandler (evaluative cycle)
│   └── briefings/            # Briefing context builders
│
├── integrations/             # External service clients
│   ├── google/               # Calendar, Gmail, Docs, Contacts
│   ├── relay/                # Relay MCP client
│   └── voice.py              # Whisper transcriber
│
├── board/                    # Board of Directors sub-agents
│   ├── orchestrator.py       # BoardOrchestrator
│   ├── base_agent.py         # SubAgent base class
│   └── agents/               # strategy, content, finance, researcher, critic
│
├── delivery/                 # Outbound message queue (crash-safe)
│   ├── queue.py
│   └── send.py
│
├── analytics/                # API cost tracking, call logging
│   ├── call_log.py
│   ├── costs.py
│   └── metrics.py
│
├── utils/                    # Shared utilities
│   ├── circuit_breaker.py
│   ├── tokens.py
│   └── concurrency.py
│
├── health.py                 # HTTP health server (/ready, /diagnostics)
├── main.py                   # Entry point; wires and starts all components
└── exceptions.py             # Project-wide exceptions
```

**Key changes from current structure:**

- `remy/agents/` → split: orchestration → `board/`, background execution → inline in callers
- `remy/ai/` → split: `ClaudeClient` → `core/agent.py` (or keep as `core/claude.py`); router removed; tools → `tools/`
- `remy/bot/` → `telegram/` (clearer name)
- `remy/google/` → `integrations/google/`
- `remy/relay/` → `integrations/relay/`
- `remy/voice/` → `integrations/voice.py`
- `remy/web/` → removed; `web_search` is a tool in `tools/web.py`

---

## 6. Refactoring Roadmap

### Phase 1 — Stabilisation (no user-visible changes)

**Goal:** Stop the bleeding. Fix immediate correctness issues and remove obviously dead code.

1. **Route `TaskOrchestrator._call_claude()` through `ClaudeClient`**
   Single line change. Ensures all Claude calls have logging, circuit breaking, and token tracking.

2. **Delete `SubagentRunner`**
   Move its two methods into the `automations` handler directly. It's 80 lines and wraps one function call.

3. **Remove dead router usage from `chat.py`**
   The router fallback path (`if tool_registry is None`) cannot trigger in production. Remove the branch; keep only `stream_with_tools`. This simplifies `chat.py` significantly.

4. **Freeze legacy write paths**
   Stop writing new facts to `FactStore` and new goals to `GoalStore`. Write everything to `KnowledgeStore`. Keep read paths intact for backwards compatibility.

5. **Replace `_late` dict with a `StartupContext` dataclass**
   Provides type safety and makes the dependency graph explicit. `_late["proactive_scheduler"]` becomes `startup_ctx.proactive_scheduler`.

---

### Phase 2 — Module consolidation

**Goal:** Reduce the number of overlapping abstractions.

6. **Collapse `TaskOrchestrator` + `TaskRunner`**
   Either wire them into the live system (connect `task_runner` in `ToolRegistry`) or remove them. The current state — constructed but unwired — is the worst outcome.

7. **Merge proactive system prompt functions**
   `_reminder_system_prompt`, `_briefing_system_prompt`, `_evening_checkin_system_prompt`, `_afternoon_checkin_system_prompt`, `_afternoon_check_system_prompt` → single `build_proactive_system_prompt(scenario: str, context: dict | None)`.

8. **Unify the relay access path**
   `remy/relay/client.py` and `remy/ai/tools/relay.py` both exist. The tool wrappers should be the only entry point; `relay/client.py` becomes an internal implementation detail of the tool module.

9. **Reduce `make_handlers()` parameters**
   Group related dependencies into typed container objects (`MemoryDeps`, `GoogleDeps`, `SchedulerDeps`). Target < 8 parameters for `make_handlers()`.

---

### Phase 3 — UX normalisation

**Goal:** Consistent Telegram experience.

10. **Collapse command surface**
    Reduce from ~50 commands to ≤15. Remove duplicate command/tool pairs; the tool is the implementation. Update `/help` to be a concise 10–15 line overview.

11. **Normalise feedback patterns**
    Extract a single `WorkingMessage` context manager used everywhere. Remove the 3 separate implementations of "show typing indicator, edit to result".

12. **Consistent proactive button UX**
    All proactive triggers get zero or more action buttons using the same keyboard factory. No special casing for briefings vs reminders.

---

### Phase 4 — Feature pruning

**Goal:** Remove providers that don't contribute to reliability.

13. **Remove `ModelRouter`, `MessageClassifier`, `ClaudeDesktopClient`, `MistralClient`, `MoonshotClient`**
    These are maintained dead code in the primary path. If cost optimisation requires a cheaper model for simple requests, implement it transparently inside `ClaudeClient` by selecting `model_simple` vs `model_complex` — no separate router needed.

14. **Complete `KnowledgeStore` migration**
    Remove `FactStore` and `GoalStore` write paths. Provide read-only compatibility adapters during a deprecation window, then remove them.

15. **Remove `config_audit.py`**
    Inline the 20-line startup audit into `main.py` or `settings.py`.

---

### Phase 5 — Performance and reliability

**Goal:** Make the system faster, more observable, and easier to operate.

16. **Lazy service initialisation**
    Google Workspace clients, `FileIndexer`, voice transcriber, and embedding model should initialise on first use, not at startup. Reduces cold start from ~15s to ~3s.

17. **Reduce `ProactiveScheduler` dependencies**
    18 dependencies is too many. Extract a `SchedulerContext` that the scheduler reads from at trigger time, rather than holding 18 live references. Most of these are read-only data sources.

18. **Structured observability**
    Replace the current `logger.info()` scatter with structured log events at component boundaries: request received, tool called, tool result, response sent, token usage. Makes performance profiling tractable.

19. **Test coverage for the agent core loop**
    The agentic loop (`stream_with_tools` + tool dispatch + streaming) is the highest-value path and the hardest to test. Invest in integration tests with a mock Claude client that returns scripted tool-use sequences.

---

## Summary

The system's core is sound: the Anthropic tool-use loop works, memory injection works, Google integrations work, and the proactive scheduler is functional. The accidental complexity lives in:

1. **Multiple overlapping orchestration abstractions** (5 classes doing variations of the same thing)
2. **An incomplete memory migration** (two stores where one should exist)
3. **A routing layer that doesn't route** (bypassed in the primary path, maintained at cost)
4. **A command surface too large to use** (50+ commands, most duplicating tool capabilities)
5. **Wiring complexity** (18-parameter constructors, `_late` anti-pattern)

None of these require a rewrite. They are incremental cleanups that can be shipped as small pull requests in the order above, without user-visible disruption at any stage.
