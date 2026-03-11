# Remy documentation

Current-state documentation for the Remy personal AI assistant. Australian English, DD/MM/YYYY.

---

## Quick links

| Document | Purpose |
|----------|---------|
| [Concept Design](architecture/concept-design.md) | Vision, problem statement, personas, core features, scope, non-goals |
| [High-Level Design (HLD)](architecture/HLD.md) | Component diagram, data flow, key interfaces |
| [Software Architecture Document (SAD)](architecture/remy-SAD.md) | Full technical architecture, stack, deployment, quality |
| [SAD Design Decisions (v10)](architecture/remy-sad-v10.md) | Evaluative heartbeat, sub-agents, skills |
| [Consolidation review (Mar 2026)](architecture/consolidation-review-2026-03.md) | Structural review, refactor roadmap |
| [Engineering review (Mar 2026)](architecture/engineering-review-2026-03.md) | Code quality, testing, security, recommendations |

---

## Setup and operations

| Document | Purpose |
|----------|---------|
| [Server setup](SERVER-SETUP.md) | Env, SOUL, HEARTBEAT checklist for a Remy server |
| [Agent tooling setup](agent-tooling-setup.md) | Cursor, Claude Desktop, MCP, hooks |

---

## Architecture (current)

- **concept-design.md** — Executive summary, objectives, user personas, features, UI, scope, non-goals.
- **HLD.md** — High-level components and data flow; entry point for new contributors.
- **remy-SAD.md** — Authoritative SAD: stack, system context, data, deployment, non-functional.
- **remy-sad-v10.md** — Design decisions: evaluative heartbeat, sub-agents, skills system.
- **consolidation-review-2026-03.md** — Target architecture, refactor phases, feature rationalisation.
- **engineering-review-2026-03.md** — Code quality, test gaps, security, tech debt.
- **subagent-handoff-and-testing.md** — Sub-agent handoff and testing approach.
- **zero-trust-audit.md** — Security audit and zero-trust considerations.
- **remy-build-skills.md** — Skills system (config-driven behaviour).

---

## Backlog

User stories and product backlog items live in [backlog/](backlog/). Completed and obsolete PBIs are moved to [backlog/archive/](backlog/archive/). See [backlog/_TEMPLATE.md](backlog/_TEMPLATE.md) for the story format.

---

## Archive

Superseded and reference-only docs are in [archive/](archive/). See [archive/README.md](archive/README.md) for what was archived and why.
