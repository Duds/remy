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

> **NOTE — 07/03/2026:** Google released `gws` (Google Workspace CLI) on 06/03/2026. It is a single subprocess tool covering Drive, Gmail, Calendar, Sheets, Docs, Chat, and more — structured JSON output, 40+ agent skills, built for LLM integration. It is a candidate to replace the underlying API calls in Remy's Gmail, Calendar, Contacts, and Drive tool implementations — not the tool interfaces themselves, but what executes beneath them. The tool surface Remy exposes to Dale stays unchanged; `gws` handles data retrieval. Pre-v1.0 and under active development — evaluate for adoption at v1.0. See Section 10.2.1 for assessment of the `gws` MCP server against the relay pattern.

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

This follows the same pattern already established for SOUL.md: a public file defines structure and defaults; a gitignored local file holds personal overrides.

| File | Committed? | Contains |
|---|---|---|
| `config/HEARTBEAT.md` | Yes — public repo | Generic threshold categories, structure, extension points, model selection. No personal detail. |
| `config/HEARTBEAT.local.md` | No — gitignored | Personal thresholds, relationship context, wellbeing signals, calendar event tags, intimate behavioural triggers. |
| `config/HEARTBEAT.example.md` | Yes — public repo | Documented placeholder showing how to write a local override. Mirrors SOUL.example.md convention. |

The heartbeat loader merges both files at runtime. If `HEARTBEAT.local.md` does not exist, the heartbeat runs on public defaults only — the system degrades gracefully for other users cloning the repo.

```gitignore
config/*.local.md   # personal config — never commit
```

> **NOTE:** The `*.local.md` wildcard future-proofs the pattern. Any new personal config file created in `config/` is automatically excluded from version control without needing to update `.gitignore` again.

#### 5.2.2 Public HEARTBEAT.md — Structure

See `/config/HEARTBEAT.md` in the repo. Key sections: Goals, Calendar, Email, Reminders, Daily Orientation, End-of-Day Reflection, Wellbeing Check-in (stub — personal thresholds in local file), Model Selection, Silence Rules.

### 5.3 Heartbeat Architecture

| Component | Location | Description |
|---|---|---|
| `HEARTBEAT.md` | `config/HEARTBEAT.md` | Public evaluation template — generic categories and extension points. Committed to repo. |
| `HEARTBEAT.local.md` | `config/HEARTBEAT.local.md` | Personal overrides — private thresholds, relationship context, wellbeing signals. Gitignored. |
| `HEARTBEAT.example.md` | `config/HEARTBEAT.example.md` | Documented placeholder showing local override structure. Committed. Mirrors SOUL.example.md. |
| Config loader | `remy/scheduler/heartbeat.py` | Merges HEARTBEAT.md + HEARTBEAT.local.md at runtime. Gracefully skips local file if absent. |
| HeartbeatJob | `remy/scheduler/heartbeat.py` | Scheduler job — runs merged config evaluation, suppresses HEARTBEAT_OK |
| HeartbeatHandler | `remy/bot/heartbeat_handler.py` | Executes tool queries and passes results to model for evaluation |
| Silence guard | `remy/scheduler/heartbeat.py` | Enforces quiet hours — no heartbeat between 22:00 and 07:00 |
| Hook integration | `remy/hooks/lifecycle.py` | Emits `HEARTBEAT_START` and `HEARTBEAT_END` hook events for observability |
| Delivered flag | `data/remy.db — heartbeat_log` | Tracks what has been surfaced to prevent duplicate notifications |

### 5.4 Evaluation Logic

| Step | Action | Tool Used |
|---|---|---|
| 1 | Load and merge HEARTBEAT.md + HEARTBEAT.local.md into system context | File read (local file optional — skipped if absent) |
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
| Alcohol check (17:00) | Wellbeing check-in threshold | Multi-factor: time window, days since last check-in, recent conversation tone, unresolved emotional context. Context-triggered — not time-triggered. |

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

