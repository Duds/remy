# Remy Roadmap & Development Plan

**Last Updated:** March 4, 2026 (roadmap cleanup: US moved to docs/backlog, TODO = high-level only)

## 🎯 Philosophy: Simplicity > Complexity

Remy's success relies on being **lean, secure, and continuously useful**. We avoid bloat trap by:

- Focusing on **workflow automation** that Dale actually uses daily
- Keeping dependencies minimal and auditable
- Building **one thing at a time** to completion before moving to the next
- Prioritizing **security and transparency** over feature breadth

## 📐 Development Rule: Natural Language First

> **Every slash command MUST have a corresponding tool in `remy/ai/tools/`.**

When adding a new command:

1. Implement the slash command handler in `remy/bot/handlers.py`
2. Add a tool schema to `TOOL_SCHEMAS` in `remy/ai/tools/schemas.py`
3. Add an executor in `remy/ai/tools/` and register in `ToolRegistry`
4. Wire any new dependencies through `main.py` into both `make_handlers` and `ToolRegistry`

This ensures users never need to remember slash commands — Claude detects intent and calls the right tool automatically.

## 🏗️ Architecture Principle: Remy as UI Layer, Subagents for Heavy Work

**Remy should stay a thin UI and routing layer.** Telegram, relay, simple task routing, and quick replies live in Remy. Heavy or long-running work (Board of Directors, deep research, retrospective, reindex, consolidation) should be delegated to **parallel subagents** with their own models and tools, not run as fat coroutines inside Remy’s process. Today we use `BackgroundTaskRunner` for fire-and-forget; the target is **Phase 7 Step 3** (Claude Agent SDK subagents) so that board, research, etc. are true subagents and Remy just receives results and delivers them. New features that add heavy logic should be designed as subagent tasks, not as more code in the main handler path.

---

## ✅ Current State (What Remy Does Well)

### Foundation

- ✅ **Telegram Integration**: Secure bot interface, no exposed gateway
- ✅ **Board of Directors**: 5-agent multi-perspective analysis (Strategy, Content, Finance, Researcher, Critic)
- ✅ **Memory System**: Facts, goals, and conversation history persistence
- ✅ **Proactive Scheduling**: Morning briefings, check-ins, birthday reminders
- ✅ **Voice Transcription**: Process voice messages via Whisper API
- ✅ **Tool Integration**: Native Anthropic tool use (logs, goals, facts, board, status)
- ✅ **Session Management**: Per-user, stateful conversations
- ✅ **Model Routing**: Smart fallback between Claude and Ollama
- ✅ **Database**: SQLite with semantic search via embeddings

### Security Posture (vs OpenClaw's Problems)

- ✅ **Zero exposed gateway**: No internet-facing port listening
- ✅ **Minimal dependencies**: ~20 packages vs OpenClaw's massive tree
- ✅ **No third-party marketplace**: No untrusted add-ons
- ✅ **Audit trail**: Full conversation logging for transparency

---

## 🏗️ Phase 1: Security & Operational Hardening ✅ Complete

### 1.1 Deprecation of Unsafe Patterns

- [x] **Remove/Restrict Claude Code subprocess access**
  - ClaudeCodeRunner removed entirely from production path
  - File writes require explicit `/write` + confirmation step
  - Allowed directories enforced via path sanitisation

- [x] **Add input validation and injection protection**
  - `input_validator.py`: rate limiting, length limits, shell/prompt injection detection
  - `sanitize_file_path()`: path traversal prevention via `Path.resolve().relative_to()`
  - `sanitize_memory_injection()`: XML tag escaping for user-derived memory content

### 1.2 Transparent Limits & Reliability

- [x] **2-hour action limit enforcement**
  - Hard timeout via `_task_start_times` + `TASK_TIMEOUT_SECONDS`
  - Cleared on success in both Path A (tool use) and Path B (router)

