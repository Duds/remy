# US: Multi-Agent Architecture (Leaf + Sub-Agent Pattern)

**Status:** ✅ Done (2026-03-11 — leaf base + web/file/gmail leaves; Researcher/Coder/Ops/Analyst + Creator + subagent_runner; PBI-1–10)
**Phase:** 7 (Step 3 — Claude Agent SDK Subagents)
**Priority:** S (Should Have)

---

## Overview

Break heavy and specialist work out of Remy's main handler path into a structured tree of leaf agents and sub-agents. Remy stays a thin UI/routing layer; all heavy lifting is delegated downward.

Architecture:
- **Leaf agents** — single-tool, single-call, structured I/O, 15s hard timeout
- **Sub-agents** — orchestrate 1–N leaves, synthesise results, return to Remy
- **Remy** — routes intent to the right sub-agent, delivers result to user

Sub-agents cannot spawn their own sub-agents (no recursive delegation).

---

## PBI-1 — Leaf agent base class

**As Remy, I need a standard leaf agent pattern so all leaves behave consistently.**

- Single Claude call, no loop
- Accepts: task, tool list (max 2), structured input
- Returns: structured JSON output + status
- Timeout: 15s hard limit
- AC: any leaf can be instantiated with a system prompt + tool list

---

## PBI-2 — Web search leaf

**As Researcher sub-agent, I need a leaf that executes a single web search and returns a clean summary.**

- Input: `{ query, max_results }`
- Tools: `web_search` only
- Output: `{ query, summary, sources[] }`
- AC: 1-shot, no follow-up calls

---

## PBI-3 — File read leaf

**As Ops sub-agent, I need a leaf that reads a file and extracts relevant content.**

- Input: `{ path, extraction_hint }`
- Tools: `read_file` only
- Output: `{ path, extracted_content, raw_length }`
- AC: 1-shot, no follow-up calls

---

## PBI-4 — Gmail search leaf

**As Ops sub-agent, I need a leaf that searches Gmail and returns structured results.**

- Input: `{ query, max_results, include_body }`
- Tools: `search_gmail` only
- Output: `{ results[], count }`
- AC: 1-shot, no follow-up calls

---

## PBI-5 — Researcher sub-agent

**As Remy, I need a Researcher sub-agent that orchestrates web search leaves in parallel and synthesises results.**

- Spins up 1–3 search leaves in parallel
- Synthesises into a structured report
- Returns report to Remy
- AC: handles partial leaf failures gracefully (returns partial results + error notes)

---

## PBI-6 — Coder sub-agent

**As Remy, I need a Coder sub-agent that handles code tasks via Claude Code or run_python.**

- Accepts: task description + optional repo path
- Delegates to `run_claude_code` or `run_python` leaf as appropriate
- Returns: output, exit code, summary
- AC: surfaces errors clearly to Remy; does not swallow failures

---

## PBI-7 — Ops sub-agent

**As Remy, I need an Ops sub-agent that handles file, email, and calendar tasks.**

- Routes to appropriate leaf (file read, Gmail search, calendar)
- Handles multi-step ops (e.g. search → label)
- Returns structured result to Remy
- AC: graceful fallback if a leaf times out

---

## PBI-8 — Analyst sub-agent

**As Remy, I need an Analyst sub-agent that handles calculations, data tradeoffs, and structured reasoning.**

- Uses `run_python` leaf for computation
- Returns: findings, recommendation, confidence
- AC: no web calls — analysis only; pure reasoning + computation

---

## PBI-9 — Remy delegation router

**As Remy, I need to automatically route tasks to the right sub-agent without asking the user.**

- Classify intent → pick sub-agent (Researcher / Coder / Ops / Analyst)
- Fire async, confirm to user immediately ("On it — I'll message you when done 🔄")
- Push result when done via existing BackgroundTaskRunner + Telegram callback
- AC: Board is explicitly excluded from auto-routing; Board = explicit user opt-in only

---

## PBI-10 — Async result delivery

**As Remy, I need to push sub-agent results to the user in Telegram when they're ready.**

- Store result in `background_jobs` table (existing BackgroundJobStore)
- Push message via `primary_chat_id` when complete
- Handle timeout/failure gracefully — always message the user, even on failure
- AC: user never left hanging; partial results surfaced with clear error context

---

## Constraints

- Sub-agents cannot spawn sub-agents (flat delegation tree only)
- Leaf agents: 15s hard timeout, max 2 tools
- Board of Directors is NOT part of this routing system — explicit user command only
- Builds on existing `BackgroundTaskRunner` and `BackgroundJobStore` (Phase 7 Steps 1–2)

---

## Related

- `US-claude-agent-sdk-subagents.md` — upstream architecture decision
- `US-persistent-job-tracking.md` — async result storage (✅ done)
- `docs/backlog/US-subagents-next-plan.md` — prior evaluation notes
- `TODO.md` Phase 7 Step 3