#### 10.2.1 gws MCP Server — Assessment Against the Relay

Google's `gws` CLI ships with a built-in MCP server. Assessment against the relay pattern:

| Dimension | relay_mcp/ | gws MCP server |
|---|---|---|
| What it carries | Any context packet — code, tasks, conversation, Workspace data | Workspace data only |
| Requires Remy? | Yes — Remy writes packets to the relay | No — direct Workspace access |
| Autonomous reception? | No — Cursor/Claude Desktop still pull-only | No — same constraint |
| Human-initiated use | Context handoff: Telegram → Cursor | Workspace queries direct from Cursor |
| Solves dead drop problem? | No | No |

> **ASSESSMENT:** The `gws` MCP server does not solve the relay dead drop problem. Cursor and Claude Desktop remain pull-only regardless of which MCP server they connect to. What `gws` does is make the human-initiated Workspace path cleaner — a human can query Gmail or Calendar from Cursor directly via `gws` MCP without Remy in the path. This is a complement to the relay, not a replacement. The relay handles general context passing; `gws` handles Workspace-specific data retrieval. Both are human-initiated. Neither is autonomous.

If `gws` reaches v1.0 stability, Remy's Workspace tool implementations could be refactored to shell out to `gws` rather than calling Google APIs directly. The tool interface stays the same. Remy's interpretation layer — priority senders, personal calendar context, `HEARTBEAT.local.md` significance — stays the same. Only data retrieval changes.

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

> **ARCHITECTURE DECISION:** Add `remy/tools/claude_code.py` — a subprocess tool that invokes the Claude Code CLI with task context and repo path, captures stdout/stderr, and returns the result to Remy. Add a Coding Tasks category to `HEARTBEAT.local.md` with thresholds for stalled tasks, open TODOs, and uncommitted work. Retain `relay_mcp/` as a human-initiated context bus. Do not attempt to make Cursor or Claude Desktop check the relay autonomously — this is architecturally impossible without modifying those tools.

| Component | Location | Priority | Description |
|---|---|---|---|
| `claude_code_tool` | `remy/tools/claude_code.py` | P2 | Subprocess wrapper for Claude Code CLI. Accepts task, context, repo_path. Returns result dict with stdout, stderr, exit_code. |
| Coding Tasks threshold | `config/HEARTBEAT.local.md` | P2 | Personal threshold category: stalled tasks, open TODOs, uncommitted work >N hours. Gitignored. |
| `relay_mcp/` | Existing | Retain as-is | Human-initiated context bus. No changes needed. Autonomous orchestration documentation removed. |

### 10.5 Honest Audit Trail

The relay MCP was described as a hero differentiator in SAD v1.0 and v2.0. That description was wrong — not because the relay is badly built, but because the premise (Cursor and Claude Desktop as autonomous receivers) was wrong.

The correct diagnosis came from following the dead drop analogy to its conclusion: a dead drop only works if someone is watching the window. Cursor and Claude Desktop are never watching. Remy always is.

By correctly diagnosing the constraint, the right solution became obvious: stop trying to make the dead drop autonomous, and instead give Remy a direct line to an execution layer that is actually scriptable. Claude Code CLI is that layer. It was available the whole time.

> **NOTE:** This section is preserved in the SAD as an architectural record, not just a conclusion. The reasoning that leads to a decision is as valuable as the decision itself — particularly when the earlier position was clearly stated and subsequently revised.

---

*— End of Document —*

---

## 11. Sub-Agent Architecture — Orchestrator Pattern

*Added 07/03/2026.*

### 11.1 Design Principle — Separation of Concerns

The core insight: Remy and the Orchestrator have fundamentally different jobs and must not share responsibilities. Remy knows Dale. The Orchestrator knows tasks. Workers know nothing except their specific job.