- [x] **Clear model degradation messages**
  - Ollama fallback: inline `⚠️` notice streamed to user
  - Claude unavailable: `health_monitor` alerts every 5 minutes via Telegram

### 1.3 Conversation Privacy

- [x] **Implement conversation cleanup/deletion**
  - `/delete_conversation` command purges JSONL session file
  - Note: automated 30-day cleanup not yet implemented

---

## 🚀 Phase 2: File & Workspace Integration ✅ Complete

**Solves: "Help me with my projects and interests," ADHD body double for decluttering**

### 2.1 Filesystem Access (Secure Read-Write)

- [x] **Safe file reading**
  - `/read <path>` — reads text files from allowed directories
  - Files >50KB: summarised via Claude instead of raw truncation
  - Only allows reads from `~/Projects/`, `~/Documents/`, `~/Downloads/`

- [x] **Safe file writing**
  - `/write <path>` two-step flow: stores path, prompts for content
  - Backup-before-overwrite: `.bak` copy created automatically
  - Pending write intercepted inside session lock (race-safe)

- [x] **File discovery & organisation**
  - `/ls <path>` — list files in a directory
  - `/find <pattern>` — glob search under allowed bases (results validated)
  - `/organize <path>` — Claude-powered organisation suggestions for a directory

### 2.2 Project Context Integration

- [x] **Auto-load project context**
  - `MemoryInjector` reads `README.md` from tracked project directories
  - Injected as `<fact category='project_context'>` in every system prompt
  - Capped at 1500 chars per project, max 3 projects

- [x] **Active project tracking**
  - `/set-project <path>` — store project path as a memory fact
  - `/project-status` — lists projects with file count and last-modified date
  - Morning briefing includes tracked projects

### 2.3 Downloads Automation (ADHD Body Double)

- [x] **Downloads folder watchdog**
  - Morning briefing includes old-file summary from `~/Downloads/`
  - Note: real-time filesystem watching not implemented (out of scope)

- [x] **Decluttering assistant**
  - `/scan-downloads` — rich report: type classification, ages, sizes
  - `/clean <path>` — Claude suggests DELETE / ARCHIVE / KEEP per file

---

## 🌐 Phase 3: Google Workspace Integration ✅ Complete

**Solves: "Read/write to GDocs, Gmail, GCal"**

This is a **cherry-pick from my-agent** (which had partial support) but implemented **cleanly and narrowly**.

### 3.1 Google Calendar Integration

- [x] **OAuth2 setup and token management**
  - Token stored at `data/google_token.json` (never in logs or `.env`)
  - Auto-refresh via google-auth library; persisted on rotation
  - `scripts/setup_google_auth.py` for one-time interactive consent flow
  - Graceful degradation: commands return helpful setup instructions if not configured

- [x] **Read calendar events**
  - `/calendar [days=7]` — show events for next N days, grouped by date
  - `/calendar-today` — shorthand for `/calendar 1`
  - Morning briefing includes today's events (if Google configured)

- [x] **Create calendar events**
  - `/schedule <title> <YYYY-MM-DD> <HH:MM>` — 1-hour event creation
  - Returns Google Calendar link for created event
  - Note: `/block-focus` deferred — low priority vs complexity

### 3.2 Gmail Integration (Lightweight)

- [x] **Read unread emails**
  - `/gmail-unread [limit=5]` — metadata-only fetch (fast), shows subject/sender/snippet
  - `/gmail-unread-summary` — total unread count + top senders

- [x] **Newsletter/Spam classification with archive confirmation**
  - `/gmail-classify` — keyword heuristic finds promotional emails
  - Two-step archive flow: bot asks "Reply yes to archive N emails"
  - User reply intercepted in message handler (same pattern as `/write`)
  - Note: `/email` send deferred — security risk for now

- [x] **Gmail draft creation**
  - `create_email_draft` tool — saves a composed email to Drafts (does not send)
  - Natural language: "draft an email to Kathryn about the hockey schedule"
  - User reviews and sends manually from Gmail — no send capability exposed to Remy

