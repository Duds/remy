## Personal Agent Orchestrator Design

This document outlines a **multi-model orchestration strategy** for a personal AI assistant using **Claude, Mistral, and Moonshot AI** only, optimising **cost, performance, and functionality** with a focus on snappy Telegram interface responsiveness.

---

### 1. Agent Architecture Overview

- **Orchestrator / Router:** Determines task type, context window requirements, and routes to the optimal model.

- **Task Modules:**
  1. Email summarisation and notifications (CRON-based)
  2. Local RAG access across your computer
  3. Action execution (e.g., food ordering, scripts, scheduling)

- **Memory & Persistence Layer:** Stores embeddings, task history, summaries, and cached outputs.

- **Cost-Aware Layer:** Minimises token costs via model selection and caching.

- **UI Consideration:** Telegram interface must remain responsive; prioritise low-latency models for short messages and confirmations.

---

### 2. Model Orchestration Strategy

**Routing principles:**

1. Start with **cheapest capable model**.
2. Escalate if task exceeds context, performance, or safety threshold.
3. Cache recurring outputs to reduce token usage.
4. Split long or complex tasks into subtasks handled by multiple models.

#### Task to Model Mapping

| Task Type                                           | Recommended Model(s)                               | Notes                                                                         |
| --------------------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------------------- |
| Short-context summarisation (emails, notifications) | Mistral Medium, Claude Haiku                       | Fast, low-cost; ensures snappy Telegram responses                             |
| Long-context summarisation / RAG                    | Mistral Large, Claude Sonnet, Moonshot K2 Thinking | Route only top-N retrieved segments from RAG; cache frequently used summaries |
| Reasoning-heavy / agentic tasks                     | Moonshot K2 Thinking, Claude Opus                  | Handles planning, multi-step tasks, orchestration of sub-agents               |
| Safety-critical / action execution                  | Claude Sonnet, Claude Opus                         | Validate any system-level or financial actions                                |
| Code generation / scripting                         | Mistral 7B-instruct, Moonshot K2 Thinking          | Prefer cloud API for large tasks; Mistral for moderate tasks                  |
| Roleplay / persona                                  | Moonshot K2 Thinking, Claude Sonnet                | Balance speed vs context length for Telegram interaction                      |

---

### 3. Model Routing Table with Thresholds

| Task Category                   | Min Model            | Max Model            | Context Window Threshold | Token Limit / Escalation              | Notes                                                      |
| ------------------------------- | -------------------- | -------------------- | ------------------------ | ------------------------------------- | ---------------------------------------------------------- |
| Routine short text              | Mistral Medium       | Claude Haiku         | < 50k                    | Escalate if output incomplete         | Fast, low-cost for snappy responses                        |
| Standard summarisation          | Mistral Large        | Claude Sonnet        | 50k–128k                 | Escalate if task exceeds capacity     | Cache top-N segments from RAG                              |
| Long-form summarisation / RAG   | Mistral Large        | Moonshot K2 Thinking | 128k–1M                  | Escalate if summary incomplete        | Use only retrieved relevant segments to reduce token usage |
| Multi-step reasoning / planning | Moonshot K2 Thinking | Claude Opus          | 256k–1M                  | Escalate if task is agentic           | Split subtasks; use cheapest capable model per subtask     |
| Safety-critical actions         | Claude Sonnet        | Claude Opus          | Any                      | N/A                                   | Always validate action before execution                    |
| Code generation / scripting     | Mistral 7B-instruct  | Moonshot K2 Thinking | 128k                     | Escalate for complex multi-file tasks | Use Mistral for small/moderate tasks to reduce latency     |
| Roleplay / persona              | Moonshot K2 Thinking | Claude Sonnet        | 128k–256k                | Escalate if conversation too long     | Maintain Telegram snappiness                               |

---

### 4. Cost and Latency Optimization Principles

1. **Dynamic Escalation:** Always try lowest-cost capable model; escalate only when output is insufficient.
2. **Cache Reuse:** Store embeddings, summaries, and repeated outputs locally.
3. **Task Batching:** Use CRON jobs for repetitive tasks to reduce repeated API calls.
4. **Context Segmentation:** Split large tasks for low-cost models; escalate for aggregation only if needed.
5. **Telegram Responsiveness:** Use smaller models (Mistral Medium, Claude Haiku) for interactive messages; reserve Moonshot / Claude Opus for batch or complex reasoning behind the scenes.

---

### 5. Suggested Workflow Example

**Scenario:** Weekly email summary + plan Friday dinner

1. **Fetch emails (CRON)** → Mistral Medium / Claude Haiku for short emails to ensure fast Telegram response.
2. **Summarise long emails** → segment + Mistral Large / Claude Sonnet.
3. **Aggregate weekly summary** → Moonshot K2 Thinking / Claude Sonnet for large context.
4. **Plan dinner order** → K2 Thinking plans steps; Mistral Medium executes API calls.
5. **Verify action** → Claude Sonnet confirms details before ordering.
6. **Store summaries** → local cache for next CRON run.

This setup **maximises use of your current API accounts**, keeps **Telegram interactions responsive**, and allows **cost-efficient escalation** for complex reasoning tasks.
