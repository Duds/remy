# Remy Roadmap & Development Plan

**Last Updated:** February 27, 2026 (Phase 7 Step 1 + image support complete)

## 🎯 Philosophy: Simplicity > Complexity

Remy's success relies on being **lean, secure, and continuously useful**. We avoid my-agent's bloat trap by:

- Focusing on **workflow automation** that Dale actually uses daily
- Keeping dependencies minimal and auditable
- Building **one thing at a time** to completion before moving to the next
- Prioritizing **security and transparency** over feature breadth

## 📐 Development Rule: Natural Language First

> **Every slash command MUST have a corresponding tool in `remy/ai/tool_registry.py`.**

When adding a new command:

1. Implement the slash command handler in `bot/handlers.py`
2. Add a tool schema to `TOOL_SCHEMAS` in `tool_registry.py`
3. Add an executor method `_exec_<tool_name>()` to `ToolRegistry`
4. Wire any new dependencies through `main.py` into both `make_handlers` and `ToolRegistry`

This ensures users never need to remember slash commands — Claude detects intent and calls the right tool automatically.

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

- [ ] **Gmail label/folder support** _(feature request)_
  - Current search only queries the default inbox view; emails in Promotions, All Mail,
    or custom labels are invisible to Remy even when unread
  - Extend `GmailClient` to accept a `label` parameter (e.g. `label:all`, `label:promotions`)
  - Natural language: "search all my mail for emails from Kathryn about hockey"
  - Tool schema update: add optional `labels` field to `search_gmail` tool
  - Suggested labels to support: `INBOX`, `ALL_MAIL`, `PROMOTIONS`, `UPDATES`, `FORUMS`

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
  - `/grocery-list` — show items (stored in `data/grocery_list.txt`)
  - `/grocery-list add <items>` — comma-separated or single item
  - `/grocery-list done <item>` — remove completed item
  - `/grocery-list clear` — empty the list

~~### 4.3 Digital Fingerprint Audit~~
~~- [ ] **Privacy audit** — conversation-based via Claude + Board; deferred (no new code needed, just prompting)~~

~~### 4.4 Platform Avoidance~~
~~- [ ] **`/research-alternative <platform>`** — covered by `/research` already; deferred as named command~~

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

### Step 2 — Persistent Job Tracking ⬜ Next Up

Builds on Step 1. Lets the user check status and re-read results after the fact.
See `docs/backlog/US-persistent-job-tracking.md` for full spec.

- [ ] Add `background_jobs` table to SQLite schema (`remy/memory/database.py`)
- [ ] Add `BackgroundJobStore` in `remy/memory/background_jobs.py` — CRUD + status updates
- [ ] Add `/jobs` command → lists recent background jobs with status and truncated result
- [ ] Add `list_background_jobs` tool → natural language: "is my board analysis done yet?"
- [ ] On bot restart: jobs still marked `running` are flipped to `failed` with a note

### Step 3 — Claude Agent SDK Subagents (future, major refactor)

Deferred until Steps 1 & 2 are proven insufficient. Requires replacing `ClaudeClient.stream_with_tools()`.

- [ ] Evaluate `claude-agent-sdk` (`pip install claude-agent-sdk`) as a replacement for the
      manual tool-use loop in `remy/ai/claude_client.py`
- [ ] Define named subagents for different capability profiles:
  - `deep-researcher` — Opus 4.6, web search + file read, runs on background task
  - `board-analyst` — Opus 4.6, read-only, orchestrates the 5 Board agents
  - `quick-assistant` — Sonnet 4.6 (current default), all tools, interactive
- [ ] Subagents can run on **different models** — cheap Haiku for classification,
      Opus for deep analysis — without changing the main conversation model