- [x] **Gmail label/folder support** (`US-gmail-label-search`) — done
  - `search_gmail` tool accepts optional `labels` parameter (INBOX, ALL_MAIL, PROMOTIONS, etc.)
  - Natural language: "search all my mail for emails from Kathryn about hockey"

### 3.3 Google Docs Integration (Minimal)

- [x] **Read shared documents**
  - `/gdoc <doc-id-or-url>` — accepts full URL or bare document ID
  - Large docs (>50KB) summarised via Claude automatically

- [x] **Write to shared documents**
  - `/gdoc-append <doc-id-or-url> <text>` — appends at end of document body

### 3.4 Google Contacts Integration

- [x] **Browse & search contacts**
  - `/contacts` — list all contacts (name, email, phone)
  - `/contacts <query>` — search by name or email via People API

- [x] **Contact details**
  - `/contacts-details <name>` — full card: email, phone, org, birthday, bio/notes

- [x] **Birthday reminders**
  - `/contacts-birthday [days=14]` — upcoming birthdays within N days
  - Morning briefing includes birthdays in the next 7 days automatically

- [x] **Contact notes**
  - `/contacts-note <name> <note>` — search for contact, update biography field

- [x] **Sparse contact pruning**
  - `/contacts-prune` — lists contacts missing both email AND phone (review for deletion)
  - Graceful degradation: all commands return setup instructions if not configured

---

## 🔍 Phase 4: Internet Navigation & Web Tasks ✅ Complete

**Solves: "Clean digital fingerprint," "Help me shop," "Research," "Internet native"**

### 4.1 Web Search & Browsing

- [x] **Web search via DuckDuckGo** (no API key needed)
  - `/search <query>` — top 5 results with title, URL, snippet
  - `/research <topic>` — search + Claude synthesis into a structured summary
  - Graceful degradation: helpful error if duckduckgo-search unavailable

- [x] **Bookmark & reference management**
  - `/save-url <url> [note]` — saved as memory fact (category: bookmark)
  - `/bookmarks [filter]` — list bookmarks, optional text filter, capped at 20

### 4.2 Shopping Assistance

- [x] **Price comparison**
  - `/price-check <item>` — DuckDuckGo search + Claude extraction of prices
  - Falls back to raw results if Claude unavailable

- [x] **Grocery shopping helper**
  - **Storage**: KnowledgeStore only (`entity_type='shopping_item'`). File deprecated; config `grocery_list_file` kept only for `migrate_legacy_data()`.
  - **Unified**: One implementation `grocery_list_impl(store, user_id, action, items_raw)` in `ai/tools/automations.py`; both the `grocery_list` tool and `/grocery-list` command use it. List shows IDs; remove by name or ID.
  - `/grocery-list` — show list (with IDs)
  - `/grocery-list add <items>` — comma- or space-separated
  - `/grocery-list done <item|id>` — remove by name or ID (e.g. `done 43`)
  - `/grocery-list clear` — empty the list
  - In chat, `grocery_list` tool: same actions (show/add/remove/clear).

---

## 🤝 Phase 5: Smart Behavioral Automation ✅ Complete

**Cherry-pick from my-agent's "capability.automation_engine"** but **scoped and simple**.

### 5.1 Task Automation Framework

- [x] **Cron-like scheduled tasks**
  - `/schedule-daily [HH:MM] <task>` — daily reminder (default 09:00)
  - `/schedule-weekly [day] [HH:MM] <task>` — weekly reminder (default Mon 09:00)
  - `/list-automations` — show scheduled reminders with IDs and last-run times
  - `/unschedule <id>` — remove a reminder by ID
  - Backend: APScheduler cron jobs; persisted in `automations` DB table; reloaded on restart
  - New file: `remy/memory/automations.py` — AutomationStore CRUD

