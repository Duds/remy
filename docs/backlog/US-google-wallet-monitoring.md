# User Story: Google Wallet Notification Monitoring

## Summary
As a user, I want Remy to alert me via Telegram whenever Google Wallet processes a
transaction, so I can catch unexpected charges immediately without checking my phone.

---

## Background

Google Wallet does not reliably send email receipts (behaviour varies by card issuer and
region), and there is no public Wallet API. However, every Wallet transaction fires an
Android system notification — visible in the notification shade. Android's
`NotificationListenerService` grants trusted apps permission to read these notifications.

**Tasker** (already recommended for SMS in `US-sms-ingestion`) has a built-in
**Notification Received** profile event that captures any notification by app package name.
The Wallet notification text contains the merchant, amount, and card used — all the
information needed.

This story **reuses the `/webhook/notification` endpoint** and Tailscale tunnel from
`US-sms-ingestion`. No additional infrastructure is needed if that story is implemented
first. If implementing standalone, that infrastructure must be set up as a prerequisite.

---

## Acceptance Criteria

1. **Telegram alert on every Wallet transaction** within seconds of the notification
   appearing on the phone:
   ```
   💳 Google Wallet
   Tim Hortons — $4.27
   Visa ••••1234
   ```
2. **Pass-through for unparseable notifications.** If the notification text doesn't match
   the expected pattern, Remy still sends the raw notification title + body so no
   transaction is silently missed.
3. **Endpoint reuse.** Wallet notifications arrive at `POST /webhook/notification` with a
   `source` field (e.g. `"google_wallet"`) distinguishing them from future notification
   sources.
4. **Same token auth** as the SMS webhook (`X-Secret` header, `SMS_WEBHOOK_SECRET`).
5. **Transactions stored in SQLite** (`wallet_transactions` table) for later querying.
6. **Natural language queries:** "what was my last Wallet transaction?",
   "how much did I spend today?" — via `get_wallet_transactions` tool.

---

## Implementation

### Phone setup (one-time, manual)

**Prerequisite:** Tasker installed. Tailscale active on phone and Mac.

Grant Tasker **Notification Access** in Android Settings → Notifications → Notification
access. This is required for `NotificationListenerService`.

**Tasker profile:**

```
Event: Notification → Application = Google Wallet
         (package: com.google.android.apps.walletnfcrel)

Task: HTTP Request
  Method:  POST
  URL:     http://<remy-tailscale-ip>:8080/webhook/notification
  Headers: X-Secret: <SMS_WEBHOOK_SECRET>
           Content-Type: application/json
  Body:    {
             "source": "google_wallet",
             "title": "%antitle",
             "text":  "%antext",
             "subtext": "%ansubtext",
             "timestamp": "%TIMES"
           }
```

`%antitle`, `%antext`, `%ansubtext` are Tasker's built-in notification variables.

### remy changes

**New endpoint:** `POST /webhook/notification` (alongside `/webhook/sms`)

```python
@routes.post("/webhook/notification")
async def handle_notification(request: web.Request) -> web.Response:
    secret = request.headers.get("X-Secret", "")
    if secret != settings.sms_webhook_secret:
        return web.Response(status=401)

    data    = await request.json()
    source  = data.get("source", "unknown")
    title   = data.get("title", "")
    text    = data.get("text", "")
    subtext = data.get("subtext", "")
    ts      = data.get("timestamp", datetime.utcnow().isoformat())

    if source == "google_wallet":
        await wallet_handler.handle(title, text, subtext, ts)

    return web.Response(status=204)
```

**`remy/integrations/wallet.py`:**

```python
# Wallet notifications look like:
#   title:   "Tim Hortons"
#   text:    "$4.27 • Visa ••••1234"
# or sometimes:
#   title:   "Payment sent"
#   text:    "$50.00 to John Smith"

AMOUNT_RE = re.compile(r'\$[\d,]+\.\d{2}')

class WalletHandler:
    async def handle(self, title, text, subtext, ts):
        amount = AMOUNT_RE.search(text) or AMOUNT_RE.search(title)
        merchant = title  # best guess — Wallet puts merchant as title for tap-to-pay

        await wallet_store.save(
            merchant=merchant,
            amount=amount.group(0) if amount else None,
            raw_title=title,
            raw_text=text,
            occurred_at=ts,
        )

        alert = f"💳 Google Wallet\n{title}"
        if text:
            alert += f"\n{text}"
        await bot.send_message(PRIMARY_CHAT_ID, alert)
```

**Schema (`remy/memory/database.py`):**

```sql
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant    TEXT,
    amount      TEXT,
    raw_title   TEXT,
    raw_text    TEXT,
    occurred_at TEXT NOT NULL
);
```

**`tool_registry.py`:** Add `get_wallet_transactions` tool (period, merchant, limit filters).

---

## Notification Format Reference

Google Wallet notification text varies — the parser must be tolerant:

| Transaction type | Title | Text |
|---|---|---|
| Tap-to-pay | "Tim Hortons" | "$4.27 • Visa ••••1234" |
| Online purchase | "Payment approved" | "$29.99 at Amazon • Visa ••••1234" |
| Peer-to-peer send | "Payment sent" | "$50.00 to John Smith" |
| Refund | "Refund from Tim Hortons" | "$4.27 to Visa ••••1234" |
| Declined | "Payment declined" | "$4.27 at Tim Hortons" |

The handler should store and alert on **all** of these, not just successful purchases.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Tap-to-pay purchase | Alert with merchant + amount within seconds |
| Notification text doesn't match known pattern | Raw title + text sent as-is |
| Webhook POST with wrong token | `401`, no alert |
| "What was my last Wallet transaction?" | Remy queries `wallet_transactions` |
| "How much did I spend today?" | Remy sums `amount` column for today |
| Declined transaction notification | Alert still sent (not filtered out) |

---

## Out of Scope

- Email receipt parsing (not reliable — see story background)
- Spending budgets or alerts when over a threshold (future story, builds on this)
- Non-Wallet financial notifications (other bank apps need separate Tasker profiles)
- Replying to or disputing transactions via remy
