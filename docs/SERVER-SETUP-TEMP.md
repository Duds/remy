# Server setup — env, SOUL & HEARTBEAT (real intent)

**Temporary file.** Copy what you need to the server, then delete this file. **Do not commit.** It contains intent and personal context for configuration.

---

## 1. Environment (.env on server)

Copy from `.env.example` and fill in secrets. Below are the ones that carry **real intent** or need explicit values.

### Required (no defaults)
```bash
TELEGRAM_BOT_TOKEN=...
ANTHROPIC_API_KEY=...
TELEGRAM_ALLOWED_USERS_RAW=123456789   # your Telegram user ID(s)
```

### Scheduler & heartbeat
```bash
HEARTBEAT_ENABLED=true
SCHEDULER_TIMEZONE=Australia/Sydney

# Optional overrides (defaults are fine for most)
# HEARTBEAT_CRON=*/30 * * * *
# HEARTBEAT_QUIET_START=22
# HEARTBEAT_QUIET_END=7
# ORIENTATION_WAKE_HOUR=7
# REFLECTION_HOUR=18
# WELLBEING_WINDOW_START=13
# WELLBEING_WINDOW_END=19
```

**Real intent:** When `HEARTBEAT_ENABLED=false`, the legacy crons run. The **afternoon check** (`AFTERNOON_CHECK_CRON`) is the **5pm sobriety / alcohol check-in** — mediated, compassionate, high-risk window ~5:00–6:30pm. Default: `AFTERNOON_CHECK_CRON=0 17 * * *`.

### Email scope
```bash
# Morning briefing: inbox_only | primary_tabs | all_mail
# Heartbeat always uses all mail for unread count.
BRIEFING_EMAIL_SCOPE=all_mail
```

### Optional (paths, relay, health, etc.)
```bash
# SOUL_MD_PATH=config/SOUL.md
# SOUL_COMPACT_PATH=config/SOUL.compact.md
# HEALTH_API_TOKEN=...
# RELAY_MCP_URL=...
# RELAY_MCP_SECRET=...
# RELAY_DB_PATH=...
# FILE_LINK_BASE_URL=...
# GDRIVE_MOUNT_PATHS=...
```

---

## 2. SOUL — add real intent for the afternoon check

In `config/SOUL.md` (or `config/SOUL.compact.md` if you use it), add a short section so Remy knows what the **afternoon check-in** is for. The code only says "Afternoon check-in"; the intent comes from SOUL or HEARTBEAT.local.

**Suggested block to add under "Context" or "What the Agent Does" (or a new "Proactive check-ins" section):**

```markdown
---

## Proactive check-ins

- **Morning:** Daily orientation — goals, calendar, email summary if no interaction yet today.
- **Evening:** End-of-day nudge — goals, reflection.
- **Afternoon (5pm):** This is the **sobriety / alcohol check-in**. Dale's high-risk window is often 5:00–6:30pm. Your job is to meet him where he is — compassionate, context-aware, never preachy or generic. Use what you know from memory and today's conversation. One or two short sentences; warmth and presence over advice. Do not sound like a reminder app; sound like Remy checking in.
```

Adjust wording to your voice. The important part: the model needs to know the afternoon check is the sobriety check so it can tailor tone and content.

---

## 3. HEARTBEAT — public vs local

- **HEARTBEAT.md** — already in the repo. No changes needed on the server unless you want to tweak the checklist.
- **HEARTBEAT.local.md** — create this on the server only (gitignored). Copy from `config/HEARTBEAT.example.md` and fill in **real intent** below.

### HEARTBEAT.local.md — what to put in (real intent)

Create `config/HEARTBEAT.local.md` on the server with content like this. **Do not commit this file.**

```markdown
# HEARTBEAT.local.md — personal thresholds (do not commit)

Copy from HEARTBEAT.example.md and customise. Below: real intent for wellbeing.

---

## Goals (local overrides)

- Stale goal threshold: N days without progress (e.g. 5).
- Goal tags or names that always warrant a nudge.

---

## Calendar (local overrides)

- Event keywords that mean "always surface" (e.g. "interview", "doctor").
- Lead time for "meeting starting soon" (e.g. 15 minutes).

---

## Email (local overrides)

- Unread count threshold above which to surface (e.g. 20).
- Sender patterns or labels that are high-priority.

---

## Wellbeing Check-in (local only — real intent)

- **This is the sobriety / alcohol check-in.** Time window: 13:00–19:00 (primary window 17:00–18:30). Minimum hours between check-ins: 36.
- Dale's high-risk window is often 5:00–6:30pm. The model should be compassionate, context-aware, never preachy. Use memory and today's conversation; warmth and presence over advice.
- Any other personal signals or triggers go here. This file must not be committed.
```

Replace placeholders (N days, 15 minutes, 20, 36 hours, etc.) with your actual thresholds.

---

## 4. Quick checklist on the server

1. Copy `.env.example` → `.env`; fill `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `TELEGRAM_ALLOWED_USERS_RAW`.
2. Set `HEARTBEAT_ENABLED=true`, `SCHEDULER_TIMEZONE=Australia/Sydney`. If using legacy crons, set `AFTERNOON_CHECK_CRON=0 17 * * *` (real intent: 5pm sobriety check).
3. In SOUL: add the "Proactive check-ins" block so the afternoon check is clearly the sobriety check-in.
4. Create `config/HEARTBEAT.local.md` from the template above; fill in wellbeing window (13:00–19:00, min 36h between) and any other personal thresholds.
5. Delete this file (`docs/SERVER-SETUP-TEMP.md`) after copying. Do not commit it.