- [x] **Conditional task triggering**
  - Shopping keywords → grocery list injected into Claude's system prompt context
  - Deadline keywords → calendar event offer injected into system prompt context
  - Handled in `_process_text_input` before AI call (lightweight keyword heuristics)

### 5.2 ADHD Body Double Features

- [x] **Time-aware focus suggestions**
  - Afternoon check-in job at 14:00 (new `_afternoon_focus` job in ProactiveScheduler)
  - Sends top active goal + remaining calendar events + "3 focused hours" encouragement
  - Configurable via `AFTERNOON_CRON` env var

- [x] **Breaking down big tasks**
  - `/breakdown <task>` — Claude decomposes task into 5 actionable ≤30-min steps
  - Memory-injected: uses user's goals/facts for personalised advice
  - ADHD-friendly phrasing ("you've got this")

- [ ] **Context-aware gentle reminders** — deferred (evening check-in already covers goal staleness)

### 5.3 Memory Management ✅ Complete (added post-phase)

- [x] **Update / delete stored facts**
  - `FactStore.update()`, `FactStore.delete()`, `FactStore.add()` — full CRUD on `facts` table
  - `manage_memory` tool in `tool_registry.py` — Claude calls `get_facts` to find IDs, then add/update/delete
  - Natural language: "change my favourite colour to green", "forget that I live in Sydney"
- [x] **Update / delete / complete goals**
  - `GoalStore.update()`, `GoalStore.delete()`, `GoalStore.add()` — full CRUD on `goals` table
  - `manage_goal` tool — actions: add / update / complete / abandon / delete
  - Natural language: "I finished that goal", "rename the remy goal to X", "add a goal: learn Spanish"

---

## 📊 Phase 6: Analytics & Better Insights ✅ Complete

**Increases long-term value without adding complexity.**

- [x] **Conversation analytics**
  - `/stats [period]` — message counts, active days, model breakdown (7d/30d/90d/all)
  - `get_stats` tool — natural language: "how much have I used remy this month?"
  - New file: `remy/analytics/analyzer.py` — `ConversationAnalyzer` class

- [x] **Goal tracking dashboard**
  - `/goal-status` — active goals with creation age + last-update staleness indicator (⚠️ = 3+ days)
  - Shows completed goals from the last 30 days
  - `get_goal_status` tool — natural language: "what's my goal progress?"

- [x] **Monthly retrospective**
  - `/retrospective` — on-demand Claude-generated monthly summary (wins, in-progress, next priorities)
  - `generate_retrospective` tool — natural language: "give me a retrospective"
  - Automatic: fires last day of each month at 18:00 via `ProactiveScheduler`

---

## 🤖 Phase 7: Background Agents (Non-Blocking Long Tasks)

**Problem:** Slow tasks (Board of Directors ~45s, deep research, retrospective) currently hold the
per-user session lock for their full duration. The user is blocked until they complete.

**Key insight:** `ProactiveScheduler` already solves this — it runs async AI work and calls
`_send()` directly without ever holding a session lock. Background agents follow the same model.

### Step 1 — Fire-and-Forget with Telegram Callback ✅ Complete

The minimal, idiomatic change. Fits entirely within the existing asyncio architecture.

- [x] Add `BackgroundTaskRunner` in `remy/agents/background.py`
  - Wraps `BoardOrchestrator`, `ConversationAnalyzer.generate_retrospective`, etc.
  - Accepts a `chat_id` + `bot` reference; calls `bot.send_message()` on completion
  - Catches and logs exceptions; never leaks into the main event loop
- [x] Modify `_process_text_input` in `handlers.py` to detect "detachable" requests
  - Heuristic: user explicitly asks for `/board`, `/retrospective`, or sends a message whose
    intent is classified as "deep analysis" (existing `classifier.py` already has intent detection)
  - On match: acquire lock briefly → send "Started — I'll message you when done 🔄" → release
    lock → `asyncio.create_task(_run_detached(...))`