| Layer | Role | Knows About | Does Not Know About |
|---|---|---|---|
| Remy | User liaison | Dale — conversation, memory, goals, facts, SOUL, heartbeat | Worker status, raw results, task coordination |
| Orchestrator | Task coordinator | Task manifest, worker statuses, raw results, delegation context | Dale, conversation history, SOUL, personal context |
| Workers | Execution units | Their specific task and tools | Everything else |

> **KEY PRINCIPLE:** The Orchestrator synthesises raw worker results into structured findings and surfaces them to Remy. Remy layers those findings into the conversation naturally, alongside memory, goals, and personal context. The Orchestrator never talks to Dale directly.

### 11.2 Persistence Model — Injected Context, Not Resident State

Neither Remy nor the Orchestrator are alive between turns. Both are stateless inference calls that feel persistent because structured data is injected at the start of each turn. The persistence is in the data layer (SQLite), not the agent.

| Injected Context | Remy | Orchestrator |
|---|---|---|
| Personality / values | SOUL.md + SOUL.local.md | — |
| Behaviour config | HEARTBEAT.md + HEARTBEAT.local.md | TASK.md |
| Conversation history | Full recent history | — |
| Personal context | Goals, facts, memory, counters | — |
| Task state | — | Task manifest: delegations, worker statuses, results so far |
| Delegation context | — | Original request from Remy — what was asked and why |

> **NOTE:** The Orchestrator does not need a SOUL.md. It needs a **TASK.md** — its equivalent of HEARTBEAT.md. A plain text description of how to coordinate workers, what to do with results, how to synthesise, and when to report back to Remy. `TASK.local.md` is gitignored for personal task preferences.

### 11.3 Turn Trigger Model

Every agent turn follows the same pattern regardless of layer:

```
Turn trigger received
  → inject context from SQLite (appropriate to layer)
  → run inference (appropriate model tier)
  → act / delegate / respond
  → persist new state to SQLite
  → go idle
```

| Layer | Trigger Types |
|---|---|
| Remy | Dale message via Telegram; heartbeat threshold exceeded |
| Orchestrator | Remy delegation (new task); worker completion (collect result, update manifest, decide if job is done); heartbeat (surface stalled/failed tasks to Remy) |
| Workers | Orchestrator spawn instruction — single trigger, fire and complete |

### 11.4 Agent Hierarchy

```
Dale (Telegram)
  ↕
Remy  ←————————————————  user liaison: conversation, memory, goals, heartbeat
  ↕  delegates / receives synthesis
Orchestrator  ←——————————  task coordinator: spawns, tracks, synthesises
  ↕  spawns / collects results
Workers  ←———————————————  execution: one task, one result, report to orchestrator
  ├── ResearchAgent        (web search + summarise)
  ├── GoalWorker           (long-running goal step execution)
  └── CodeAgent            (wraps claude_code_tool)
```

Spawn depth is capped at 2 levels (Orchestrator → Worker). Workers do not spawn children. The one exception is a ResearchAgent spawning sub-topic workers — permitted but capped at 3 children maximum. Any deeper coordination is a signal the task should be broken into separate top-level delegations.

### 11.5 Concurrency Model

Workers run as `asyncio.create_task()` — lightweight coroutines on the existing event loop. No threads needed. The main Remy conversation loop stays fully responsive while workers run in the background.

| Concern | Approach | Rationale |
|---|---|---|
| Concurrency | `asyncio.create_task()` | No threads needed — Remy is already fully async |
| Worker isolation | Each worker gets its own task context — no shared state | Prevents result cross-contamination |
| Max concurrent workers | Configurable — default 5 (`SUBAGENT_MAX_WORKERS`) | Prevents runaway API cost |
| CodeAgent | subprocess (`claude_code_tool`) — not async task | CLI tool requires subprocess; result piped back to orchestrator |
| Task persistence | SQLite task manifest — survives Remy restart | Long-running tasks not lost if Remy restarts mid-job |

