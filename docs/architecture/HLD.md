# Remy — High-Level Design (HLD)

**Version:** 1.0  
**Date:** 10/03/2026  
**Status:** Current  

This document summarises Remy’s high-level architecture. For full technical detail, see [remy-SAD.md](remy-SAD.md). For design decisions (heartbeat, sub-agents), see [remy-sad-v10.md](remy-sad-v10.md).

---

## 1. System purpose

Remy is a **single-user personal AI assistant** that:

- Talks to the user over **Telegram** (messages, voice, photos).
- Uses **Claude** (Anthropic) as the primary model with **native tool use**.
- Persists **memory** (goals, plans, facts, conversations) in SQLite and uses **sqlite-vec** for semantic search.
- Runs **proactive behaviour** via an **evaluative heartbeat** (HEARTBEAT.md): only contacts the user when thresholds warrant it.
- Handoff to Cursor/Claude Desktop is manual (relay feature removed; see [relay-removal.md](relay-removal.md)).

---

## 2. Conceptual architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Telegram interface (inbound messages, commands, streaming out)  │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  Agent core (session, memory injection, Claude, tool loop)       │
└──────────┬────────────────────────────┬─────────────────────────┘
           │                            │
┌──────────▼──────────┐    ┌────────────▼─────────────────────────┐
│  Memory             │    │  Tools (calendar, email, files, web,  │
│  SQLite + vec,      │    │  goals, plans, board, etc.)           │
│  conversations      │    └──────────────────────────────────────┘
└─────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│  Scheduler (evaluative heartbeat → agent core)                     │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│  Integrations (Google Workspace, Ollama fallback)                 │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Component boundaries

| Component | Responsibility | Does not own |
|-----------|----------------|--------------|
| **Telegram interface** | Receive updates, dispatch to agent, send/stream replies | Business logic |
| **Agent core** | Session lock, memory injection, Claude call, tool loop | Tool implementation |
| **Memory** | Persist and retrieve knowledge, conversations, goals, plans | AI calls |
| **Tools** | Implement capabilities (calendar, email, files, etc.) | Telegram interaction |
| **Scheduler** | Fire proactive triggers (heartbeat) at the right time | Building content |
| **Integrations** | Google API clients | Tool dispatch |

---

## 4. Data flow (simplified)

1. **Inbound:** Telegram → bot → session lock → load conversation + inject memory → Claude with tools.
2. **Tool loop:** Claude returns tool calls → registry dispatches to tool implementations → results back to Claude → stream reply.
3. **Outbound:** Stream to Telegram; optional crash-safe **outbound queue** for reliability.
4. **Proactive:** Scheduler runs **evaluative heartbeat** (HEARTBEAT.md); if thresholds say “contact user”, runs agent loop and sends message.

---

## 5. Key interfaces

- **Claude:** Single primary path via `ClaudeClient.stream_with_tools()` (see SAD §4.4).
- **Memory:** `MemoryInjector` builds the `<memory>` block; `KnowledgeStore` (and legacy Fact/Goal stores during migration) back it.
- **Tools:** `ToolRegistry` holds schemas and executors; one entry point for all tool execution.
---

## 6. Deployment

- **Local / server:** Docker Compose (remy + ollama) or `make run` (local).
- **Data:** `./data` — SQLite (`remy.db`), JSONL sessions, Google tokens.
- **Config:** `.env`; `config/SOUL.md`, `config/HEARTBEAT.md` (and optional `.local.md` overrides).

For deployment topology, scaling, and health endpoints, see [remy-SAD.md](remy-SAD.md) §6.