- [x] The detached task reads `primary_chat_id` (same as proactive scheduler) for the callback send
- **No new dependencies.** Uses `asyncio.create_task()` already used for fact/goal extraction.

### Step 2 — Persistent Job Tracking ✅ Complete

Builds on Step 1. Lets the user check status and re-read results after the fact.
See `docs/backlog/US-persistent-job-tracking.md` for full spec.

- [x] Add `background_jobs` table to SQLite schema (`remy/memory/database.py`)
- [x] Add `BackgroundJobStore` in `remy/memory/background_jobs.py` — CRUD + status updates
- [x] Add `/jobs` command → lists recent background jobs with status and truncated result
- [x] Add `list_background_jobs` tool → natural language: "is my board analysis done yet?"
- [x] On bot restart: jobs still marked `running` are flipped to `failed` with a note

### Step 3 — Claude Agent SDK Subagents (target architecture)

**Goal:** Remy as UI layer only; board, research, retrospective, etc. run as parallel subagents that report back. Deferred so far; revisit when prioritising "Remy thin, subagents for heavy work." Requires replacing or wrapping `ClaudeClient.stream_with_tools()`.

- [ ] Evaluate `claude-agent-sdk` (`pip install claude-agent-sdk`) as a replacement for the
      manual tool-use loop in `remy/ai/claude_client.py`
- [ ] Define named subagents for different capability profiles:
  - `deep-researcher` — Sonnet 4.6, web search + file read, runs on background task
  - `board-analyst` — Sonnet 4.6, read-only, orchestrates the 5 Board agents
  - `quick-assistant` — Sonnet 4.6 (current default), all tools, interactive
  - `chief-financial-officer` — Sonnet 4.6, finance-focused: budgeting, expense tracking & categorisation, invoice and receipt reconciliation, monthly cash‑flow forecasting, cost‑savings analysis, and billing/reminder automation. Read-only by default; any write or transaction actions require explicit user confirmation and secure token gating. Produces spreadsheet-friendly reports and short actionable recommendations for reducing recurring costs.
  - `code-reviewer` — Sonnet 4.6, optimized for reading and explaining code, with repo access and linting tools; handy for PR reviews and coding assistance.
  - `meeting-summarizer` — focused on rapidly condensing transcripts or notes into action items and highlights.
  - `wellness-coach` — provides brief motivational prompts and tracks simple health/habit metrics.
  - `project-manager` — keeps an eye on tasks, deadlines, and reminds you of upcoming milestones.
  - (add other specialised agents as new needs arise)
- [ ] Subagents can run on **different models** — cheap Haiku for classification,
      Opus for deep analysis — without changing the main conversation model