### 11.6 Task Manifest — SQLite Schema

```sql
CREATE TABLE agent_tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT UNIQUE NOT NULL,       -- stable identifier
    parent_id        TEXT,                       -- NULL = top-level delegation
    worker_type      TEXT NOT NULL,              -- research | goal | code
    status           TEXT NOT NULL,              -- pending | running | done | failed | stalled
    task_context     TEXT NOT NULL,              -- JSON: task definition from Remy
    result           TEXT,                       -- JSON: worker output when complete
    synthesis        TEXT,                       -- Orchestrator summary surfaced to Remy
    error            TEXT,                       -- failure detail if status = failed
    retry_count      INTEGER DEFAULT 0,
    depth            INTEGER DEFAULT 0,          -- spawn depth (max 2)
    created_at       DATETIME NOT NULL,
    started_at       DATETIME,
    completed_at     DATETIME,
    surfaced_to_remy BOOLEAN DEFAULT FALSE       -- heartbeat suppression flag
);
```

### 11.7 Task Lifecycle

| Status | Meaning | Next State | Heartbeat Behaviour |
|---|---|---|---|
| pending | Created, not yet picked up | running | Surface if pending >5 minutes |
| running | Worker asyncio task is active | done \| failed | Surface if running >SUBAGENT_STALL_MINUTES |
| done | Worker completed successfully | surfaced_to_remy = TRUE | Surface synthesis once, then suppress |
| failed | Worker threw unhandled error | retry or stalled | Surface immediately on next heartbeat cycle |
| stalled | Running > stall threshold | failed (after max retries) | Surface immediately — requires Dale decision |

> **NOTE:** Workers do not retry automatically. A failed task surfaces to Remy via heartbeat with the error detail. Remy presents it to Dale: *"The research task I started on X failed — want me to try again or approach it differently?"* Automatic retry without human awareness is a trust-breaker.

### 11.8 TASK.md — Orchestrator Behaviour Config

```markdown
# TASK.md

## Coordination Rules
- Maximum spawn depth: 2 (orchestrator → worker → child worker)
- Maximum concurrent workers: SUBAGENT_MAX_WORKERS (default 5)
- Stall threshold: SUBAGENT_STALL_MINUTES (default 30)

## Synthesis Rules
- Wait for all workers in a delegation to complete before synthesising
- If a worker fails, synthesise from available results and flag the gap
- Synthesis is structured JSON: {summary, findings[], gaps[], relevant_goals[]}
- Never include raw worker output in synthesis — distil only

## Escalation Rules
- Failed workers: surface to Remy via heartbeat with error detail
- Stalled workers: surface to Remy immediately — do not wait for heartbeat
- Do NOT retry automatically — surface to Remy and wait for decision

## Model Selection
- Coordination decisions (spawn, status check): Tier 1 (Mistral)
- Synthesis (distilling worker results): Tier 2 (Sonnet)
- Worker execution: Tier 1 (Mistral) for research/goal; see claude_code_tool for code
```

### 11.9 Heartbeat Integration

Sub-agent state integrates with the heartbeat via the `agent_tasks` table. No separate notification path needed.

```markdown
## Agent Tasks  (HEARTBEAT.md addition)
- Check agent_tasks for status = failed where surfaced_to_remy = FALSE
- Check agent_tasks for status = stalled where surfaced_to_remy = FALSE
- Check agent_tasks for status = done where surfaced_to_remy = FALSE
- Surface failed/stalled immediately — do not suppress
- Surface completed tasks in the next natural heartbeat window
- Set surfaced_to_remy = TRUE after delivery
- Use task synthesis field as message content — never raw worker output
```

### 11.10 Component Summary

