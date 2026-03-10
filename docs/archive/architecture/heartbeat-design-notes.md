# Heartbeat Design Notes (SAD v7)

Short answers to common questions about the evaluative heartbeat.

---

## 1. HEARTBEAT.md vs HEARTBEAT.example.md

**HEARTBEAT.md is gitignored** — your private config. The repo ships **HEARTBEAT.example.md** as the only committed template.

- If **HEARTBEAT.md** exists, the loader uses it.
- If HEARTBEAT.md is missing (e.g. fresh clone), the loader uses **HEARTBEAT.example.md** so the app runs out of the box.
- Copy `config/HEARTBEAT.example.md` → `config/HEARTBEAT.md` and customise; your HEARTBEAT.md is never committed, so forks never see your private settings.

---

## 2. How do HEARTBEAT and SOUL interact?

**Currently they do not interact in code.**

| File | Purpose | Used by |
|------|---------|--------|
| **SOUL.md** | Remy’s identity, personality, tone, operating principles | Main chat system prompt (`settings.soul_md`), briefings, proactive pipeline |
| **HEARTBEAT.md** | Evaluation checklist: when to contact the user, model selection, silence rules | Heartbeat job only |

The heartbeat handler uses a **fixed system prompt** (“You are the evaluative heartbeat. Be concise…”) and does **not** load SOUL.md. So:

- **Proactive messages from the heartbeat** are not explicitly tuned to SOUL’s voice; they follow HEARTBEAT.md and the short system prompt.
- **Proactive messages from the old crons** (morning briefing, evening check-in, etc.) go through the full pipeline and **do** use SOUL.

If you want heartbeat-originated messages to match SOUL’s tone, options are:

- **Option A:** Prepend a one- or two-sentence “identity” line from SOUL (e.g. first paragraph or a `SOUL.compact.md` summary) to the heartbeat system prompt.
- **Option B:** Leave as-is and treat the heartbeat as a neutral, concise evaluator; SOUL still governs all conversational replies.

HEARTBEAT.md’s “Silence Rules” section mentions “tone provided by SOUL.compact.md” as guidance for when you *do* surface content; that is aspirational unless Option A is implemented.

---

## 3. Heartbeat dependencies and behaviour when missing

The heartbeat **does not require** every dependency to be present. Missing pieces are reported in `items_checked` and the job still runs (or exits gracefully where required).

| Dependency | Provided in | If missing |
|------------|-------------|------------|
| **goal_store** | main → HeartbeatHandler | `items_checked["goals"]` = “Goal store not available.” |
| **plan_store** | main → HeartbeatHandler | Not used by current handler (goals only). |
| **calendar_client** | main → HeartbeatHandler | “Calendar not available.” |
| **gmail_client** | main → HeartbeatHandler | “Gmail not available.” |
| **automation_store** | main → HeartbeatHandler | “Reminders not available.” |
| **claude_client** | main → HeartbeatHandler | Handler returns HEARTBEAT_OK and does not call the model. |
| **outbound_queue** | main → HeartbeatHandler | If model returns content, delivery falls back to `bot.send_message` (see `send_via_queue_or_bot`). |
| **bot** | main → HeartbeatHandler | Same fallback; if both queue and bot are None, message is not sent (handler still returns “delivered”). |
| **db** (DatabaseManager) | main → ProactiveScheduler | Heartbeat job is **not registered**; scheduler falls back to fixed crons (morning, afternoon, evening, afternoon_check). |
| **heartbeat_handler** | main → ProactiveScheduler | Same: no heartbeat job, fixed crons used. |
| **Primary chat_id / user_id** | `_read_primary_chat_id()` / settings | Job exits without running handler; no log row. |

So: **all dependencies are already wired in main.py**. You only need to “check” in the sense of knowing that missing store or client is reported in context (“X not available”) and that a missing db or handler disables the heartbeat and reverts to the old cron behaviour.

No separate “dependency check” script is required unless you want a startup validation that warns when e.g. `claude_client` or `db` is missing so the heartbeat will be disabled.
