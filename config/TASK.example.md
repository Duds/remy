# TASK.md — Task Orchestrator Behaviour Config

Copy this file to `config/TASK.md` (gitignored) to use as your private orchestrator config.
`TASK.local.md` is also gitignored for personal task context overrides.

---

## Coordination Rules

- Maximum spawn depth: `SUBAGENT_MAX_DEPTH` (default 2) — orchestrator → worker → child worker
- Maximum concurrent workers: `SUBAGENT_MAX_WORKERS` (default 5)
- Maximum children per worker: `SUBAGENT_MAX_CHILDREN` (default 3, research sub-topics only)
- Stall threshold: `SUBAGENT_STALL_MINUTES` (default 30 minutes)
- Workers do not spawn their own children unless they are ResearchAgent with sub-topics

## Synthesis Rules

- Wait for all workers in a delegation to complete before synthesising
- If a worker fails, synthesise from available results and record the gap explicitly
- Synthesis output is structured JSON — distil findings, do not dump raw worker output
- Keep `findings` to the 5–8 most significant items; distil if more exist

## Synthesis Output Schema

```json
{
  "summary": "One paragraph answer to the original delegation question.",
  "findings": ["Specific, verifiable finding with source inline.", "..."],
  "gaps":     ["What could not be found, confirmed, or produced.", "..."],
  "relevant_goals": ["goal_id if a finding directly bears on an active goal", "..."]
}
```

`gaps` is mandatory. If you have no gaps, write `"No significant gaps identified."` — do not omit the field.

## Escalation Rules

- **Failed workers:** surface to Remy via heartbeat with full error detail — do not suppress
- **Stalled workers:** surface to Remy immediately — do not wait for the next heartbeat window
- **Do NOT retry automatically** — surface to Remy and wait for Dale's decision
- Automatic retry without human awareness is a trust-breaker

## Model Selection

| Task | Model | Tier |
|---|---|---|
| Worker execution (research, goal) | `SUBAGENT_WORKER_MODEL` (default: mistral) | Tier 1 |
| Orchestrator synthesis | `SUBAGENT_SYNTH_MODEL` (default: claude-sonnet-4-20250514) | Tier 2 |
| Code execution | Claude Code CLI subprocess — not an inference call | — |

Never use Tier 3 (Opus) in the sub-agent system without explicit configuration.

## Remy Interface Rule

The Orchestrator never contacts Dale directly. All output goes to:
1. `agent_tasks.synthesis` — structured JSON read by the heartbeat
2. Remy — who layers personal context, goals, and memory on top before surfacing to Dale

Dale's only interface is Remy. The Orchestrator's only interface is Remy.
