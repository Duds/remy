# Server setup — env, SOUL & HEARTBEAT

Checklist for configuring a Remy server: environment, SOUL intent, and optional HEARTBEAT local overrides.

---

## 1. Environment (.env on server)

Copy from `.env.example` and fill in secrets.

### Required (no defaults)

- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `ANTHROPIC_API_KEY` — Anthropic API key
- `TELEGRAM_ALLOWED_USERS_RAW` — your Telegram user ID(s), comma-separated

### Scheduler & heartbeat

- `HEARTBEAT_ENABLED=true`
- `SCHEDULER_TIMEZONE=Australia/Sydney` (or your IANA timezone)

Optional overrides (defaults are fine for most):

- `HEARTBEAT_CRON` — default: `*/30 * * * *`
- `HEARTBEAT_QUIET_START` / `HEARTBEAT_QUIET_END` — e.g. 22 and 7
- `ORIENTATION_WAKE_HOUR`, `REFLECTION_HOUR`, `WELLBEING_WINDOW_START`, `WELLBEING_WINDOW_END`

When `HEARTBEAT_ENABLED=false`, legacy crons run. The afternoon check (`AFTERNOON_CHECK_CRON`, default `0 17 * * *`) is the mediated check-in — set it to the time you want.

### Email scope

- `BRIEFING_EMAIL_SCOPE` — `inbox_only` | `primary_tabs` | `all_mail` for morning briefing. Heartbeat always uses all mail for unread count.

### Optional

- `SOUL_MD_PATH`, `SOUL_COMPACT_PATH`
- `HEALTH_API_TOKEN`, `RELAY_MCP_URL`, `RELAY_MCP_SECRET`, `RELAY_DB_PATH`
- `FILE_LINK_BASE_URL`, `GDRIVE_MOUNT_PATHS`

---

## 2. SOUL — intent for proactive check-ins

In `config/SOUL.md` (or `config/SOUL.compact.md`), add a **Proactive check-ins** section so the model knows what each scheduled contact is for:

- **Morning:** Daily orientation — goals, calendar, email summary if no interaction yet today.
- **Evening:** End-of-day nudge — goals, reflection.
- **Afternoon (e.g. 5pm):** Describe the intent of this check-in (e.g. wellbeing, accountability). The model should be compassionate, context-aware, and use memory and today's conversation; warmth and presence over advice. Do not sound like a reminder app; sound like the agent checking in.

You can copy the block from `config/SOUL.example.md` and adjust wording to your voice. The important part: the model needs to know what the afternoon check is for so it can tailor tone and content.

---

## 3. HEARTBEAT — public vs local

- **HEARTBEAT.md** — already in the repo. No changes needed unless you want to tweak the checklist.
- **HEARTBEAT.local.md** — create on the server only (gitignored). Copy from `config/HEARTBEAT.example.md` and fill in your personal thresholds and intent.

### HEARTBEAT.local.md — what to put in

- **Goals:** Stale goal threshold (e.g. N days without progress), goal tags that warrant a nudge.
- **Calendar:** Event keywords that mean "always surface", lead time for "meeting starting soon" (e.g. 15 minutes).
- **Email:** Unread count threshold, sender patterns or labels that are high-priority.
- **Wellbeing Check-in:** Time window (e.g. 13:00–19:00, primary 17:00–18:30), minimum hours between check-ins (e.g. 36). Describe the intent of this check-in so the model can tailor tone. Any other personal signals go here. Do not commit this file.

---

## 4. Quick checklist on the server

1. Copy `.env.example` → `.env`; set `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `TELEGRAM_ALLOWED_USERS_RAW`.
2. Set `HEARTBEAT_ENABLED=true`, `SCHEDULER_TIMEZONE` to your timezone. If using legacy crons, set `AFTERNOON_CHECK_CRON` (e.g. `0 17 * * *`).
3. In SOUL: add the **Proactive check-ins** block so the afternoon check intent is clear.
4. Create `config/HEARTBEAT.local.md` from `config/HEARTBEAT.example.md`; fill in wellbeing window, min hours between check-ins, and any other personal thresholds.
5. Restart the bot and verify health: `curl http://localhost:8080/health`.
