# Remy

A personal AI assistant running as a Telegram bot on a Mac Mini. Remy handles tasks, tracks goals, reads email, manages calendar, remembers context across conversations, and sends scheduled briefings.

Built with Claude (Anthropic), Python, Docker, and Google Workspace APIs.

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
| `BRIEFING_CRON` | — | Cron schedule for morning briefing (default: `0 7 * * *`) |
| `CHECKIN_CRON` | — | Cron schedule for evening check-in (default: `0 19 * * *`) |
| `ALCOHOL_CHECK_CRON` | — | 5pm alcohol/sobriety check-in — mediated, compassionate (default: `0 17 * * *`) |
| `SCHEDULER_TIMEZONE` | — | Timezone for scheduler (default: `Australia/Sydney`) |
| `LOG_LEVEL` | — | Logging level (default: `INFO`) |
| `HF_TOKEN` | — | HuggingFace token — prevents rate limiting on embedding model downloads |
| `HEALTH_API_TOKEN` | — | Bearer token protecting `/logs` and `/telemetry` endpoints |
| `FILE_LINK_BASE_URL` | — | Public base URL for secure file download links (e.g. `https://remy.dalerogers.com.au`); empty = disabled |
| `CLOUDFLARE_TUNNEL_TOKEN` | — | Token for Cloudflare Tunnel (see [Remote Observability](#remote-observability)) |
| `SOUL_MD_PATH` | — | Path to personality file (default: `config/SOUL.md`) |
| `GDRIVE_MOUNT_PATHS` | — | Comma-separated paths to Google Drive mount to index (e.g. `~/Library/CloudStorage/GoogleDrive-<email>`) |
| `RAG_PDF_OCR_ENABLED` | — | Set to `false` to disable OCR for image-only PDFs (default: `true`) |
| `RAG_OCR_LANG` | — | Tesseract language(s), e.g. `eng` or `eng+fra` (default: `eng`) |

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

| Service | Port | Description |
|---|---|---|
| `remy` | 8080 | Main bot + health server |
| `relay` | 8765 (localhost only) | Relay MCP — inter-agent communication (Claude Code) |
| `ollama` | 11434 | Local LLM fallback |
| `cloudflared` | — | Cloudflare Tunnel (optional — `--profile tunnel`) |

---

## Claude Desktop & Cursor (relay MCP)

Remy and cowork (Claude Desktop) share one relay backend so messages and tasks flow both ways. **Use a single relay process** (e.g. `make remy-up` or `make relay-run`) and point both Cursor and Claude Desktop at it.

**Cursor:** The Remy project includes `.cursor/mcp.json` with the relay — it uses the shared HTTP endpoint `http://127.0.0.1:8765/mcp` (no per-session stdio). Restart Cursor after pulling.

**Full setup:** See [docs/relay-setup.md](docs/relay-setup.md) for the shared backend and [docs/agent-tooling-setup.md](docs/agent-tooling-setup.md) for MCP, hooks, and skills.

### Requirements

1. **Relay server running** — Start before using Claude Desktop:
   ```bash
   make remy-up       # Docker (remy + relay + ollama)
   # or
   make relay-run     # Local Python (relay only)
   ```
   Verify: `make relay-check`

2. **uv** (for mcp-proxy) — Claude Desktop uses stdio; the relay uses HTTP. `mcp-proxy` bridges them:
   ```bash
   brew install uv
   # or: pip install uv
   ```

3. **Config** — `~/Library/Application Support/Claude/claude_desktop_config.json` should include:
   ```json
   "relay": {
     "command": "uvx",
     "args": ["mcp-proxy", "--transport", "streamablehttp", "http://127.0.0.1:8765/mcp"]
   }
   ```

4. **Restart Claude Desktop** — Fully quit and reopen after editing config.

### Start at login (macOS)

To have remy + relay + ollama start automatically when you log in:

```bash
make install-launchd   # Install LaunchAgent (runs at login)
make uninstall-launchd # Remove LaunchAgent
```

Requires Docker Desktop (set to "Open at login" in Docker preferences).

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

### Relay (Claude Desktop)

```bash
make remy-up            # Start remy + relay + ollama (Docker)
make relay-run          # Run relay server locally (no Docker)
make relay-check        # Verify relay is reachable on port 8765
make relay-setup-check  # Verify relay + uv (full Claude Desktop setup)
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
make tunnel-up      # Start remy + relay + ollama + cloudflared
make tunnel-stop    # Stop all including tunnel
make tunnel-logs    # Follow cloudflared logs
```

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
│   ├── relay/          # Relay MCP client (inter-agent communication)
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
├── relay_mcp/          # Relay MCP server (inter-agent communication)
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

| Endpoint | Query params | Description |
|---|---|---|
| `/diagnostics` | — | Full system diagnostics (DB, scheduler, config) |
| `/logs` | `lines=100`, `level=ERROR\|WARNING\|INFO`, `since=startup\|1h\|6h\|24h\|all` | Recent log lines |
| `/telemetry` | `window=1h\|6h\|24h\|7d` | API call stats: tokens, latency, model breakdown |

### Remote access via Make

```bash
# Health check
make health HOST=remy.dalerogers.com.au PORT=443

# Telemetry (last 24h)
make telemetry HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN

# Logs (last 200 lines)
make logs HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN LINES=200
```

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
- `data/relay.db` — Relay MCP message queue

The `data/` directory is gitignored. Back it up before wiping containers.

---

## Bug Reports & Fixes

See [BUGS.md](BUGS.md) for the bug log. Recent fixes (March 2026): react_to_message UX, self-diagnostics trigger, orphaned tool_use_id, compaction API, max tool iterations.
