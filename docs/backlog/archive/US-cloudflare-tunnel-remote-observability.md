# User Story: Cloudflare Tunnel — Remote Observability

**Status:** ✅ Done

## Summary

As Dale, I want to check remy's live logs and telemetry from any network so that I can monitor and diagnose the production server on the Mac Mini without needing to be on the home network or SSH in.

---

## Background

Remy runs as a Docker Compose stack on a Mac Mini M2 at home. The health server (`/health`, `/ready`, `/metrics`, `/diagnostics`, `/logs`, `/telemetry`) listens on port 8080. Port 8080 is exposed to the local network but not to the internet.

When working remotely (work network, mobile hotspot, etc.) there is currently no way to check:
- Whether remy is running
- Recent log output (errors, warnings, unusual behaviour)
- API call telemetry (token usage, cost, model routing, latency)

The `/logs` and `/telemetry` endpoints were added in March 2026 (see `remy/health.py`). The remaining gap is a secure transport layer to reach them from any network.

**Cloudflare Tunnel** (`cloudflared`) is the right solution:
- No port forwarding or static IP required
- Outbound-only connection from Mac Mini to Cloudflare's edge
- HTTPS handled automatically at the edge
- Free tier; requires a Cloudflare account and a domain on Cloudflare DNS
- Bearer token (`HEALTH_API_TOKEN`) protects `/logs` and `/telemetry`

**Code changes already done (2026-03-02):**
- [x] `docker-compose.yml` — `cloudflared` service added under `profiles: [tunnel]`
- [x] `.env.example` — `CLOUDFLARE_TUNNEL_TOKEN=` added with setup comments
- [x] `Makefile` — `tunnel-up`, `tunnel-stop`, `tunnel-logs`, `telemetry`, `logs` targets added

**Public URL:** `https://remy.dalerogers.com.au`

**Completed:** Tunnel live as of 2026-03-03. `/health` returns 200 from any network. `/telemetry` and `/logs` return 401 without Bearer token.

---

## Acceptance Criteria

1. **Tunnel is running.** `docker compose --profile tunnel ps` shows `cloudflared` as `Up` on the Mac Mini.

2. **Public hostname resolves.** `curl https://remy.<domain>/health` returns `{"status": "ok", "uptime_s": N}` from any network.

3. **`/logs` and `/telemetry` are protected.** A request without `Authorization: Bearer <HEALTH_API_TOKEN>` returns `401`. A request with the correct token returns `200`.

4. **`make telemetry` works from the dev machine.**
   ```
   make telemetry HOST=remy.<domain> TOKEN=<HEALTH_API_TOKEN>
   ```
   Returns a formatted JSON block with `total_calls`, `tokens`, `latency_ms`, `by_model`, `recent_calls`.

5. **`make logs` works from the dev machine.**
   ```
   make logs HOST=remy.<domain> TOKEN=<HEALTH_API_TOKEN> LINES=50
   ```
   Returns recent log lines as plain text.

6. **Normal `docker compose up` is unaffected.** Without `--profile tunnel`, remy starts normally with no cloudflared container.

7. **Tunnel survives remy restarts.** Because `cloudflared` depends on the `remy` healthcheck, the tunnel reconnects automatically after remy restarts.

---

## Implementation

### One-time setup on the Mac Mini

**Step 1 — Cloudflare account and domain**

A domain must be active on Cloudflare DNS. If you have one (e.g. `dale.id.au`), skip to Step 2.

**Step 2 — Create the tunnel**

In the Cloudflare dashboard:
1. Go to **Zero Trust → Networks → Tunnels → Create a tunnel**
2. Name it `remy`
3. Select **Docker** as the connector type
4. Copy the token from the `docker run` command shown (long base64 string)

**Step 3 — Configure public hostname**

Still in the tunnel config:
1. Click **Next** to reach the Public Hostname tab
2. Add a hostname:
   - **Subdomain:** `remy`
   - **Domain:** `<your-domain>` (e.g. `dale.id.au`)
   - **Service:** `http://remy:8080`
3. Save

**Step 4 — Set environment variables on Mac Mini**

Add to `.env` (the file used by `docker compose`):
```
CLOUDFLARE_TUNNEL_TOKEN=<token from Step 2>
HEALTH_API_TOKEN=<strong random string — generate with: openssl rand -hex 32>
```

**Step 5 — Start the tunnel**

```bash
cd ~/Projects/active/agents/remy
make tunnel-up
# or: docker compose --profile tunnel up -d
```

**Step 6 — Verify**

```bash
# From anywhere:
curl https://remy.<domain>/health

# Telemetry (from dev machine):
make telemetry HOST=remy.<domain> TOKEN=<HEALTH_API_TOKEN>

# Logs:
make logs HOST=remy.<domain> TOKEN=<HEALTH_API_TOKEN> LINES=100
```