- **Constraint:** Subagents cannot spawn their own subagents (no `Task` tool in subagent's tools)
- **Dependency:** `claude-agent-sdk` replaces the hand-rolled agentic loop; test thoroughly before merging
- **Next:** Concrete evaluation and first-subagent steps are in [docs/backlog/US-subagents-next-plan.md](docs/backlog/US-subagents-next-plan.md).

---

## 📱 Phase 8: Telegram + Claude UX Enhancements

**Solves: "One-tap actions instead of typing," "Safer destructive flows," "Richer proactive reminders"**

Combines Telegram Bot API (inline keyboards, callbacks, chat actions) with Claude's reasoning and tool use. Prioritised for a single-user personal assistant. See `docs/backlog/US-confirmation-flows.md` through `US-send-to-cowork.md` for specs; full ideation in plan.

### Tier 1 — Do first (highest daily impact)

- [x] **Confirmation flows** (`US-confirmation-flows`) — [Confirm] [Cancel] inline buttons for destructive actions (archive emails, delete automation). Replaces "Reply yes" text flow.
- [x] **Smart reply buttons** (`US-smart-reply-buttons`) — Contextual [Add to calendar], [Forward to cowork], [Break down] on substantive replies. Requires `CallbackQueryHandler` + pipeline `suggested_actions`.
- [x] **Snooze/Complete on reminders** (`US-snooze-complete-reminders`) — [Snooze 5m] [Snooze 15m] [Done] on proactive reminder messages.
- [x] **Emoji reactions as task feedback** (`US-emoji-reactions-feedback`) — Automatic 🤩 on user's message when allowlisted tools complete. Builds on `US-emoji-reaction-handling` (done).
- [x] **One-tap automation templates** (`US-one-tap-automations`) — `/list_automations` as inline buttons; tap to run on-demand.

### Tier 2 — High value, moderate effort

- [x] **Conversational briefing via Remy** (`US-conversational-briefing-via-remy`) — Morning briefing composed by Remy from structured data; Australian dates; natural voice. See `docs/backlog/US-conversational-briefing-via-remy.md`.
- [x] **Calendar quick add** (`US-calendar-quick-add`) — [Add to calendar] on event mentions in briefings/summaries.
- [x] **Send to cowork** (`US-send-to-cowork`) — [Send to cowork] on notes/summaries for one-tap relay handoff.
- [x] **Chat actions for long tasks** — `upload_document` / `upload_photo` when research/board runs (instead of only `typing`).
- [x] **Run again / different params** — [Run again] [New topic] on tool-heavy flows (research, board, web_search).
- [ ] **Document/photo action buttons** — [Summarise] [Extract tasks] [Save] on attachments.

### Tier 3 — Nice to have

- [ ] **Deep links for reminders** — `t.me/RemyBot?start=reminder_<id>` for notification tap → context.
- [ ] **Bookmarks with tag buttons** — [Preferences] [Work] [Personal] when saving facts.
- [ ] **Rich media summaries** — Week-at-a-glance image + caption for briefings.
- [ ] **Web login for dashboards** — Telegram Login Widget for stats/costs in browser.
- [ ] **Webhooks for third-party** — CI, Zapier → Remy notification + actions.

### Lower priority (single user)

- Message threading (done), inline quick actions from any chat, workflow checklist, location reminders, polls, dice, voice replies, price alerts, multi-language, Mini App settings — see plan for rationale.

---

## 🗑️ Features to Deliberately Avoid (Lessons from my-agent)

These were in my-agent and caused bloat. **Do not implement.**

- ❌ **Distributed mesh networking** — complexity for marginal benefit
- ❌ **Full automation marketplace** — breeds security issues (like ClawHub)
- ❌ **Real-time collaborative editing** — stateful and complex
- ❌ **Local LLM fine-tuning** — maintenance burden
- ❌ **Headless browser for web automation** — fragile, maintenance-heavy
- ❌ **Knowledge graph with vector store** — can use vector embeddings we have; don't build new DB
- ❌ **Inspiration sidebar widget** — nice-to-have, deferred until core is rock-solid
- ❌ **Privacy vault with encryption** — use system keychain instead; don't reinvent crypto
- ❌ **Approval/HITL workflows** — simple confirmations in Telegram work fine

**Why?** Each adds complexity without proportional value. Focus on **workflows Dale uses daily**.

---

## 🎯 Success Metrics

1. **Day-to-day utility**: Minimum 5 distinct use cases Dale uses per week
2. **Security**: Zero known vulnerabilities, full audit trail
3. **Reliability**: 99.5% uptime, <2 sec response time for common commands
4. **Maintainability**: <150 lines of new code per week over 6 months
5. **Understandability**: Any competent engineer can read full codebase in <4 hours

---

## 📋 Prioritization (MoSCoW)

**M = Must Have | S = Should Have | C = Could Have | W = Won't Have**

| Priority | Feature                                                            | Backlog                             | Status                       |
| -------- | ------------------------------------------------------------------ | ----------------------------------- | ---------------------------- |
| **M**    | Safe file read/write                                               | —                                   | ✅ Done                      |
| **M**    | Input validation & injection protection                            | —                                   | ✅ Done                      |
| **M**    | Google Calendar read/write                                         | —                                   | ✅ Done                      |
| **M**    | Gmail integration (unread, classify, draft)                        | —                                   | ✅ Done                      |
| **M**    | Google Docs & Contacts                                             | —                                   | ✅ Done                      |
| **M**    | Web search & research                                              | —                                   | ✅ Done                      |
| **M**    | Scheduled automation (cron reminders)                              | —                                   | ✅ Done                      |
| **M**    | Analytics, goal dashboard, retrospective                           | —                                   | ✅ Done                      |
| **M**    | Image/vision support (photos)                                      | —                                   | ✅ Done                      |
| **M**    | BackgroundTaskRunner (fire-and-forget)                             | US-background-task-runner           | ✅ Done                      |
| **S**    | Persistent job tracking + `/jobs`                                  | US-persistent-job-tracking          | ✅ Done                      |
| **S**    | Gmail label/folder search                                          | US-gmail-label-search               | ✅ Done                      |
| **S**    | Gmail create label (tool + slash command)                          | US-gmail-create-label              | ✅ Done                      |
| **S**    | Analytics: per-call token capture                                  | US-analytics-token-capture          | ✅ Done                      |
| **S**    | Analytics: API call log + latency                                  | US-analytics-call-log               | ✅ Done                      |
| **S**    | Analytics: `/costs` command                                        | US-analytics-costs-command          | ✅ Done                      |
| **S**    | Document image support (PNG/WebP as files)                         | US-document-image-support           | ✅ Done                      |
| **S**    | Plan tracking (multi-step, with attempts)                          | US-plan-tracking                    | ✅ Done                      |
| **C**    | Privacy audit (`/privacy-audit`)                                   | US-digital-fingerprint-audit        | ✅ Done                      |
| **C**    | Native Telegram Message Threading (Topics)                         | US-telegram-message-threading       | ✅ Done                      |
| **C**    | Improved persistent memory (semantic dedup, staleness, categories) | US-improved-persistent-memory       | ✅ Done                      |
| **C**    | Home directory RAG index (~/Projects + ~/Documents)                | US-home-directory-rag               | ✅ Done                      |
| **C**    | Context-aware reminders (snooze, dedup)                            | US-context-aware-reminders          | ⬜ P3 (deferred)             |
| **C**    | SMS ingestion via Android webhook                                  | US-sms-ingestion                    | ⬜ P3 (new infra)            |
| **C**    | Google Wallet transaction alerts                                   | US-google-wallet-monitoring         | ⬜ P3 (needs SMS first)      |
| **C**    | Funny/nonsensical "working" messages for Telegram                  | US-working-messages                 | ✅ Done                      |
| **C**    | Telegram Markdown header/formatting fixes                          | US-telegram-markdown-fix            | ✅ Done                      |
| **S**    | Telegram catch-all error handler                                   | US-telegram-error-handler           | ✅ Done                      |
| **S**    | Multi-Model Orchestration (Mistral, Moonshot)                      | US-model-orchestration              | ✅ Done                      |
| **S**    | Cloudflare Tunnel — remote log/telemetry access                    | US-cloudflare-tunnel-remote-observability | ✅ Done — https://remy.dalerogers.com.au |
| **S**    | Claude Agent SDK subagents                                         | US-claude-agent-sdk-subagents       | ⬜ Deferred (major refactor) |
| **S**    | Gmail send                                                         | —                                   | ⬜ Deferred (security)       |
| **S**    | Confirmation flows (inline Confirm/Cancel)                          | US-confirmation-flows               | ✅ Done                      |
| **S**    | Smart reply buttons (Add to calendar, Forward to cowork)             | US-smart-reply-buttons              | ✅ Done                      |
| **S**    | Snooze/Complete on proactive reminders                              | US-snooze-complete-reminders        | ✅ Done                      |
| **C**    | Emoji reactions as task completion feedback                         | US-emoji-reactions-feedback         | ✅ Done                      |
| **C**    | One-tap automation templates                                        | US-one-tap-automations              | ✅ Done                      |
| **C**    | Conversational briefing via Remy (morning)                           | US-conversational-briefing-via-remy | ✅ Done                      |
| **C**    | Calendar quick add from inline suggestions                           | US-calendar-quick-add               | ✅ Done                      |
| **C**    | Send to cowork with one tap                                          | US-send-to-cowork                   | ✅ Done                      |
| **S**    | Two-way Claude Desktop ↔ Remy relay (tools, /relay, briefing hook)   | US-claude-desktop-relay             | ✅ Done                      |
| **S**    | Fix save_bookmark KnowledgeStore AttributeError                     | US-fix-save-bookmark-knowledge-store | ✅ Done                      |
| **S**    | Cap tool iterations per turn (reduce latency)                         | US-cap-tool-iterations-per-turn    | ✅ Done                      |
| **S**    | Step-limit message inline buttons (Continue / Break down / Stop)      | US-step-limit-buttons              | ✅ Done                      |
| **S**    | Web search optimisation (per-turn limit, caching)                    | US-web-search-optimisation         | ✅ Done                      |
| **C**    | Aggressive session compaction (earlier trigger, smaller window)      | US-aggressive-session-compaction  | ✅ Done                      |
| **C**    | Anthropic overload detection and fallback                            | US-anthropic-overload-fallback    | ✅ Done                      |
| **W**    | Headless browser automation                                        | —                                   | ❌ Avoid                     |
| **W**    | Knowledge graph + vector store                                     | —                                   | ❌ Avoid                     |

---

## 📍 Next steps (roadmap)

Prioritised work lives in **`docs/backlog/`** as PBI user stories (`US-*.md`). Use the **next-PBI** skill or scan backlog by status for what to pick up next. Current focus areas:

- **Phase 8 (Telegram UX):** Remaining Tier 2/3 items (e.g. document/photo action buttons, deep links). See phase section above and backlog.
- **P3 / deferred:** Context-aware reminders, SMS ingestion, Google Wallet — see `US-context-aware-reminders`, `US-sms-ingestion`, `US-google-wallet-monitoring`. Deferred: Claude Agent SDK subagents, Gmail send.

---

## 🔧 Recent Fixes (March 2026)

See [BUGS.md](./BUGS.md) for full details. Key fixes:

- **Bug 35:** `react_to_message` — delete status message when reaction is sole response (no extra ✅ text)
- **Bug 34:** Self-diagnostics trigger — "Are you there God, it's me, Dale" runs check_status + get_logs
- **Bug 36:** Orphaned tool_use_id — message sanitizer prevents 400 errors from trimmed history
- **Bug 37:** Compaction — `complete()` now receives `[{"role":"user","content":...}]` not raw string
- **Bug 38:** Max tool iterations — limit 8→12, truncation message when limit hit

---

## 🔗 Related Documentation

- [SOUL.md](./config/SOUL.md) — Remy's system identity and available commands
- [Blog: GoBot vs OpenClaw](https://autonomee.ai/blog/gobot-vs-openclaw/) — architectural lessons
- [my-agent Archive](../my-agent/README.md) — lessons in scope creep

---

## 📍 Where to find detail

**User stories and PBIs** live in `docs/backlog/` as `US-*.md` files. Use the **next-PBI** skill (or scan backlog by status) for prioritised work. The MoSCoW table and phase sections above reference backlog IDs; implementation notes and acceptance criteria are in the backlog. For tool-level file write, Gmail create label, image consumption, and memory persistence details, see Phase 2–5 and `US-gmail-create-label`, `US-document-image-support`, `US-proactive-memory-storage`, and related US files.
