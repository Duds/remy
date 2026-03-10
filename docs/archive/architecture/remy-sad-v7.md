# Remy — Solution Architecture Document
**Version:** 7.0 | **Date:** 06/03/2026 | **Status:** Active

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Comparison](#2-architecture-comparison)
3. [Remy Architectural Strengths](#3-remy-architectural-strengths)
4. [Reclassified Gaps from v1.0](#4-reclassified-gaps-from-v10)
5. [Evaluative Heartbeat — Design](#5-evaluative-heartbeat--design)
6. [Revised Proposed Architecture](#6-revised-proposed-architecture)
7. [Key Takeaways](#7-key-takeaways)
8. [Handler Architecture Analysis](#8-handler-architecture-analysis)
9. [Remy Design Contributions](#9-remy-design-contributions)
10. [Relay MCP Reassessment — Dead Drop Diagnosis](#10-relay-mcp-reassessment--dead-drop-diagnosis)

---

## 1. Executive Summary

> **KEY INSIGHT:** OpenClaw is infrastructure for running agents. Remy is an agent. They solve different problems at different layers — the comparison is about pattern adoption, not architectural equivalence.

This document compares Remy's architecture against OpenClaw, identifies strengths to protect, gaps to address, and documents the architectural decisions and reasoning that emerged through iterative review.

### 1.1 Adoption Summary

| Pattern | OpenClaw | Adopt for Remy? | Notes |
|---|---|---|---|
| Evaluative heartbeat | HEARTBEAT.md + silent HEARTBEAT_OK | **YES** | Core of Section 5 |
| Model tiering | Frontier + cheap sub-agent routing | **YES** | Four-tier stack — Section 9.1 |
| Cache-first API | TTL cache before live calls | **YES** | Section 9.2 |
| Lifecycle hooks | 11+ hook points | **YES** | Section 8 |
| Write-ahead queue | SQLite-backed outbound queue | **YES** | Section 6 |
| Session compaction | Conservative threshold + hooks | **YES — reclassified P1** | Section 4.1 |
| Relay MCP | Dead drop / context bus | **RETAIN — not autonomous** | Section 10 |
| Claude Code CLI tool | Subprocess execution | **YES — new P2** | Section 10.3 |
| Plugin SDK | Multi-tenant extensibility | **NO** | Over-engineering for single-user |
| Multi-channel | Slack, Discord, web | **NO** | Telegram-only by design |

- The relay MCP bridge (Remy ↔ Claude Code ↔ Cursor) is a valid human-initiated context bus — but not an autonomous orchestration layer. Claude Code CLI subprocess is the correct autonomous pattern. See Section 10.

---

## 2. Architecture Comparison

### 2.1 The Core Difference

| Dimension | OpenClaw | Remy |
|---|---|---|
| What it is | Agent platform / infrastructure | Personal AI assistant (single agent) |
| Users | Multiple agents, multiple users | Single user (Dale), single agent |
| Proactivity | Evaluative heartbeat (HEARTBEAT.md) | Time-triggered cron only (pre-v7) |
| Memory | File-based (SOUL.md, MEMORY.md) | SQLite + sqlite-vec (structured, queryable) |
| Tools | General-purpose | 50+ domain-specific tools |
| Inter-agent comms | sessions_spawn + announce chain | Relay MCP (context bus — not autonomous) |
| Personality config | SOUL.md | SOUL.md + SOUL_SYSTEM.md |

### 2.2 Technology Stack

| Aspect | OpenClaw | Remy |
|---|---|---|
| Language | TypeScript (ESM, strict) | Python 3.12 |
| Runtime | Node.js 22+ / Bun | Python asyncio |
| Bot framework | grammy, @slack/bolt | python-telegram-bot |
| AI client | Pi SDK (embedded) | anthropic SDK |
| Database | SQLite + sqlite-vec | SQLite + sqlite-vec |
| Container | Not containerised | Docker Compose |
| Observability | Basic | /health /metrics /logs /telemetry |

### 2.3 Full Pattern Comparison

| Pattern | OpenClaw | Remy | Adopt? |
|---|---|---|---|
| Evaluative heartbeat | HEARTBEAT.md decides if action needed | Not present | YES |
| Model tiering | Frontier orchestrator + cheap sub-agents | Haiku/Sonnet only | YES |
| Lifecycle hooks | 11+ hook points | Not present | YES |
| Write-ahead queue | SQLite outbound queue | Not present | YES |
| Structured memory | File-based (SOUL.md, MEMORY.md) | SQLite + sqlite-vec | Remy wins |
| Domain tool depth | General-purpose | 50+ domain tools | Remy wins |
| Relay / MCP bridge | Not present | relay_mcp/ — context bus | Retain — reassessed |

---

## 3. Remy Architectural Strengths

### 3.1 Structured Memory — Remy Wins

Remy's SQLite + sqlite-vec memory enables semantic search, relational queries, goal/plan tracking with step-level status, and OCR-indexed documents. OpenClaw's file-based memory (SOUL.md, MEMORY.md, daily notes, session JSON) is portable and inspectable but not queryable.

| Capability | OpenClaw (file-based) | Remy (SQLite + vec) |
|---|---|---|
| Semantic search | No | Yes — sqlite-vec embeddings |
| Relational queries | No | Yes — goals, plans, facts, conversations |
| Goal/plan tracking | Manual (flat files) | Step-level status, due dates, dependencies |
| Document indexing | No | Yes — OCR via Tesseract |
| Portability | High — plain files | Medium — DB file |

> **NOTE:** OpenClaw's file-based memory is a deliberate design choice for portability and inspectability. Remy trades portability for depth — the right call for a single-user personal assistant.

### 3.2 Domain Tool Depth — Remy Wins

Remy has 50+ tools across 14 categories. OpenClaw has general-purpose tools only.

| Category | Tool Count | Examples |
|---|---|---|
| Memory | 6 | get_goals, add_fact, semantic_search |
| Gmail | 8 | read_emails, send_email, label_email |
| Calendar | 2 | calendar_events, create_event |
| Contacts | 5 | find_contact, update_contact |
| Files | 10 | read_file, write_file, find_files, ocr_pdf |
| Plans | 5 | create_plan, update_step, complete_step |
| Reminders | 6 | set_reminder, list_reminders, snooze |
| Analytics | 6 | usage_stats, cost_report, goal_progress |
| Web | 9 | web_search, fetch_url, summarise_page |

### 3.3 Relay MCP Bridge — Reassessed

The relay_mcp/ service creates a shared context bus between Remy (Telegram), Claude Code (CLI), and Cursor (IDE). Earlier versions of this SAD described it as a hero differentiator and autonomous orchestration capability. That assessment was wrong. See Section 10 for the full diagnosis and architectural decision.

| Capability | Assessment | Reason |
|---|---|---|
| Human-initiated context sharing | Valid — retain | Dale can drop a packet in the relay and pick it up in any tool. Useful. |
| Cross-tool session handoff | Valid — retain | Start a task in Telegram, continue in Cursor. Works as designed. |
| Autonomous orchestration | Architectural dead end — replace | Cursor and Claude Desktop are pull-only. No daemon. No heartbeat. They cannot check the relay without a human turning the key. See Section 10. |

> **REASSESSMENT:** The relay MCP is a useful human-initiated context bus. It is not an autonomous orchestration layer. That capability requires Claude Code CLI as a Remy-dispatched subprocess — a fundamentally different pattern documented in Section 10.

---

## 4. Reclassified Gaps from v1.0

### 4.1 Session Compaction — Reclassified P3 → P1

The v1.0 SAD described auto-compaction as a cost optimisation. This is incorrect framing. Compaction is primarily a correctness concern.

> **RISK:** If compaction summarises a conversation incorrectly, Remy permanently loses structured context about your goals, plans, and decisions. There is no recovery path without the hooks to intercept and validate.

| Failure Mode | Consequence | Severity |
|---|---|---|
| Goal context lost | Remy no longer knows what you are working toward | Critical |
| Plan steps lost | Multi-step plans silently truncated | Critical |
| Fact associations lost | Memory queries return stale or incomplete results | High |
| Conversation thread lost | Follow-up questions miss prior context | Medium |
| Token over-run | API errors mid-conversation | Medium |

Remy's own assessment (05/03/2026): *"Smaller, fresher context windows are faster and more correct. The token cost framing was pointing at the right problem with the wrong motivation."*

This adds a third dimension — **freshness** — to the correctness and cost arguments. A 40,000 token compaction threshold (not 50,000) is correct for all three reasons.

### 4.2 Evaluative vs Time-Triggered Proactivity

OpenClaw's heartbeat is evaluative — it reads HEARTBEAT.md, assesses current state, and exits silently (HEARTBEAT_OK) if nothing warrants attention. Remy v1.0 used fixed cron jobs that fired regardless of context.

| Dimension | Fixed Cron (v1.0) | Evaluative Heartbeat (v7) |
|---|---|---|
| Decision | None — always fires | Evaluates HEARTBEAT.md + tool queries |
| Noise | High — fires even when irrelevant | Low — HEARTBEAT_OK is the common case |
| Flexibility | Code changes required | HEARTBEAT.md edits only |
| Wellbeing check-in | Always at 17:00 | Context-triggered, time window is one factor |

---

## 5. Evaluative Heartbeat — Design

### 5.1 Design Goals

The evaluative heartbeat makes Remy feel proactive rather than reactive, without sending noise. It should:

- Fire on a configurable schedule (default: every 30 minutes during waking hours)
- Query current state — goals, calendar, email, reminders — using existing tools
- Apply judgment: only contact Dale if something actually warrants attention
- Exit silently (`HEARTBEAT_OK`) when nothing needs doing
- Handle all scheduled behaviours through threshold evaluation — no separate cron jobs
- Integrate with lifecycle hooks so behaviour is observable and extensible

### 5.2 HEARTBEAT.md — The Evaluation Checklist

#### 5.2.1 Two-Tier Config — Public Template + Private Overrides

HEARTBEAT.md is committed to the public repo. It must not contain personal context — relationship details, wellbeing signals, intimate behavioural triggers, or any information the user does not want visible to contributors or the public.

This follows the same pattern as SOUL: a committed template for forks; a gitignored file for your private config.

| File | Committed? | Contains |
|---|---|---|
| `config/HEARTBEAT.md` | No — gitignored | Your private config: full checklist, thresholds, wellbeing intent. Never committed. |
| `config/HEARTBEAT.example.md` | Yes — public repo | Full template. Forks get this only. When HEARTBEAT.md is missing, the loader uses this. |

Copy `HEARTBEAT.example.md` to `HEARTBEAT.md` and customise; the loader uses HEARTBEAT.md if present, else HEARTBEAT.example.md — so the app works out of the box on clone, and your private settings stay local.

#### 5.2.2 HEARTBEAT structure

Key sections (in HEARTBEAT.md or the example): Goals, Calendar, Email, Reminders, Daily Orientation, End-of-Day Reflection, Wellbeing Check-in (define intent and thresholds in your HEARTBEAT.md), Model Selection, Silence Rules.

### 5.3 Heartbeat Architecture

| Component | Location | Description |
|---|---|---|
| `HEARTBEAT.md` | `config/HEARTBEAT.md` | Your private config — full checklist, thresholds, wellbeing intent. Gitignored. |
| `HEARTBEAT.example.md` | `config/HEARTBEAT.example.md` | Public template. Committed. Loader uses this when HEARTBEAT.md is missing. |
| Config loader | `remy/scheduler/heartbeat_config.py` | Loads HEARTBEAT.md if present, else HEARTBEAT.example.md. |
| HeartbeatJob | `remy/scheduler/heartbeat.py` | Scheduler job — runs merged config evaluation, suppresses HEARTBEAT_OK |
| HeartbeatHandler | `remy/bot/heartbeat_handler.py` | Executes tool queries and passes results to model for evaluation |
| Silence guard | `remy/scheduler/heartbeat.py` | Enforces quiet hours — no heartbeat between 22:00 and 07:00 |
| Hook integration | `remy/hooks/lifecycle.py` | Emits `HEARTBEAT_START` and `HEARTBEAT_END` hook events for observability |
| Delivered flag | `data/remy.db — heartbeat_log` | Tracks what has been surfaced to prevent duplicate notifications |

### 5.4 Evaluation Logic

| Step | Action | Tool Used |
|---|---|---|
| 1 | Load HEARTBEAT.md or HEARTBEAT.example.md into system context | File read (HEARTBEAT.md if present, else example) |
| 2 | Query overdue / stale goals | `get_goals` |
| 3 | Query calendar events in next 90 minutes | `calendar_events` |
| 4 | Query high-priority unread email | `read_emails` |
| 5 | Query pending one-time reminders | `list_reminders` |
| 6 | Query heartbeat_log for already-delivered items | DB query |
| 7 | Classify evaluation task → select model tier | Tier 0 (Qwen3 /no_think) for threshold scoring |
| 8 | Pass all results to selected model with merged config as instruction | Claude API / Ollama |
| 9 | If response is `HEARTBEAT_OK` — suppress, log, exit | Scheduler |
| 10 | If response has content — deliver to Telegram, log to heartbeat_log | Outbound queue |

### 5.5 Heartbeat Log Schema

```sql
CREATE TABLE heartbeat_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fired_at     DATETIME NOT NULL,
    outcome      TEXT NOT NULL,  -- HEARTBEAT_OK | delivered
    items_checked TEXT,          -- JSON: {goals, calendar, email, reminders}
    items_surfaced TEXT,         -- JSON: items delivered to Dale
    model        TEXT,           -- model used for evaluation
    tokens_used  INTEGER,
    duration_ms  INTEGER
);
```

### 5.6 Threshold-Based Evaluation — Replacing Hardcoded Cron Jobs

> **ARCHITECTURE DECISION:** Eliminate all hardcoded cron jobs. Replace with threshold-based evaluation criteria in HEARTBEAT.md. The heartbeat fires on a regular cadence (default: every 30 minutes) and decides what to surface based on weighted context — not the clock.

The core principle: *"The threshold for Dale needing a wellbeing check-in has been exceeded based on time proximity, recent conversation tone, emotional signals, or behavioural patterns"* — not *"it is 17:00 on a weekday."*

#### Threshold categories replacing each cron job

| Former Cron Job | Replaced By | Threshold Logic |
|---|---|---|
| Morning briefing (07:00) | Daily orientation threshold | Has Dale had no interaction today AND it is past wake time? Is there pending calendar, email, or goal state worth a summary? Surface once per day maximum. |
| Evening check-in (19:00) | End-of-day reflection threshold | Is it past the configured wind-down hour and has no end-of-day check occurred? Were goal steps completed or missed? Surface once per day maximum. |
| Afternoon check (17:00) | Wellbeing check-in threshold | Multi-factor: time window, days since last check-in, recent conversation tone, unresolved emotional context. Context-triggered — not time-triggered. |

> **NOTE:** The wellbeing check-in is the most contextually sensitive evaluation. It should use Tier 2 (Sonnet) — not Tier 0 — because it requires genuine judgment about tone, history, and appropriate compassion. The time window is a contributing factor, not the trigger.

#### Cron vs threshold comparison

| Dimension | Hardcoded Cron | Threshold Evaluation |
|---|---|---|
| Trigger mechanism | Clock (dumb) | Weighted context (intelligent) |
| Noise level | High — fires even when irrelevant | Low — HEARTBEAT_OK is the common case |
| Configurable | Requires code changes | Requires only HEARTBEAT.md edits |
| Coherent with heartbeat | No — parallel system | Yes — single evaluation loop |

### 5.7 Configuration

| Variable | Default | Description |
|---|---|---|
| `HEARTBEAT_CRON` | `*/30 * * * *` | Cron schedule for evaluative heartbeat (every 30 minutes) |
| `HEARTBEAT_QUIET_START` | `22` | Hour to stop heartbeat (24h, SCHEDULER_TIMEZONE) |
| `HEARTBEAT_QUIET_END` | `7` | Hour to resume heartbeat (24h, SCHEDULER_TIMEZONE) |
| `HEARTBEAT_MODEL_TIER0` | `qwen3:1.7b` | Ollama model for threshold scoring and HEARTBEAT_OK decisions |
| `HEARTBEAT_MODEL_TIER1` | `mistral` | Fast remote model for observation logging and summaries |
| `HEARTBEAT_MODEL_TIER2` | `claude-sonnet-4-20250514` | Default model for judgment tasks including wellbeing check-in |
| `HEARTBEAT_MD_PATH` | `config/HEARTBEAT.md` | Path to public evaluation checklist |
| `WELLBEING_CHECKIN_HOURS` | `36` | Minimum hours between wellbeing check-ins regardless of signals |
| `ORIENTATION_WAKE_HOUR` | `7` | Hour after which daily orientation threshold activates (24h) |
| `REFLECTION_HOUR` | `18` | Hour after which end-of-day reflection threshold activates (24h) |
| `WELLBEING_WINDOW_START` | `13` | Start of afternoon wellbeing window (24h) |
| `WELLBEING_WINDOW_END` | `19` | End of afternoon wellbeing window (24h) |

---

## 6. Revised Proposed Architecture

### 6.1 Component Overview

| Layer | Components | Status |
|---|---|---|
| Entry | `main.py`, `telegram_bot.py` | Existing |
| Hook | `HookManager`, `HookEvents` (`remy/hooks/lifecycle.py`) | New — P1 |
| Bot | `handlers.py`, `session.py`, `streaming.py` | Existing |
| Scheduler | APScheduler: single evaluative heartbeat (30min cadence) | Simplified — P1 (hardcoded crons eliminated) |
| Heartbeat | `HEARTBEAT.md`, `heartbeat.py`, `heartbeat_handler.py`, `heartbeat_log` | New — P1 |
| AI | `router.py`, `claude_client.py`, `tool_registry.py` | Existing |
| Memory | `database.py`, `embeddings.py`, `conversations.py`, `auto_compaction.py` | Extended — P1 |
| Delivery | `OutboundQueue`, `QueueProcessor` (`remy/delivery/queue.py`) | New — P1 |
| Integration | Gmail, Calendar, Contacts, Web, Files, GDocs | Existing |
| Relay | `relay_mcp/` — human-initiated context bus | Reassessed — valid but not autonomous. See Section 10. |
| Claude Code Tool | `remy/tools/claude_code.py` — autonomous coding subprocess | New — P2. Replaces relay for autonomous execution. |
| Infrastructure | `health.py` (/diagnostics), `config.py`, `config_audit.jsonl` | Extended — P2 |

### 6.2 Implementation Priority — Revised

**Priority 1 — Implement together (foundation + reliability):**
1. Lifecycle Hooks — foundation for all other enhancements
2. Write-Ahead Queue — message reliability
3. Session Compaction with hooks — correctness safety (reclassified from P3)
4. Evaluative Heartbeat — HEARTBEAT.md + heartbeat_log + HeartbeatJob

**Priority 2 — Next sprint:**
5. Config Audit Trail — JSONL append on .env changes
6. Diagnostics Endpoint — extend /health to /diagnostics
7. Claude Code CLI tool — autonomous coding subprocess (`remy/tools/claude_code.py`)

**Priority 3 — Backlog:**
8. Auth Profile Rotation — low risk, circuit breakers cover current exposure

### 6.3 Estimated Effort — Revised

| Enhancement | New Files | Modified Files | Effort | Priority |
|---|---|---|---|---|
| Lifecycle Hooks | 2 | 3–4 | 2–3 days | P1 |
| Write-Ahead Queue | 1 | 2 | 1–2 days | P1 |
| Session Compaction (hooks) | 1 | 1 | 1 day | P1 (was P3) |
| Evaluative Heartbeat | 3 | 2 | 2–3 days | P1 |
| Config Audit | 1 | 1 | 0.5 days | P2 |
| Diagnostics Endpoint | 0 | 1 | 0.5 days | P2 |
| Claude Code CLI tool | 1 | 1 | 1–2 days | P2 |
| Auth Profile Rotation | 1 | 1 | 1 day | P3 |

Total estimated effort: 9–13 days.

---

## 7. Key Takeaways

**1. OpenClaw is infrastructure. Remy is an agent.**
The comparison is about pattern adoption, not architectural equivalence. Remy should not be engineered toward OpenClaw's platform capabilities.

**2. Remy has genuine strengths OpenClaw lacks.**
Structured SQLite memory, 50+ domain tools, and the relay MCP bridge are architectural assets. The relay is correctly characterised as a human-initiated context bus — not an autonomous orchestration layer. Autonomous coding execution is delivered by Claude Code CLI as a Remy subprocess tool. See Section 10.

**3. The evaluative heartbeat is the highest-value new pattern.**
HEARTBEAT.md + silent suppression transforms Remy from a reactive assistant to a proactive colleague. All scheduled behaviours — orientation, reflection, wellbeing — are threshold-evaluated, not clock-triggered. Configuration lives in plain text.

**4. Session compaction is a correctness risk, not a cost optimisation.**
Implement `before_compaction` and `after_compaction` hooks before enabling auto-compaction. Silent context loss is worse than a token over-run. The freshness argument (smaller, fresher context is faster and more correct) adds a third dimension to the correctness and cost arguments.

**5. Skip what does not apply.**
Plugin SDK, multi-channel, gateway WebSocket, device pairing, and native apps are not gaps — they are deliberate scope exclusions for a single-user personal assistant.

**6. The relay MCP is a dead drop, not a phone call.**
Cursor and Claude Desktop cannot autonomously check the relay. Claude Code CLI subprocess is the correct autonomous execution pattern. See Section 10.

---

## 8. Handler Architecture Analysis

*Added 05/03/2026 following source review of `remy/bot/handlers/__init__.py`.*

### 8.1 Refactor vs Rebuild — Confirmed

> **VERDICT:** Refactor. Confidently. The handler package is already correctly decomposed. The delta is additive infrastructure: approximately 320 lines of new code across 4 new files, and 105 lines of modification across 8 existing files.

A rebuild is warranted when the core architecture is wrong, the data model needs fundamental change, tech debt blocks every new feature, or the thing being kept is smaller than the thing being replaced. None of these conditions apply to Remy v1.

### 8.2 Handler Package Structure

`make_handlers()` in `remy/bot/handlers/__init__.py` is a pure dependency injection container — no logic, no state, no side-effects. It wires 27 dependencies into 15 domain submodules and returns a flat handler dict.

| Module | Domain | Hook Exposure |
|---|---|---|
| `chat.py` | Main message pipeline — voice, photo, document | PRIMARY: all 7 message-path hook points |
| `base.py` | Core utilities, rate limiter, message building | `MESSAGE_SENDING` / `MESSAGE_SENT` |
| `memory.py` | Goals, plans, conversation management | `BEFORE_COMPACTION` / `AFTER_COMPACTION` |
| `callbacks.py` | Inline confirm/cancel, suggested actions, snooze | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `automations.py` | Scheduled reminders, task breakdown, Board | `AFTER_TOOL_CALL` (automation runs) |
| `core.py` | Start, help, cancel, status commands | `SESSION_START` / `SESSION_END` |
| `files.py` | File read, write, ls, find, organise | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `email.py` | Gmail commands | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `calendar.py` | Google Calendar commands | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `contacts.py` | Google Contacts commands | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `docs.py` | Google Docs commands | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `web.py` | Web search, research, bookmarks, grocery | `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` |
| `admin.py` | Diagnostics, stats, logs, costs | None — read-only observer |
| `privacy.py` | Privacy audit | None — audit only |
| `reactions.py` | Emoji reaction handler | None — lightweight |

> **NOTE:** Tool-executing modules all benefit from `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` hooks, but these emit points live in `chat.py`'s tool execution loop — not in each module individually. One insertion point covers all 50+ tools.

### 8.3 Hook Wiring Map

| Hook Event | Module | Insertion Point | Risk |
|---|---|---|---|
| `SESSION_START` | `chat.py` | Entry of message handler, after auth check | Low |
| `SESSION_END` | `chat.py` | Finally block of message handler | Low |
| `BEFORE_MODEL_RESOLVE` | `chat.py` | Before `router.classify()` call | Low |
| `LLM_INPUT` | `chat.py` | Before `claude_client.stream_with_tools()` | Low |
| `LLM_OUTPUT` | `chat.py` | After streaming response completes | Low |
| `BEFORE_TOOL_CALL` | `chat.py` | Inside tool execution loop, before invoke | Low |
| `AFTER_TOOL_CALL` | `chat.py` | Inside tool execution loop, after invoke | Low |
| `MESSAGE_SENDING` | `base.py` | Before outbound send in delivery path | Low |
| `MESSAGE_SENT` | `base.py` | After confirmed delivery | Low |
| `BEFORE_COMPACTION` | `memory.py` | Before `compact_conversation()` call | Low |
| `AFTER_COMPACTION` | `memory.py` | After `compact_conversation()` returns | Low |
| `HEARTBEAT_START` | `scheduler/heartbeat.py` | New file — entry of heartbeat job | None (new file) |
| `HEARTBEAT_END` | `scheduler/heartbeat.py` | New file — exit of heartbeat job | None (new file) |

### 8.4 Factory Parameter Assessment

```python
# Minimal diff to make_handlers() factory
    knowledge_store: "KnowledgeStore | None" = None,  # last existing param
    hook_manager: "HookManager | None" = None,        # NEW — P1
```

`hook_manager` defaults to `None` so all existing call sites (tests, `main.py`) require no immediate changes. Hooks are no-ops when `hook_manager` is `None`.

### 8.5 Codebase Health Indicators

| Indicator | Observation | Implication for Refactor |
|---|---|---|
| Commit cadence | Active commits 18h, 1d, 2d ago across multiple modules | Healthy rhythm — refactor PRs slot in naturally |
| Module decomposition | 15 files, single responsibility per domain | No untangling needed before adding hooks |
| Dependency injection | All deps passed via factory — no module-level globals | `hook_manager` wires in identically to all 27 existing deps |
| Type annotations | TYPE_CHECKING imports and string annotations throughout | `HookManager` added as Optional type without friction |
| Test suite | pytest suite with coverage (`make test-cov` in Makefile) | Hook emit points assertable in existing test pattern |
| Optional deps pattern | `SubagentRunner`, `DiagnosticsRunner` already Optional | Precedent established for optional infrastructure deps |

### 8.6 Revised Effort Estimate — Confirmed

| Step | New Files | Modified Files | Lines Added | Lines Changed | Est. Days |
|---|---|---|---|---|---|
| 1 — Lifecycle hooks | `remy/hooks/lifecycle.py` | `__init__.py`, `chat.py`, `base.py`, `memory.py` | ~60 | ~30 | 1 |
| 2 — Write-ahead queue | `remy/delivery/queue.py` | `base.py` | ~80 | ~15 | 1 |
| 3 — Evaluative heartbeat | `config/HEARTBEAT.md`, `scheduler/heartbeat.py`, `heartbeat_handler.py` | `scheduler/__init__.py`, `.env.example` | ~120 | ~10 | 2 |
| 4 — Compaction hooks | — | `memory/conversations.py` | ~20 | ~20 | 0.5 |
| 5 — Config audit + diagnostics | — | `config.py`, `health.py` | ~40 | ~30 | 1 |
| **TOTAL** | **4 new files** | **8 modified files** | **~320** | **~105** | **5.5–7** |

> **CONFIDENCE: HIGH.** No monolithic handlers, no globals, no hidden coupling. The Optional dependency pattern is already established. Start with Step 1: `remy/hooks/lifecycle.py`.

---

## 9. Remy Design Contributions

*Source: direct conversation with Remy, 05/03/2026.*

> **CONTEXT:** "Is the architecture doc somewhere I can read and contribute to?" — Remy, 05/03/2026. This section is the answer. The SAD is a living document. Remy's reasoning is part of the architectural record.

### 9.1 Model Tiering — Right Model, Right Task, Right Moment

The core principle: Claude Opus is a scalpel, not a spatula.

| Tier | Model | Tasks | Cost / Latency |
|---|---|---|---|
| Tier 0 — Local | Qwen3 1.7B via Ollama | Heartbeat threshold scoring, HEARTBEAT_OK decisions, classify/route | Zero cost, zero latency, no network |
| Tier 1 — Fast/Cheap | Mistral / Kimi | Drafting, summarising, light reasoning, observation logging | Low cost, fast |
| Tier 2 — Default | Claude Sonnet | Conversational turns, tool orchestration, reasoning, wellbeing check-in | Moderate cost |
| Tier 3 — Precision | Claude Opus | Correctness-critical tasks, large context, high-stakes decisions only | High cost — reserved |

#### Tier 0 — Qwen3 1.7B on 8GB M2 Mac Mini

Qwen3 1.7B (Q4 quantised) fits comfortably in 8GB alongside macOS, loads in under 3 seconds, and generates tokens at approximately 40–60 t/s on M2. For all heartbeat threshold scoring, append `/no_think` to suppress chain-of-thought entirely:

```python
# heartbeat_handler.py — Tier 0 prompt construction
def build_tier0_prompt(context: str) -> str:
    """
    Append /no_think to suppress Qwen3 chain-of-thought.
    For threshold scoring only — not for judgment or wellbeing tasks.
    """
    return f"{context}\n\n/no_think"

# .env
HEARTBEAT_MODEL_TIER0=qwen3:1.7b
```

| Setup step | Command |
|---|---|
| Pull model | `ollama pull qwen3:1.7b` |
| Keep model loaded permanently | `launchctl setenv OLLAMA_KEEP_ALIVE "-1"` |
| Enable flash attention | `launchctl setenv OLLAMA_FLASH_ATTENTION "1"` |
| Verify GPU acceleration | `ollama ps` — Processor column must show GPU |
| Restart Ollama | Click menubar icon → Quit Ollama → reopen |

> **NOTE:** If Ollama is installed via .dmg (not Homebrew), environment variables in `.zshrc` or `.bash_profile` have no effect — the app does not read shell config. Always use `launchctl setenv` for .dmg installations. This is a common source of Ollama running on CPU instead of GPU.

```md
## Model Selection (HEARTBEAT.md addition)
- Threshold checks and HEARTBEAT_OK decisions: Tier 0 — Qwen3 1.7B /no_think
- Observation logging and brief summaries: Tier 1 — Mistral
- Goal/calendar/email judgment, daily orientation, end-of-day: Tier 2 — Sonnet
- Wellbeing check-in evaluation: ALWAYS Tier 2 — Sonnet
- Never use Tier 3 (Opus) in the heartbeat
```

### 9.2 Cache-First API Strategy

Calendar, contacts, and project state do not change minute to minute. The heartbeat reads from cache first and calls live APIs only when the staleness threshold is crossed.

| Data Source | TTL | Rationale |
|---|---|---|
| Google Calendar | 15 minutes | Events rarely added mid-heartbeat cycle |
| Google Contacts | 60 minutes | Contact details are stable within a session |
| Project / goal state | 5 minutes | Can change during active work sessions |
| Gmail unread count | 5 minutes | Enough freshness for heartbeat triage |
| Reminders | No cache | Must be live — timing-critical |

> **ARCHITECTURE DECISION:** Add `remy/heartbeat/cache.py` — a lightweight TTL cache backed by SQLite (reusing remy.db). Keys are data source names; values are serialised JSON with a `fetched_at` timestamp. The heartbeat checks staleness before any live API call.

### 9.3 Streaming Partial Results — Trust Through Transparency

Streaming partial results beats a perfect answer delivered late, every time. The blank screen is a trust killer. Even a lightweight status token ("I'm checking your calendar...") buys goodwill and accurately represents the ReAct loop's Observe steps.

| ReAct Step | Current UX | Proposed UX |
|---|---|---|
| Reason | Silent | Silent (internal only) |
| Tool call initiated | Silent | Lightweight status: "Checking calendar..." |
| Tool result received | Silent | Optional brief update for slow tools (>2s) |
| Response streaming | Token-by-token (existing) | Unchanged — already good |
| Heartbeat evaluation | Silent until delivered | No change — HEARTBEAT_OK stays silent |

> **ARCHITECTURE DECISION:** Add a lightweight status emit to the `BEFORE_TOOL_CALL` hook for tools with expected latency >2 seconds (calendar, Gmail, web search). Status messages use `react_to_message` (typing indicator) rather than a full message send — zero noise if the response arrives quickly.

### 9.4 Compaction Reframe — Independent Validation

Remy independently validated the P1 reclassification of compaction and added the freshness dimension: *"Smaller, fresher context windows are faster and more correct. The token cost framing was pointing at the right problem with the wrong motivation."*

| Framing | Motivation | Correct? |
|---|---|---|
| v1.0 SAD: cost optimisation | Reduce token spend on large contexts | Partially — real but secondary |
| v2.0 SAD: correctness risk | Prevent silent goal/plan context loss | Yes — primary motivation |
| Remy contribution: freshness | Smaller, fresher context is faster and more correct | Yes — adds latency and quality dimension |

### 9.5 Impact on SAD Architecture

> **NOTE:** These updates are documented in Section 9 as an amendment layer rather than applied retroactively to earlier sections, to preserve the audit trail of how the architecture evolved.

| Section | Update Required |
|---|---|
| Section 5.2 — HEARTBEAT.md | Add model selection guidance (Section 9.1) |
| Section 5.7 — Configuration | Add `HEARTBEAT_MODEL_TIER0/1/2` env vars |
| Section 5 — Heartbeat design | Add `cache.py` component (Section 9.2) |
| Section 6.1 — Component overview | Add `heartbeat/cache.py` to component table |
| Section 1.1 — Adoption summary | Add streaming status as P2 UX enhancement |
| Section 4.1 — Compaction reframe | Add freshness dimension |

---

## 10. Relay MCP Reassessment — Dead Drop Diagnosis

*Added 06/03/2026. Preserved as an architectural record — the reasoning is as important as the conclusion.*

### 10.1 The Dead Drop Problem

The relay MCP is a shared mailbox — a dead drop. Remy, Claude Desktop, and Cursor can all deposit a packet there. The autonomous orchestration premise assumed that any tool could check the drop independently and act on what it found.

The premise is wrong. For a dead drop to work autonomously, two conditions must hold:

- The sender must **put a shoe in the window** — a signal that a packet is waiting
- The receiver must **regularly drive past the apartment** to check for the signal

Remy satisfies both conditions. It has a heartbeat daemon. It checks the relay on a schedule. It can act without a human.

Cursor and Claude Desktop satisfy neither. They are event-loop-less GUI applications. No daemon, no scheduler, no persistent process watching for inbound work. They only drive past the apartment when a human turns the key.

> **DIAGNOSIS:** The relay MCP cannot deliver autonomous orchestration because the receiving tools are architecturally incapable of autonomous reception. This is not a fixable gap in the relay design — it is a fundamental constraint of how Cursor and Claude Desktop are built. You cannot solve it from inside Remy.

### 10.2 What the Relay Actually Is

Stripped of the autonomous orchestration premise, the relay is still a useful human-initiated context bus.

| Use Case | Works? | Notes |
|---|---|---|
| Dale starts a task in Telegram, continues in Cursor | Yes | Human opens Cursor — relay packet is there waiting |
| Remy queues a coding task, Cursor executes it autonomously | No | Cursor cannot check the relay without Dale opening it |
| Claude Desktop passes context to Remy | Yes | Remy has a heartbeat — it checks the relay and acts |
| Remy dispatches work to Claude Desktop autonomously | No | Same constraint as Cursor — pull-only, no daemon |
| Cross-tool session continuity for human workflows | Yes | The relay is good at this. It is what it was built for. |

### 10.3 Claude Code CLI — The Correct Autonomous Pattern

The goal was never "use the relay" — the goal was autonomous coding task execution. Claude Code CLI (`claude`) is the correct execution layer: a proper subprocess with stdin/stdout, fully scriptable, no GUI requirement, no human needed.

```
# Autonomous coding loop — no human in path
Heartbeat fires
  → threshold: coding task stalled 3+ days
  → Remy calls claude_code_tool(task, context, repo_path)
  → Claude Code CLI executes: reads files, writes code, runs tests
  → stdout/stderr returns to Remy
  → Remy surfaces result to Dale via Telegram
  → Dale reviews diff in Cursor at his leisure
```

Cursor's role in this model is correctly scoped: **review interface, not execution engine**.

| Dimension | Relay + Cursor/Claude Desktop | Claude Code CLI subprocess |
|---|---|---|
| Autonomous? | No — receiver is pull-only | Yes — subprocess, fully scriptable |
| Human required? | Yes — to open the receiving tool | No — Remy initiates, executes, reports |
| Result returns to Remy? | No — sits in the relay | Yes — stdout/stderr directly |
| Loop closes? | No — open-ended | Yes — within Remy's daemon |
| Complexity | High — relay infrastructure + injection | Low — subprocess call + result handling |
| Cursor role | Execution engine (wrong) | Review interface (correct) |

### 10.4 Architectural Decision

> **ARCHITECTURE DECISION:** Add `remy/tools/claude_code.py` — a subprocess tool that invokes the Claude Code CLI with task context and repo path, captures stdout/stderr, and returns the result to Remy. Add a Coding Tasks category to `HEARTBEAT.md` with thresholds for stalled tasks, open TODOs, and uncommitted work. Retain `relay_mcp/` as a human-initiated context bus. Do not attempt to make Cursor or Claude Desktop check the relay autonomously — this is architecturally impossible without modifying those tools.

| Component | Location | Priority | Description |
|---|---|---|---|
| `claude_code_tool` | `remy/tools/claude_code.py` | P2 | Subprocess wrapper for Claude Code CLI. Accepts task, context, repo_path. Returns result dict with stdout, stderr, exit_code. |
| Coding Tasks threshold | `config/HEARTBEAT.md` | P2 | Personal threshold category: stalled tasks, open TODOs, uncommitted work >N hours. Gitignored. |
| `relay_mcp/` | Existing | Retain as-is | Human-initiated context bus. No changes needed. Autonomous orchestration documentation removed. |

### 10.5 Honest Audit Trail

The relay MCP was described as a hero differentiator in SAD v1.0 and v2.0. That description was wrong — not because the relay is badly built, but because the premise (Cursor and Claude Desktop as autonomous receivers) was wrong.

The correct diagnosis came from following the dead drop analogy to its conclusion: a dead drop only works if someone is watching the window. Cursor and Claude Desktop are never watching. Remy always is.

By correctly diagnosing the constraint, the right solution became obvious: stop trying to make the dead drop autonomous, and instead give Remy a direct line to an execution layer that is actually scriptable. Claude Code CLI is that layer. It was available the whole time.

> **NOTE:** This section is preserved in the SAD as an architectural record, not just a conclusion. The reasoning that leads to a decision is as valuable as the decision itself — particularly when the earlier position was clearly stated and subsequently revised.

---

*— End of Document —*