---

## Live Endpoints — https://remy.dalerogers.com.au

### Public (no auth)

| Endpoint | Method | Response |
|---|---|---|
| `/` | GET | `{"service": "remy", "version": "1.0"}` |
| `/health` | GET | `{"status": "ok", "uptime_s": N}` |
| `/ready` | GET | `{"status": "ready"}` or `503 {"status": "starting"}` |
| `/metrics` | GET | Prometheus metrics (text format) |

### Protected — requires `Authorization: Bearer <HEALTH_API_TOKEN>`

| Endpoint | Method | Query params | Response |
|---|---|---|---|
| `/diagnostics` | GET | — | Full system diagnostics JSON (DB, scheduler, embeddings, config) |
| `/logs` | GET | `lines=100` (max 500), `level=ERROR\|WARNING\|INFO`, `since=startup\|1h\|6h\|24h\|all` | Recent log lines (plain text) |
| `/telemetry` | GET | `window=1h\|6h\|24h\|7d` (default `24h`) | API call stats JSON: total calls, tokens, latency, model breakdown |

### Quick-reference curl commands

```bash
# Health (public)
curl https://remy.dalerogers.com.au/health

# Telemetry — last 24h
curl -H "Authorization: Bearer $HEALTH_API_TOKEN" https://remy.dalerogers.com.au/telemetry | python3 -m json.tool

# Telemetry — last 7 days
curl -H "Authorization: Bearer $HEALTH_API_TOKEN" "https://remy.dalerogers.com.au/telemetry?window=7d" | python3 -m json.tool

# Logs — last 100 lines from current session
curl -H "Authorization: Bearer $HEALTH_API_TOKEN" https://remy.dalerogers.com.au/logs

# Logs — last 200 error/warning lines
curl -H "Authorization: Bearer $HEALTH_API_TOKEN" "https://remy.dalerogers.com.au/logs?lines=200&level=WARNING"

# Logs — all logs from last 6 hours
curl -H "Authorization: Bearer $HEALTH_API_TOKEN" "https://remy.dalerogers.com.au/logs?since=6h&lines=500"

# Diagnostics
curl -H "Authorization: Bearer $HEALTH_API_TOKEN" https://remy.dalerogers.com.au/diagnostics | python3 -m json.tool
```

### Makefile shortcuts

```bash
# Telemetry (24h default)
make telemetry HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN

# Logs (100 lines default)
make logs HOST=remy.dalerogers.com.au TOKEN=$HEALTH_API_TOKEN LINES=200
```

---

### Files changed (already done)

- `docker-compose.yml` — `cloudflared` service under `profiles: [tunnel]`
- `.env.example` — `CLOUDFLARE_TUNNEL_TOKEN=` added
- `Makefile` — `tunnel-up`, `tunnel-stop`, `tunnel-logs`, `telemetry`, `logs`

### Notes

- The `cloudflared` service uses `depends_on: remy: condition: service_healthy` — it will not start until remy's `/health` endpoint returns 200. This means remy must be fully started before the tunnel opens.
- If `CLOUDFLARE_TUNNEL_TOKEN` is empty or unset, the cloudflared container will start but immediately exit. This is harmless if you haven't set up the tunnel yet; just don't include `--profile tunnel` until the token is configured.
- To rotate `HEALTH_API_TOKEN`, update `.env` and restart: `docker compose --profile tunnel restart`.
- Do not expose port 8080 directly to the internet via router port forwarding — the Cloudflare Tunnel is the only intended path.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `curl https://remy.<domain>/health` (no auth) | `200 {"status": "ok"}` |
| `curl https://remy.<domain>/telemetry` (no token) | `401 Unauthorized` |
| `curl https://remy.<domain>/telemetry` (correct Bearer token) | `200` JSON with aggregate stats |
| `curl https://remy.<domain>/logs?lines=50` (correct Bearer token) | `200` plain text log lines |
| `make tunnel-up` with `CLOUDFLARE_TUNNEL_TOKEN` set | `cloudflared` container starts, tunnel connects |
| `docker compose up` (no `--profile tunnel`) | Only `remy`, `relay`, `ollama` start — no `cloudflared` |
| remy container restarts | `cloudflared` reconnects automatically |
| `CLOUDFLARE_TUNNEL_TOKEN` not set | `cloudflared` exits immediately; other services unaffected |

---

## Out of Scope

- Exposing other ports (relay MCP on 8765 stays localhost-only — never expose this)
- Cloudflare Access policies (Zero Trust application-level auth) — bearer token is sufficient
- Dynamic DNS or router port forwarding — tunnel replaces both
- Metrics scraping by an external Prometheus — use `/telemetry` pull instead