| Component | Location | Priority | Description |
|---|---|---|---|
| Orchestrator | `remy/agents/orchestrator.py` | P2 | Stateless coordinator. Injected with task manifest + TASK.md each turn. Spawns workers, collects results, synthesises for Remy. |
| SubagentRunner | `remy/agents/runner.py` | P2 | Manages asyncio task pool. Enforces max workers and spawn depth. Persists task state to SQLite. |
| ResearchAgent | `remy/agents/workers/research.py` | P2 | Web search + summarise worker. Tier 1 model. Reports structured findings to orchestrator. |
| GoalWorker | `remy/agents/workers/goal.py` | P2 | Long-running goal step execution. Reads goal/plan context from SQLite. Reports step completion or blockers. |
| CodeAgent | `remy/agents/workers/code.py` | P2 | Thin wrapper around `claude_code_tool`. Passes task + repo_path, returns stdout/stderr/exit_code to orchestrator. |
| `agent_tasks` table | `data/remy.db` | P2 | Task manifest. Persists across restarts. Read by heartbeat for stall/fail/done detection. |
| TASK.md | `config/TASK.md` | P2 | Public orchestrator behaviour config. `TASK.local.md` gitignored. |

### 11.11 Configuration

| Variable | Default | Description |
|---|---|---|
| `SUBAGENT_MAX_WORKERS` | `5` | Maximum concurrent asyncio worker tasks |
| `SUBAGENT_MAX_DEPTH` | `2` | Maximum spawn depth |
| `SUBAGENT_MAX_CHILDREN` | `3` | Maximum children per worker (research sub-topics only) |
| `SUBAGENT_STALL_MINUTES` | `30` | Minutes before a running task is marked stalled |
| `SUBAGENT_WORKER_MODEL` | `mistral` | Default model for worker execution (Tier 1) |
| `SUBAGENT_SYNTH_MODEL` | `claude-sonnet-4-20250514` | Model for orchestrator synthesis (Tier 2) |
| `TASK_MD_PATH` | `config/TASK.md` | Path to orchestrator behaviour config |

### 11.12 Implementation Sequence

Sub-agents depend on lifecycle hooks (P1) and write-ahead queue (P1) being in place first. Build order within P2:

1. `agent_tasks` schema — add to remy.db migrations
2. `SubagentRunner` — task pool, asyncio management, SQLite persistence
3. `Orchestrator` — context injection, TASK.md loader, synthesis
4. `ResearchAgent` — first worker (simplest: web search + summarise)
5. Heartbeat integration — add Agent Tasks section to HEARTBEAT.md, wire heartbeat queries
6. `GoalWorker` — goal step execution (requires SubagentRunner stable)
7. `CodeAgent` — claude_code_tool wrapper (depends on Section 10)

> **ARCHITECTURE DECISION:** Build ResearchAgent first. It has no dependencies on `claude_code_tool` or goal state, uses only web tools Remy already has, and produces a clear testable output. It is the right first worker to validate the full orchestrator → worker → heartbeat loop end-to-end before building more complex workers.

---

## 12. Skills System

Remy's skills system extends the SOUL.md / HEARTBEAT.md / TASK.md config pattern to task-type-specific behavioural instructions. Skills are plain Markdown files loaded into inference context before a task executes. They encode accumulated best practice so the model does not rediscover patterns through trial and error, and so behaviour can be iterated by editing a text file rather than deploying code.

> **DESIGN PRINCIPLE:** Skills are Markdown, not code. Behavioural logic in Python is expensive to change and invisible to inspection. Behavioural logic in a text file is cheap to iterate, reviewable in git, and overridable per-user without touching the codebase. All skill behaviour should start in config and only move to code when config is provably insufficient.

### 12.1 What a Skill Is

A skill file is a Markdown document containing instructions specific to a task type. It is injected into the system prompt alongside SOUL.md, TASK.md, or HEARTBEAT.md at task-start. Skills are composable — multiple skills can be loaded for a single task.