- **Constraint:** Subagents cannot spawn their own subagents (no `Task` tool in subagent's tools)
- **Dependency:** `claude-agent-sdk` replaces the hand-rolled agentic loop; test thoroughly before merging

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
| **S**    | Fix tool dispatch exception → corrupts history (bug)               | US-tool-dispatch-exception-recovery | ✅ Done                      |
| **S**    | Fix final reply duplication (bug)                                  | US-final-reply-duplication          | ✅ Done                      |
| **S**    | Gmail label/folder search                                          | US-gmail-label-search               | ⬜ P1                        |
| **S**    | Persistent job tracking + `/jobs`                                  | US-persistent-job-tracking          | ⬜ P1                        |
| **S**    | Document image support (PNG/WebP as files)                         | US-document-image-support           | ⬜ P2                        |
| **S**    | Plan tracking (multi-step, with attempts)                          | US-plan-tracking                    | ⬜ P2                        |
| **C**    | Privacy audit (`/privacy-audit`)                                   | US-digital-fingerprint-audit        | ⬜ P2 (prompt-only)          |
| **C**    | Native Telegram Message Threading (Topics)                         | US-telegram-message-threading       | ⬜ P3                        |
| **C**    | Improved persistent memory (semantic dedup, staleness, categories) | US-improved-persistent-memory       | ⬜ P2                        |
| **C**    | Home directory RAG index (~/Projects + ~/Documents)                | US-home-directory-rag               | ⬜ P3                        |
| **C**    | Context-aware reminders (snooze, dedup)                            | US-context-aware-reminders          | ⬜ P3 (deferred)             |
| **C**    | SMS ingestion via Android webhook                                  | US-sms-ingestion                    | ⬜ P3 (new infra)            |
| **C**    | Google Wallet transaction alerts                                   | US-google-wallet-monitoring         | ⬜ P3 (needs SMS first)      |
| **W**    | Claude Agent SDK subagents                                         | US-claude-agent-sdk-subagents       | ⬜ Deferred (major refactor) |
| **W**    | Gmail send                                                         | —                                   | ⬜ Deferred (security)       |
| **W**    | Headless browser automation                                        | —                                   | ❌ Avoid                     |
| **W**    | Knowledge graph + vector store                                     | —                                   | ❌ Avoid                     |

---

## 📍 Next Steps — Prioritised Backlog

### P1 — Immediate (small–medium, clear value)

1. **Fix tool dispatch exception recovery** (`US-tool-dispatch-exception-recovery`) ← **start here**
   - Bug: if any tool call raises (network error, validation), the exception propagates up and
     conversation history is left inconsistent for the next turn
   - Fix: wrap `tool_registry.dispatch()` in per-tool try/except; inject error as tool_result so
     Claude can respond gracefully; `ToolTurnComplete` still fires normally
   - File: `ai/claude_client.py` — ~10 lines; isolated change, no new dependencies

2. **Fix final reply duplication** (`US-final-reply-duplication`)
   - Bug: after multi-tool flows the final message sometimes appears twice or out of order
   - Files: `bot/handlers.py`, `bot/streaming.py` — gate on `in_tool_turn` flag (same infrastructure as suppress story)
   - Implement after #1 (both touch the same event loop)

3. **Gmail label/folder search** (`US-gmail-label-search`)
   - Gap: emails in Promotions, All Mail, and custom labels are invisible to Remy
   - Files: `google/gmail_client.py`, `ai/tool_registry.py`
   - No new dependencies; extends existing Gmail client

4. **Persistent job tracking + `/jobs`** (`US-persistent-job-tracking`)
   - Adds SQLite-backed job registry so background task results survive restarts
   - Files: `memory/database.py` (schema), new `memory/background_jobs.py`, `agents/background.py`, `tool_registry.py`, `bot/handlers.py`
   - Depends on BackgroundTaskRunner ✅ (complete)

### P2 — Next quarter (moderate, high value)

5. **Document image support** (`US-document-image-support`)
   - Gap: images sent as Telegram documents (uncompressed PNG/WebP) are silently ignored
   - Files: `bot/handlers.py` + register in `telegram_bot.py` — mirrors existing `handle_photo`
   - No new dependencies; small targeted change

6. **Plan tracking** (`US-plan-tracking`)
   - New capability: multi-step plans with attempt history, stale-step briefing alerts
   - Files: new `memory/plans.py`, `memory/database.py`, `tool_registry.py`, `scheduler/proactive.py`
   - No new dependencies; well-specced with full schema and tool definitions

7. **Improved persistent memory** (`US-improved-persistent-memory`)
   - Semantic fact deduplication (near-duplicate merging via ANN distance), expanded category
     taxonomy (adds medical, finance, hobby, deadline), `last_referenced_at` staleness tracking,
     `source_session` tracing, and a `get_memory_summary` tool
   - Files: `memory/facts.py`, `memory/database.py`, `memory/embeddings.py`, `memory/injector.py`,
     `ai/tool_registry.py`
   - No new dependencies; builds entirely on existing EmbeddingStore infrastructure

8. **Privacy audit** (`US-digital-fingerprint-audit`)
   - `/privacy-audit` slash command; prompt-only, no new code beyond a handler + system prompt addendum
   - Files: `bot/handlers.py` only — ~20 lines
   - Very low effort for real user value

### P3 — Future (new infrastructure or deferred)

9. **Home directory RAG index** (`US-home-directory-rag`)
   - Background nightly indexer for ~/Projects + ~/Documents; character-chunked embeddings
     stored in new `file_chunks` table; `search_files` + `index_status` tools; `/reindex` command
   - Files: new `memory/file_index.py`, `memory/database.py`, `tool_registry.py`,
     `scheduler/proactive.py`, `bot/handlers.py`, `config.py`
   - No new dependencies; uses existing EmbeddingStore + sqlite-vec/FTS5 fallback
   - Schedule after P2 memory improvements (shares the same embedding infrastructure)

10. **Native Telegram Message Threading** (`US-telegram-message-threading`)
    - Implement support for Telegram Topics to maintain separate conversation contexts.
    - Files: `bot/session.py`, `bot/handlers.py`, `memory/conversations.py`
    - Requires 'Threaded Mode' enabled in @BotFather.

11. **Context-aware reminders** (`US-context-aware-reminders`)
    - Dedup evening check-in against today's conversation; snooze support
    - Only implement if the current evening check-in proves insufficient in practice

12. **SMS ingestion** (`US-sms-ingestion`)
    - Android SMS via SMS Gateway app + Tailscale tunnel + `/webhook/sms` endpoint
    - Prerequisite: Tailscale installed on phone and Mac

13. **Google Wallet alerts** (`US-google-wallet-monitoring`)
    - Tasker profile → `/webhook/notification`; depends on SMS infrastructure

### Deferred (explicit non-starters for now)

9. **Claude Agent SDK subagents** (`US-claude-agent-sdk-subagents`) — major refactor; only revisit if BackgroundTaskRunner + persistent jobs prove insufficient
10. **Gmail send** — security risk; draft creation is sufficient
11. **Research alternative** (`US-research-alternative`) — no code needed; tune `web_research` tool description if quality is poor in practice

---

## 🔗 Related Documentation

- [SOUL.md](./config/SOUL.md) — Remy's system identity and available commands
- [Blog: GoBot vs OpenClaw](https://autonomee.ai/blog/gobot-vs-openclaw/) — architectural lessons
- [my-agent Archive](../my-agent/README.md) — lessons in scope creep

---

## ✅ Remy Tool-Level File Write Access (Added February 26, 2026)

### Context

Phase 2.1 gave Dale a `/write` command to write files via a two-step flow. What was missing was Remy having **direct tool-level access** — i.e. the ability to autonomously read, write, and append files as part of natural language tasks (e.g. updating TODO.md, saving notes, checking off items).

### What Was Added

- [x] **`write_file` tool** — Remy can create or overwrite text files in ~/Projects, ~/Documents, ~/Downloads
  - Always announces the file path and a summary of changes before writing
  - Restricted to approved directories; sensitive paths blocked
- [x] **`append_file` tool** — Remy can append content to existing files without overwriting
  - Ideal for TODO items, log entries, and incremental notes
  - Automatically inserts a newline between existing content and new text
- [x] **`read_file` tool** — already existed; used in combination with write for check-off workflows
  - Pattern: read_file → replace `[ ]` with `[x]` → write_file with full updated content

### Security Constraints (unchanged from Phase 1)

- Writes restricted to `~/Projects/`, `~/Documents/`, `~/Downloads/`
- Sensitive paths (`.env`, `.ssh/`, `.aws/`, `.git/`) explicitly blocked
- Remy announces intent before every write — no silent modifications

---

## 🐛 Bug: Tool Status Text Leaking into Telegram Messages

- [x] **Suppress inter-tool TextChunks from being streamed to user**
  - **Symptom:** Messages like "using list_directory" or "using get_logs" appear in Remy's
    Telegram replies mid-response, as if they are part of the answer.
  - **Root cause:** In `bot/handlers.py`, the tool-aware processing loop passes `TextChunk`
    events directly to `StreamingReply.feed()` regardless of whether they arrive _between_
    tool calls (i.e. before `ToolTurnComplete` has fired). Claude emits brief status-style
    text fragments between tool invocations — these should be logged only, not streamed.
  - **Fix location:** `bot/handlers.py` — tool-aware path (Path A), inside the
    `async for event in claude_client.stream_with_tools(...)` loop.
  - **Fix:** Gate `StreamingReply.feed()` on a flag (`in_tool_turn: bool`). Set it `True`
    on `ToolStatusChunk`, `False` on `ToolTurnComplete`. While `in_tool_turn` is `True`,
    log `TextChunk.text` at DEBUG level but do NOT feed it to the streamer.
  - **`streaming.py` is clean** — no changes needed there.
  - **Test:** Ask Remy to list a directory. Confirm "using list_directory" no longer
    appears in the Telegram reply. Confirm tool results still appear correctly.

## 🏷️ Pending: Gmail Label Creation

- [x] **Add `create_gmail_label` tool**
  - Gap identified: Remy can list and apply labels but cannot create new ones
  - Implement via Gmail API: `POST /gmail/v1/users/me/labels`
  - Support nested labels (e.g. `4-Personal & Family/Hockey`) by setting `name` to the full path string
  - Add tool schema to `TOOL_SCHEMAS` in `tool_registry.py`
  - Natural language: "create a label called Hockey under Personal & Family"
  - Use case: on-the-fly label creation during email triage sessions

---

## 🖼️ Phase 7: Image Consumption ⚠️ Partial

**Solves: "Send Remy a photo and ask questions about it"**

**Status:** Photo messages ✅ (commit 9ef79f7). Document images (sent as files) ⬜ pending.

### Background

Dale can currently send voice messages (transcribed via Whisper) and text. Images sent via Telegram are silently ignored. Claude supports vision natively via the Anthropic messages API (base64-encoded image blocks). This phase wires the two together.

---

### 7.1 Telegram Image Ingestion

- [x] **Handle `photo` messages** — Telegram-compressed JPEG; MIME hardcoded correctly
- [ ] **Handle `document` messages** — uncompressed PNG/WebP/GIF sent as files; currently silently ignored
      → `docs/backlog/US-document-image-support.md`
- [x] **Base64-encode and pass to Claude** (Anthropic image content block)
- [x] **Conversation history** — placeholder stored; images not replayed

---

### 7.2 Natural Language Image Queries ✅

No slash command — just send an image with or without a caption. Works with whiteboard photos,
receipts, screenshots, food photos, etc.

### 7.3–7.4 Security & Implementation ✅

All constraints from the spec implemented: in-memory only, 5MB cap, MIME allowlist, no URL fetching.

---

## 🐛 Minor Bugs (no full US needed)

These are tracked here inline; fix alongside related work rather than as standalone stories.

### One-time automation double-fire on restart (`scheduler/proactive.py:257`)

- **Symptom:** If the bot restarts within the 5-minute APScheduler `misfire_grace_time` window
  after a one-time automation fired, `load_user_automations()` re-registers the job with a
  past `DateTrigger` and APScheduler fires it again immediately.
- **Root cause:** `_run_automation()` deletes the DB row _after_ firing. If the bot restarts
  between fire and delete, the row still exists and the job is re-registered.
- **Fix:** Mark the automation row as `status='fired'` (or delete it) _before_ sending the
  reminder. Then `load_user_automations()` should skip rows with `status='fired'`.
  Requires adding a `status` column to the `automations` table or using `fire_at` comparison.

### Streaming reply overflow split safety (`bot/streaming.py:84`)

- **Symptom:** Very long messages (>4000 chars, no space before limit) fall back to splitting
  at exactly 4000 chars. The `" …"` suffix can push the display string to 4003 chars, still
  within Telegram's 4096 limit but worth monitoring.
- **Fix:** Low priority — add a `len(display) <= 4096` assertion in debug mode.
