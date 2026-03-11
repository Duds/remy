# Remy

A personal AI assistant running as a Telegram bot on a Mac Mini. Remy handles tasks, tracks goals, reads email, manages calendar, remembers context across conversations, and sends scheduled briefings.

Built with Claude (Anthropic), Python, Docker, and Google Workspace APIs.

**Features:** Chat and tools (goals, calendar, Gmail, bookmarks, web search, counters, automations); proactive briefings (morning, afternoon, evening) and evaluative heartbeat; **week-at-a-glance** image (Monday 07:15); **reminder deep links** (`t.me/YourBot?start=reminder_<id>`); **document/photo action buttons** (Summarise, Extract tasks, Save); **bookmarks with tags** (preferences, work, personal); **incoming webhooks** (POST `/incoming` for notify/remind/note); **dashboard** (GET `/dashboard` — Telegram Login Widget, stats); primary chat helper (`/setmychat`, `set_proactive_chat`); streaming overflow safety (splits at 4096 chars).

---

## Requirements

- Docker and Docker Compose
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Anthropic API key
- Python 3.11+ (for local dev / scripts only)

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd remy

# 2. Copy and fill in the config
cp .env.example .env
# Edit .env — at minimum set TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, TELEGRAM_ALLOWED_USERS_RAW

# 3. Build and start
docker compose up --build -d

