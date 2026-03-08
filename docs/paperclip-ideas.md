# Paperclip → Remy Ideas

> Researched from https://github.com/paperclipai/paperclip on 2026-03-08.
> Paperclip is a Node.js agent orchestration platform ("If an agent is an employee, Paperclip is the company").
> Below are features worth porting or adapting into Remy, ordered by estimated impact.

---

## 1. PARA Memory Files (High Impact)

**What paperclip does:**
Three-layer persistent memory using Tiago Forte's PARA method:

- **Layer 1 — Knowledge Graph** (`$AGENT_HOME/life/`): Entity folders (projects, areas/people, areas/companies, resources, archives), each with:
  - `summary.md` — quick-reference loaded first
  - `items.yaml` — atomic facts, loaded on-demand
- **Layer 2 — Daily Notes** (`$AGENT_HOME/memory/YYYY-MM-DD.md`): Raw timeline of events; written continuously.
- **Layer 3 — Tacit Knowledge** (`$AGENT_HOME/MEMORY.md`): User-specific operational patterns ("how Dale works"), not abstract facts.

**Core philosophy:** "Memory does not survive session restarts. Files do."

**Entity creation threshold:** Only create a PARA entity folder if:
- Mentioned 3+ times in conversation, OR
- Direct relationship to user (family, coworker, partner, client), OR
- Significant project/company in user's life.
- Otherwise: write to daily notes only.

**Fact lifecycle:** Never delete facts — supersede them:
```yaml
status: superseded
superseded_by: "updated fact content here"
```

**Weekly synthesis:** Rewrite `summary.md` from active `items.yaml` facts weekly.

**For Remy:** Remy has SQLite facts/knowledge/goals with embeddings, but no structured PARA hierarchy or per-entity summary files. A PARA adapter on top of the existing `KnowledgeStore` — or a file-based parallel store for long-lived entities (people, companies, projects) — would give much richer cross-session context. The "supersede, don't delete" rule is worth adopting in the DB schema too (add `superseded_by` to the `knowledge` table).

---

## 2. `qmd` — Semantic Memory Search CLI (Medium Impact)

**What paperclip does:**
Uses a `qmd` command-line tool for searching the PARA memory store:
```sh
qmd query "question"    # semantic search with reranking
qmd search "phrase"     # BM25 keyword matching
qmd vsearch "concept"   # pure vector similarity
qmd index $AGENT_HOME   # index personal folder
```

**For Remy:** Remy already has FTS5 + sqlite-vec + sentence-transformers. Exposing these as a small CLI script (or a Makefile target) would let Dale (or relay tasks) query memory directly without going through the Telegram bot. Could also be useful for debugging the knowledge base.

---

## 3. Formal Heartbeat Protocol — 9-Step Work Procedure (High Impact)

**What paperclip does:**
Every agent heartbeat follows a structured 9-step loop:

