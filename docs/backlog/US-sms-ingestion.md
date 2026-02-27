# User Story: Android SMS Ingestion

## Summary
As a user, I want Remy to receive my incoming SMS messages so she can alert me to
important texts and let me respond or take action via Telegram — without needing to
pick up my phone for every message.

---

## Background

Android exposes SMS events to third-party apps via a standard Broadcast intent. A
lightweight open-source app — **SMS Gateway for Android** (free, no account) — runs a
local HTTP server on the phone and forwards every incoming SMS as a JSON webhook POST.
Drbot needs a new `/webhook/sms` endpoint to receive these POSTs.

The secondary challenge is **cellular connectivity**: when the phone is not on home WiFi,
it cannot reach `localhost:8080`. The recommended solution is **Tailscale**, which gives
drbot a stable private IP reachable from the phone over any network.

**No cloud intermediaries required. SMS never touches a third-party server.**

---

## Acceptance Criteria

1. **New `POST /webhook/sms` endpoint** in drbot accepts and validates incoming SMS payloads.
2. **Remy is notified via Telegram** for every inbound SMS with: sender number, message
   preview (first 200 chars), and timestamp. Format:
   ```
   📱 SMS from +16135550123
   "Hey, are you coming tonight?"
   Received: 3:42 PM
   ```
3. **Sender filtering (optional, configurable).** A list of allowed senders or keywords
   can be set in `.env` — if set, only matching SMS trigger a Telegram alert.
   If the list is empty (default), all SMS are forwarded.
4. **Webhook authentication.** The endpoint requires a secret token (set in `.env` as
   `SMS_WEBHOOK_SECRET`) passed as a header `X-Secret`. Requests without the correct
   token return `401`.
5. **Remy can read back recent SMS** on request: "what texts have I received today?"
   SMS are stored in a lightweight `sms_messages` SQLite table (sender, text, received_at).
6. **No data leaves the local network** (phone → Tailscale → drbot only).

---

## Implementation

### Phone setup (one-time, manual)

1. Install **SMS Gateway for Android** from F-Droid or Google Play.
   - GitHub: https://github.com/capcom6/android-sms-gateway
2. In the app: enable webhook mode, set URL to `http://<drbot-tailscale-ip>:8080/webhook/sms`,
   set the secret header `X-Secret: <SMS_WEBHOOK_SECRET>`.
3. Install **Tailscale** on the phone and on the Mac running drbot.
   - Add `network_mode: host` or expose port 8080 via the Tailscale IP in `docker-compose.yml`.

### drbot changes

**New file:** `drbot/integrations/sms.py`

```python
SMS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS sms_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sender      TEXT NOT NULL,
    body        TEXT NOT NULL,
    received_at TEXT NOT NULL
)
"""

class SMSStore:
    async def save(self, sender: str, body: str, received_at: str) -> None: ...
    async def recent(self, hours: int = 24) -> list[dict]: ...
```

**`drbot/bot/webhook.py` (or extend `main.py` aiohttp app):**

```python
@routes.post("/webhook/sms")
async def handle_sms(request: web.Request) -> web.Response:
    secret = request.headers.get("X-Secret", "")
    if secret != settings.sms_webhook_secret:
        return web.Response(status=401)

    payload = await request.json()
    sender = payload.get("from") or payload.get("sender", "unknown")
    body   = payload.get("message") or payload.get("body", "")
    ts     = payload.get("receivedAt", datetime.utcnow().isoformat())

    await sms_store.save(sender, body, ts)

    if _should_notify(sender, body):
        await bot.send_message(
            PRIMARY_CHAT_ID,
            f"📱 SMS from {sender}\n\"{body[:200]}\"\nReceived: {ts}",
        )
    return web.Response(status=204)
```

**`tool_registry.py`:** Add `get_sms_messages` tool so Remy can answer
"what texts did I get today?" via natural language.

**`.env` additions:**
```
SMS_WEBHOOK_SECRET=<random 32-char string>
SMS_ALLOWED_SENDERS=   # comma-separated E.164 numbers, or empty for all
SMS_KEYWORD_FILTER=    # comma-separated keywords, or empty for all
```

---

## Tailscale Setup Note

Tailscale creates a WireGuard mesh between the phone and the Mac. Once installed on both:
- Mac gets a stable IP like `100.x.y.z` (visible in Tailscale admin)
- Phone can POST to `http://100.x.y.z:8080/webhook/sms` over WiFi *or* cellular
- No port-forwarding, no public exposure, no firewall changes needed

In `docker-compose.yml`, bind drbot to `0.0.0.0:8080` (already the case for health check)
so the Tailscale IP can reach it.

---

## Test Cases

| Scenario | Expected |
|---|---|
| SMS received from any number (no filter set) | Telegram alert sent within 3 s |
| SMS received, sender not in allowed list | Alert suppressed |
| Webhook POST with wrong secret | `401` returned, no alert |
| Malformed JSON payload | `400` returned, logged |
| "What texts did I get today?" | Remy queries `sms_store.recent(24)` and summarises |
| Phone on cellular (Tailscale active) | Webhook reaches drbot; same behaviour |

---

## Out of Scope

- Sending SMS replies via drbot (requires SMS Gateway outbound API — separate story)
- iMessage / RCS support
- SMS search beyond recent history (full text search can be added later)
- Notification forwarding beyond SMS (see `US-google-wallet-monitoring`)