# 4. Verify
curl http://localhost:8080/health
```

Remy will start polling Telegram within 20–30 seconds.

### Terminal UI

You can chat with Remy from the terminal without Telegram:

```bash
make tui
# or
python -m remy.tui
```

The TUI uses the same `.env` and data directory as the main app. Conversation is persisted in the same session store but with a dedicated TUI session (separate from Telegram). **Ctrl+Q** quits; **Ctrl+C** cancels an in-flight request.

---

## Configuration

All configuration is via `.env`. Copy `.env.example` to get started.

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API key |
| `TELEGRAM_ALLOWED_USERS_RAW` | — | Comma-separated Telegram user IDs allowed to chat (empty = allow all) |
| `MODEL_SIMPLE` | — | Model for quick responses (default: `claude-haiku-4-5-20251001`) |
| `MODEL_COMPLEX` | — | Model for complex tasks (default: `claude-sonnet-4-6`) |
| `ANTHROPIC_MAX_TOKENS` | — | Max tokens per response (default: `4096`) |
| `HEARTBEAT_ENABLED` | — | When `true`, evaluative heartbeat runs (default). When `false`, **deprecated** legacy briefing/check-in crons run; set `true` and use `config/HEARTBEAT.md` instead. |
| `BRIEFING_CRON` | — | Cron schedule for morning briefing (default: `0 7 * * *`) |
| `CHECKIN_CRON` | — | Cron schedule for evening check-in (default: `0 19 * * *`) |
| `AFTERNOON_CHECK_CRON` | — | **Deprecated.** Legacy afternoon check-in (only when `HEARTBEAT_ENABLED=false`; default: `0 17 * * *`). Prefer heartbeat. |
| `SCHEDULER_TIMEZONE` | — | Timezone for scheduler (default: `Australia/Sydney`) |
| `BRIEFING_EMAIL_SCOPE` | — | Morning briefing: `inbox_only` \| `primary_tabs` \| `all_mail`. Heartbeat always uses all mail for unread count (default: `all_mail`) |
| `LOG_LEVEL` | — | Logging level (default: `INFO`) |
| `CHUNK_LOG_ENABLED` | — | When `true`, log every stream event (agents, tools, sends, replies) to JSONL (default: `false`) |
| `CHUNK_LOG_PATH` | — | Path for chunk log file (default: `data/logs/chunk_log.jsonl`) |
| `HF_TOKEN` | — | HuggingFace token — prevents rate limiting on embedding model downloads |
| `HEALTH_API_TOKEN` | — | Bearer token protecting `/logs` and `/telemetry` endpoints |
| `FILE_LINK_BASE_URL` | — | Public base URL for secure file download links (e.g. `https://remy.dalerogers.com.au`); empty = disabled |
| `CLOUDFLARE_TUNNEL_TOKEN` | — | Token for Cloudflare Tunnel (see [Remote Observability](#remote-observability)) |
| `SOUL_MD_PATH` | — | Path to personality file (default: `config/SOUL.md`) |
| `GDRIVE_MOUNT_PATHS` | — | Comma-separated paths to Google Drive mount to index (e.g. `~/Library/CloudStorage/GoogleDrive-<email>`) |
| `RAG_PDF_OCR_ENABLED` | — | Set to `false` to disable OCR for image-only PDFs (default: `true`) |
| `RAG_OCR_LANG` | — | Tesseract language(s), e.g. `eng` or `eng+fra` (default: `eng`) |
| `REMY_WEBHOOK_SECRET` | — | Secret for incoming webhooks (POST `/incoming`). When set, third-party callers must send `X-Webhook-Secret` header. |
| `TELEGRAM_BOT_USERNAME` | — | Bot username (e.g. `RemyBot`) for dashboard Telegram Login Widget. When set, GET `/dashboard` serves the login page. |
| `MOONSHOT_API_KEY` | — | Moonshot AI API key (optional). When set, `/status` and heartbeat show credit balance. |
| `MOONSHOT_BALANCE_WARN_USD` | — | Low-balance threshold in USD (default: `5.0`). When balance is below this, `/status` and heartbeat show a warning. Set to `0` to disable. |

**Heartbeat & SOUL:** Proactive messaging (good morning, reflection, wellbeing) is driven by the **evaluative heartbeat** (`HEARTBEAT_ENABLED=true`, default). The repo ships `config/HEARTBEAT.example.md` as the template; copy it to `config/HEARTBEAT.md` (gitignored) for your private config. Put your thresholds and check-in intent in HEARTBEAT.md. In SOUL, add a **Proactive check-ins** section so the model knows what morning/evening check-ins are for. Legacy fixed-time briefing/check-in crons are **deprecated**; keep `HEARTBEAT_ENABLED=true`. See [docs/SERVER-SETUP.md](docs/SERVER-SETUP.md) for the full server checklist.

**File index (PDF/DOCX):** Remy can index PDF and Word (.docx) files for search. For image-only or scanned PDFs, it uses **Tesseract OCR**. Install Tesseract on the host (e.g. `brew install tesseract` on macOS) so OCR can run; if Tesseract is not installed, text-only PDFs are still indexed.

---

## Google Integration (optional)

Remy can read Gmail, Google Calendar, and Google Contacts. This requires a one-time OAuth setup.

**Setup:**

1. Create a Google Cloud project and enable the Gmail, Calendar, and People APIs
2. Create OAuth 2.0 credentials (Desktop app) and download as `credentials.json`
3. Place `credentials.json` in the project root
4. Run the auth script (must be done on a machine with a browser):

```bash
python3 scripts/setup_google_auth.py
```

This stores tokens in `data/google_token.json`. The Docker container picks them up automatically via the `./data` volume mount.

---

## Docker Services

**Credentials for Docker build and run:**

| Where | Purpose |
|-------|--------|
| **`.env`** | **Required.** Loaded by `docker compose` for both build and run. Must include `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, and (for build) `HF_TOKEN` so the image can download the embedding model. Copy from `.env.example` and fill in. |

So: **build** and **run** both use `.env`; set `HF_TOKEN` there (get a read token at https://huggingface.co/settings/tokens) or leave it empty (build may hit rate limits).

| Service | Port | Description |
|---|---|---|
| `remy` | 8080 | Main bot + health server |
| `ollama` | 11434 | Local LLM fallback |
| `cloudflared` | — | Cloudflare Tunnel (optional — `--profile tunnel`) |

**Health server (port 8080):** `GET /`, `GET /health`, `GET /ready`, `GET /metrics`, `GET /diagnostics`, `GET /logs`, `GET /telemetry`, `GET /files`, `POST /commands/ship-it`, `POST /incoming` (third-party webhooks; requires `REMY_WEBHOOK_SECRET`), `GET /dashboard` (Telegram Login Widget; requires `TELEGRAM_BOT_USERNAME`), `GET /dashboard/auth`, `GET /dashboard/stats`, `POST /webhooks/subscribe`, `GET /webhooks`.

The `remy` image includes Node.js and the **Claude Code CLI** (`@anthropic-ai/claude-code`) so the `run_claude_code` sub-agent tool works in Docker without extra setup.

**Indexing Google Drive in Docker (RAG, including PDF/DOCX and OCR):** Mount your Drive into the container and point Remy at it. In `.env`: set `GDRIVE_MOUNT_PATH` to your **host** path (e.g. `$HOME/Library/CloudStorage/GoogleDrive-<your-email>/My Drive`) and `GDRIVE_MOUNT_PATHS=/home/remy/GoogleDrive` so Remy inside the container indexes the mounted files. The image includes Tesseract for PDF OCR; PDF and DOCX parsing use the same RAG pipeline as local files.

---

## Make Targets

### Development

```bash
make setup          # Create virtualenv and install dev dependencies
make run            # Run bot locally (no Docker)
make test           # Run test suite
make test-cov       # Run tests with coverage report
make lint           # ruff + mypy
```

### Remy stack

```bash
make remy-up           # Start remy + ollama (Docker)
```

### Start at login (macOS)

```bash
make install-launchd    # Install LaunchAgent — remy stack starts at login
make uninstall-launchd  # Remove LaunchAgent
```

### Docker

```bash
make docker-run     # Build and start with Docker Compose (foreground)
make docker-stop    # Stop all containers
make build          # Build Docker image only
make health         # Curl health endpoint (HOST=localhost PORT=8080)
```

### Database

```bash
make db-init        # Initialise SQLite database
make db             # Open Datasette browser at http://localhost:8001
```

### Cloudflare Tunnel

```bash
make tunnel-up      # Start remy + ollama + cloudflared
make tunnel-stop    # Stop all including tunnel
make tunnel-logs    # Follow cloudflared logs
```

---

## Documentation

- **[docs/README.md](docs/README.md)** — Documentation index (architecture, setup, backlog).
- **Current-state:** [Concept Design](docs/architecture/concept-design.md), [HLD](docs/architecture/HLD.md), [SAD](docs/architecture/remy-SAD.md), [SAD design decisions](docs/architecture/remy-sad-v10.md).
- **Setup:** [Server setup](docs/SERVER-SETUP.md), [Agent tooling](docs/agent-tooling-setup.md).

---

## Project Structure

```
remy/
├── remy/
│   ├── ai/             # Claude client, tool schemas, streaming
│   ├── analytics/      # API call logging and telemetry
│   ├── bot/            # Telegram handlers, message pipeline
│   ├── delivery/       # Outbound message queue (crash-safe)
│   ├── diagnostics/    # Health checks, log analysis, self-diagnostics
│   ├── google/         # Gmail, Calendar, Contacts clients
│   ├── hooks/          # Lifecycle hooks (before/after compaction, etc.)
│   ├── memory/         # SQLite stores: goals, plans, facts, conversations
│   ├── scheduler/      # Morning briefing, evening check-in, proactive jobs
│   ├── health.py       # HTTP health server (aiohttp) — /health, /metrics, /logs, /telemetry
│   └── web/            # DuckDuckGo search, price check
├── config/
│   ├── SOUL.md         # Remy's personality and instructions
│   └── SOUL_SYSTEM.md  # System prompt template
├── data/               # SQLite DB, session JSONL files (gitignored)
├── scripts/
│   ├── setup_google_auth.py   # One-time Google OAuth
│   ├── init_db.py             # Initialise database schema
│   └── uat.py                 # User acceptance test runner
├── tests/              # pytest suite
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Remote Observability

Remy exposes a health server on port 8080. With a [Cloudflare Tunnel](docs/backlog/US-cloudflare-tunnel-remote-observability.md) configured, these endpoints are accessible from any network.

**Live instance:** `https://remy.dalerogers.com.au`

### Public endpoints (no auth)

| Endpoint | Description |
|---|---|
| `/health` | `{"status": "ok", "uptime_s": N}` |
| `/ready` | `{"status": "ready"}` or `503` while starting |
| `/metrics` | Prometheus metrics (text format) |

### Protected endpoints (require `Authorization: Bearer <HEALTH_API_TOKEN>`)

| Endpoint | Method | Description |
|---|---|---|
| `/diagnostics` | GET | Full system diagnostics (DB, scheduler, config) |
| `/logs` | GET | Recent log lines. Params: `lines`, `level`, `since` |
| `/telemetry` | GET | API call stats. Param: `window=1h\|6h\|24h\|7d` |
| `/commands/ship-it` | POST | Run SHIP-IT pipeline (fetch, diff, tests). Optional body: `{"dry_run": true}` to skip tests. |

### Remote access via Make

```bash
# Health check
make health HOST=remy.dalerogers.com.au PORT=443

# Telemetry (last 24h)
make telemetry HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN

# Logs (last 200 lines)
make logs HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN LINES=200

# Remote SHIP-IT (run tests and diff over tunnel)
make ship-it-remote HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN
```

Use `make ship-it-remote ... DRY_RUN=1` to run only fetch and diff (no tests).

### Cloudflare Tunnel setup (one-time, on the host machine)

1. Go to [Cloudflare Zero Trust](https://dash.cloudflare.com) → Networks → Tunnels → Create a tunnel
2. Name it `remy`, select Docker, copy the token
3. Add a Public Hostname: subdomain `remy`, service `http://remy:8080`
4. Add to `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=<token from step 2>
   HEALTH_API_TOKEN=$(openssl rand -hex 32)
   ```
5. Start: `make tunnel-up`

See [full setup guide](docs/backlog/US-cloudflare-tunnel-remote-observability.md) for details.

---

## Self-Diagnostics

Send **"Are you there God, it's me, Dale"** (or variations) to trigger a self-diagnostics check. Remy runs `check_status` + `get_logs` and returns the results without calling Claude. See `BUGS.md` Feature 34.

---

## Data

All persistent data lives in `./data/` (mounted into the container):

- `data/remy.db` — SQLite database (users, goals, plans, facts, API call log)
- `data/sessions/` — Conversation transcripts as JSONL files (`user_{id}_{YYYYMMDD}.jsonl`)
- `data/google_token.json` — Google OAuth tokens

The `data/` directory is gitignored. Back it up before wiping containers.

---

## Bug Reports & Fixes

See [BUGS.md](BUGS.md) for the bug log. Recent fixes (March 2026): react_to_message UX, self-diagnostics trigger, orphaned tool_use_id, compaction API, max tool iterations.