1. **Identity** — Fetch own metadata (verify you're the right agent)
2. **Approvals** — If triggered by an approval event, handle it first
3. **Assignments** — Query assigned tasks (todo, in_progress, blocked)
4. **Pick Work** — Prioritize `in_progress` first; skip blocked tasks if *your* last comment was the most recent (dedup rule — see §4)
5. **Checkout** — Atomically claim the task; 409 conflict = someone else owns it, never retry
6. **Context** — Read full issue + comment thread + parent issues for goal ancestry
7. **Do Work** — Execute with available tools
8. **Update Status** — Mark done/blocked/cancelled with a comment; always include run ID
9. **Delegate** — Create subtasks linked to parent and goal IDs

**Critical rules:**
- Never self-assign without explicit @-mention + checkout
- Never retry a 409 (conflict = another agent owns it)
- Always comment before exiting a heartbeat (except the blocked-task dedup case)
- Escalate via chain-of-command when truly stuck

**For Remy:** Remy's CLAUDE.md defines a similar loop but informally. Formalising steps 4 (work priority), 5 (atomic claim with conflict guard), and 9 (delegation with parent linking) would make relay task handling more robust — especially as cowork sends more tasks concurrently.

---

## 4. Blocked-Task Deduplication (Medium Impact)

**What paperclip does:**
When scanning assigned tasks, skip a blocked task entirely if **your own prior comment was the last update**. This prevents the agent from re-commenting "still blocked" on every heartbeat, which wastes budget and creates noise.

**For Remy:** Relay tasks can get stuck in `needs_clarification`. Remy should track whether it already posted a message about a blocked task and skip re-pinging cowork until cowork responds.

---

## 5. Budget Enforcement / Cost Control (High Impact)

**What paperclip does:**
- Per-agent monthly budget cap
- Auto-pause at 100% utilisation
- At >80%, focus only on critical/high-priority tasks, defer lower-priority work

**For Remy:** Remy already logs API costs per model (`api_calls` table + telemetry). The next step is adding a monthly budget ceiling in config and enforcing it: warn Dale at 80%, refuse non-critical LLM calls at 100%, and surface this in the morning briefing ("you've used $X of your $Y monthly budget").

---

## 6. Approval Gates (Medium Impact)

**What paperclip does:**
Before certain high-stakes actions, an agent must POST an approval request and wait for a board member to approve or reject. The heartbeat is re-triggered with the approval result as context.

**For Remy:** Remy currently handles Gmail deletes and label operations without confirmation. An approval gate — asking Dale via Telegram inline button before executing a bulk delete — would prevent accidents. This maps naturally to Remy's existing inline callback system.

---

## 7. Goal Ancestry Chains (Medium Impact)

**What paperclip does:**
Every task carries a `goalId` pointing to its parent goal. Subtasks carry both `parentId` (immediate parent issue) and `goalId` (top-level objective). This means agents always know *why* they're doing a task, not just *what*.

**For Remy:** Remy has `plans` linked to `goals` (one-to-one). Extending this to support deep chains — plan step → plan → goal → higher-order goal — would allow Remy to explain decisions ("I'm labelling these emails as 4-Personal because it supports your goal 'reduce inbox cognitive load', which supports 'better focus during work hours'").

---

## 8. Outgoing Webhooks for Agent Events (Lower Impact)

**What paperclip does (PR #303):**
Adds outgoing webhooks fired on agent events (task status changes, new comments, approvals). External systems can subscribe.

**For Remy:** Remy has a health server on port 8080. Adding webhook dispatch when relay tasks complete (or when a plan step finishes) would let cowork poll or subscribe rather than relying only on relay messages. Lower priority but clean integration point.

---

## 9. Idempotency Keys for Recurring Task Creation (Medium Impact)

**What paperclip does (PR #282):**
Prevents duplicate issues when a recurring trigger fires twice (e.g. cron overlap). Each recurring issue creation includes an `idempotencyKey`; the backend deduplicates.

**For Remy:** Remy's automation cron jobs run inside APScheduler, which is generally safe, but startup reconciliation (running missed daily jobs) can occasionally fire a job twice if the process crashes at the wrong moment. Adding an idempotency key to background_jobs (e.g. `date + job_type`) would prevent double-execution.

---

## 10. Auto-Requeue on Failure (Medium Impact)

**What paperclip does (PR #278):**
If an agent's heartbeat crashes mid-task, the task is automatically re-queued rather than left in a zombie `in_progress` state. A configurable retry count + backoff.

**For Remy:** Relay tasks that Remy claims (`in_progress`) but fails to complete (e.g. Gmail API error) stay stuck. Adding a timeout + auto-revert to `pending` after N minutes would allow cowork to reassign them.

---

## 11. Portable Company Templates / "ClipMart" (Lower Impact)

**What paperclip does (planned):**
Export an entire agent configuration (goals, plans, agent roles, skill assignments) as a template. Import into a new instance with secrets scrubbed.

**For Remy:** Not directly applicable since Remy is single-user, but the concept of exportable SOUL.md + config templates (without secrets) is useful for sharing Remy setups across Dale's machines or for open-sourcing personality configs.

---

## 12. Permission System — `canCreateTasks` (Lower Impact)

**What paperclip does (PR #301):**
Agents have explicit permissions. `canCreateTasks` controls whether an agent can spawn new subtasks or only work on assigned ones.

**For Remy:** If Remy gains the ability to spawn cowork subtasks via relay, adding a permission flag in config (`RELAY_CAN_CREATE_TASKS=true/false`) would prevent runaway task creation.

---

## Summary Table

| Idea | Effort | Impact | Priority |
|------|--------|--------|----------|
| PARA memory files | High | High | ⭐⭐⭐ |
| Budget enforcement (auto-pause) | Low | High | ⭐⭐⭐ |
| Formal heartbeat protocol | Medium | High | ⭐⭐⭐ |
| Approval gates for bulk actions | Medium | High | ⭐⭐⭐ |
| Blocked-task dedup | Low | Medium | ⭐⭐ |
| Goal ancestry chains | Medium | Medium | ⭐⭐ |
| Auto-requeue stuck relay tasks | Low | Medium | ⭐⭐ |
| Idempotency keys for cron jobs | Low | Medium | ⭐⭐ |
| Supersede-not-delete for facts | Low | Medium | ⭐⭐ |
| `qmd` CLI for memory search | Medium | Low | ⭐ |
| Outgoing webhooks | High | Low | ⭐ |
| `canCreateTasks` permission flag | Low | Low | ⭐ |
| Portable SOUL templates | Low | Low | ⭐ |

---

## Addendum: Additional Patterns from Paperclip Docs

*(Sourced from `docs/guides/agent-developer/` — found during deeper crawl)*

### Skill Files per Task Type

Paperclip skills use YAML frontmatter as routing metadata:
```yaml
---
name: gmail-labeling
description: |
  Use when: applying Gmail labels from a query or label spec.
  Avoid when: you need to read email content (use gmail-audit instead).
---
```
The agent reads skill metadata first, then decides whether to load full instructions. This keeps context lean. **Remy could add `config/skills/gmail-label/SKILL.md`, `config/skills/gmail-audit/SKILL.md`, etc.**

### Session-End Audit Note

Post a `relay_post_note` at the end of every session summarizing what was done:
```python
relay_post_note(
    from_agent="remy",
    content="Session 2026-03-08: labelled 47 emails (4-Personal), trashed 12 LinkedIn. 1 task needs_clarification (label missing).",
    tags=["session-log", "2026-03-08", "gmail"]
)
```
Creates a searchable audit trail across sessions. **Already possible with Remy's relay tools — just needs to be added to CLAUDE.md as a closing step.**

### Decision Documentation

When Remy makes a non-obvious call (e.g. skipping a missing label instead of creating it), post a note:
```python
relay_post_note(
    from_agent="remy",
    content="Decision: skipped label '5-Hobbies' — not found, didn't create to avoid polluting label list.",
    tags=["decision", "gmail", "2026-03-08"]
)
```
Builds a record of judgment calls cowork can review.

### @-Mention Discipline

Paperclip enforces: **messages = FYIs / clarifications; tasks = authoritative work units.** Don't use `relay_post_message` to create assignments — use `relay_update_task`. Each message to cowork costs budget and triggers a heartbeat. Reserve messages for genuine blockers or handoffs.

### "Never Silent on Blocked Work"

Before setting a task to `needs_clarification`, always:
1. Update the task with specific notes explaining what's missing
2. Post a message to cowork with a suggested resolution option
3. Never just leave a task in `in_progress` without a comment

This prevents zombie tasks and gives cowork enough context to unblock without back-and-forth.

### Sources (Paperclip docs)

- [heartbeat-protocol.md](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/heartbeat-protocol.md)
- [task-workflow.md](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/task-workflow.md)
- [comments-and-communication.md](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/comments-and-communication.md)
- [writing-a-skill.md](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/writing-a-skill.md)
- [adapters/overview.md](https://github.com/paperclipai/paperclip/blob/master/docs/adapters/overview.md)