| Property | Value |
|---|---|
| Format | Plain Markdown |
| Location | `config/skills/{name}.md` |
| Local override | `config/skills/{name}.local.md` — gitignored |
| Loaded by | `remy/skills/loader.py` |
| Composable? | Yes — multiple skills merged for one task |
| Versioned? | Yes — git history tracks behaviour evolution |
| Hot-reloadable? | Yes — read from disk at task-start, no deploy needed |

### 12.2 Skill Directory Structure

```
config/
  SOUL.md
  HEARTBEAT.md
  TASK.md
  skills/
    research.md           # how to conduct and scope research tasks
    goal-planning.md      # how to decompose goals into executable steps
    email-triage.md       # how to prioritise and draft email responses
    code-review.md        # what to look for when reviewing diffs
    meeting-prep.md       # how to prepare for a calendar event
    daily-briefing.md     # structure and priorities for morning orientation
    *.local.md            # gitignored — personal overrides per skill
```

### 12.3 remy/skills/loader.py

```python
def load_skill(name: str) -> str:
    """Load base + local skill, return merged string."""
    base = Path(f"config/skills/{name}.md")
    local = Path(f"config/skills/{name}.local.md")
    parts = [p.read_text() for p in [base, local] if p.exists()]
    return "\n\n".join(parts).strip()

def load_skills(names: list[str]) -> str:
    """Load and concatenate multiple skills."""
    return "\n\n---\n\n".join(load_skill(n) for n in names if load_skill(n))
```

### 12.4 Injection Points

| Component | Skill(s) Loaded | When |
|---|---|---|
| `SubagentRunner` | `load_skill(worker_type)` | At worker spawn — passed alongside task context |
| `Orchestrator` | `load_skill("research")` etc. | At task-start — injected with TASK.md into system prompt |
| `heartbeat.py` | `load_skill("daily-briefing")` etc. | When a threshold fires — skill shapes output format |
| `chat.py` | `load_skills(["email-triage"])` etc. | When intent detected — that inference call only |

> **CONSTRAINT:** Skills are injected per-call only. Not appended to SOUL.md or merged into the base system prompt. A skill loaded for an email-triage call does not persist into the next turn. This keeps context windows lean and skills focused.

### 12.5 Skill Authoring Rules

- Write as instructions to the model, not descriptions of the task.
- Include output format requirements explicitly — define JSON schemas in the skill file if needed.
- Keep each skill under 500 words. If it grows beyond that, split into two skills.
- Use `*.local.md` for personal preferences — tone, priorities, named contacts. Never commit personal data to the base skill.
- Skills should be stable. If you edit a skill every week, the logic belongs in `HEARTBEAT.local.md` or `SOUL.local.md` instead.

### 12.6 What NOT to Build

| Temptation | Why Not |
|---|---|
| Skill registry / discovery system | Plain files in a directory are the registry. |
| Skill versioning layer | Git is the version control system. |
| Dynamic skill selection by the model | Injection points are explicit in code — the model does not choose its own skills. That is a trust boundary. |
| Skill performance evals at build time | Premature. Build the loop first. |
| Nested skill inheritance | Flat directory. One level of local override. No hierarchies. |

### 12.7 Implementation Sequence

1. `remy/skills/loader.py` — 20 lines, no dependencies
2. `config/skills/research.md` — validates injection into ResearchAgent
3. `config/skills/daily-briefing.md` — validates heartbeat injection
4. `config/skills/email-triage.md` — validates chat.py intent detection injection
5. `config/skills/goal-planning.md` — validates GoalWorker injection
6. `config/skills/meeting-prep.md` — validates meeting threshold injection
7. `config/skills/code-review.md` — validates CodeAgent review context

> **ARCHITECTURE DECISION:** Implement `loader.py` and `research.md` in the same sprint as ResearchAgent (Section 11.12 Step 4). The skill and the worker are developed together — the skill defines what the worker should do, the worker validates that the skill is clear enough to produce consistent output.

---

*— End of Document —*
