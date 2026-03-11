# User Story: Agent Creator (Build Sub-Agents On Demand)

**Status:** ✅ Done (Researcher + Coder/Ops/Analyst via spawn_and_hand_off; subagent_runner; 2026-03-11)
**Phase:** 7 (Step 3 — Claude Agent SDK Subagents)
**Priority:** S (Should Have)

---

## Summary

As Remy, I want an Agent Creator that classifies tasks, builds an appropriate sub-agent spec, spawns it, and hands off so that long-running work is delegated to the right specialist instead of the Board or the main loop. Board stays explicit opt-in; the Creator routes to Researcher, Coder, Ops, or Analyst.

---

## Background

Today when the main agent hits `max_iterations` or faces a heavy task, the only hand-off target was the Board (Bug 47). The Board is for strategic, multi-perspective analysis — not research, code, file ops, or data analysis. We fixed Bug 47 by showing step-limit UI instead of auto-handing off to Board.

The user wants an **Agent Creator**: a component that builds the right sub-agent for the task and hands off. Per [US-multi-agent-architecture](../US-multi-agent-architecture.md), leaves are fixed primitives; sub-agents orchestrate leaves. The Creator builds **sub-agent specs** (which leaves to use, system prompt, constraints) and spawns them — it does not create new leaves.

Related: Bug 47 (fixed), `docs/archive/subagent-handoff-and-testing.md`, `docs/backlog/US-multi-agent-architecture.md`.

---

## Acceptance Criteria

1. **Classification.** Given a task description (from user message or last turn), the Creator classifies intent into one of: `research`, `coder`, `ops`, `analyst`. Unknown or ambiguous → no hand-off; show step-limit instead.
2. **Spec builder.** For each type, the Creator returns a sub-agent spec: `{ type, system_prompt, allowed_tools[], max_turns, timeout_s }`. Uses template-based specs (no dynamic leaf creation).
3. **Hand-off.** When classification yields a type, Creator spawns the sub-agent via `BackgroundTaskRunner` (or equivalent), hands off the task, and confirms to the user ("On it — researching that for you 🔄").
4. **Result delivery.** Sub-agent result is pushed via existing `BackgroundTaskRunner` / `BackgroundJobStore` and Telegram callback. User is never left hanging.
5. **Board excluded.** Board is never chosen by the Creator. Board = explicit user opt-in only (`/board`, "convene the board").
6. **Leaves fixed.** Creator does not define new leaves. It composes existing leaf tools into sub-agent specs.

---

## Implementation

**Files created/modified:** `remy/agents/creator.py`, `remy/agents/subagent_runner.py`, `remy/ai/claude_client.py`, `remy/bot/handlers/chat.py`, `remy/ai/tools/registry.py`, `remy/ai/tools/web.py`.

---

## Out of Scope

- Dynamic leaf creation (leaves remain fixed)
- Board as a Creator target (Board = explicit opt-in only)
- Recursive sub-agents (sub-agents cannot spawn sub-agents)
