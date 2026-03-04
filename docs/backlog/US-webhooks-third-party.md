# User Story: Webhooks for Third-Party (CI, Zapier)

**Status:** ⬜ Backlog

## Summary
As a developer or power user, I want to send notifications and trigger actions in Remy from CI, Zapier, or other tools via webhooks so that build results, alerts, or automations can surface in Remy and be acted on.

---

## Background

**Tier 3 — Nice to have.** Remy is today driven by Telegram and the relay; there is no public HTTP endpoint for external systems to push events. A webhook endpoint would allow: (1) CI (e.g. GitHub Actions, GitLab) to post “build failed” or “deploy done” and have Remy notify the user or post to a chat; (2) Zapier/Make to send a payload that Remy turns into a reminder or a note; (3) Other integrations to push alerts that appear alongside other Remy notifications.

Relevant: outbound messaging (proactive scheduler, Telegram API), allowed users, and any existing HTTP API surface (e.g. health or admin routes). Security is critical: webhooks must be authenticated and rate-limited.

---

## Acceptance Criteria

1. **Webhook endpoint.** A single HTTP POST endpoint (e.g. `/webhook` or `/incoming`) accepts JSON payloads. Documented schema: at least a required field for “what to do” (e.g. `action`: `notify` | `remind` | `note`) and payload fields (e.g. message text, optional reminder time, optional label).
2. **Authentication.** Requests must be authenticated. Options: (a) shared secret in header (e.g. `X-Webhook-Secret: <token>`), or (b) signed payload (e.g. HMAC of body). Token/secret is configurable (e.g. env `REMY_WEBHOOK_SECRET`); requests without valid auth are rejected with 401.
3. **Notify action.** `action: notify`: Remy sends the provided message to the primary Telegram chat (or a configured “webhook chat”) so the user sees it like a proactive message. Optional: include source label (e.g. “CI”, “Zapier”) in the message.
4. **Remind action (optional).** `action: remind`: Create a one-time reminder with the given label and fire_at (or delay_seconds); same behaviour as the existing one-time reminder tool, scoped to the configured user.
5. **Note action (optional).** `action: note`: Store as a shared note or internal note for the user (e.g. for later retrieval or briefing context). Behaviour can align with relay notes or a simple “webhook_notes” store.
6. **Rate limiting and idempotency.** Apply rate limiting per token or per IP (e.g. 60 requests/minute). Optional: idempotency key in header to deduplicate duplicate deliveries.
7. **Single user or routing.** For MVP, webhook events are delivered to a single configured user (e.g. first in allowed users) or a dedicated “webhook user”. Multi-tenant or routing by payload can be a follow-up.

---

## Implementation

**Files:** New module for webhook HTTP handling (e.g. `remy/web/webhooks.py` or under `remy/bot/` if the web app lives there), route registration, config for `REMY_WEBHOOK_SECRET` and optional `REMY_WEBHOOK_CHAT_ID`.

### Request body (example)

```json
{
  "action": "notify",
  "message": "Build failed on main",
  "source": "GitHub Actions"
}
```

```json
{
  "action": "remind",
  "label": "Review PR #42",
  "fire_at": "2026-03-05T14:00:00",
  "source": "Zapier"
}
```

### Auth

- Read `X-Webhook-Secret` or `Authorization: Bearer <token>`. Compare with `REMY_WEBHOOK_SECRET`. If not set, reject or disable webhook route. Optionally support HMAC: `X-Webhook-Signature: sha256=<hex>` with body HMAC-SHA256(secret, body).

### Notify

- Resolve primary chat id (or webhook-specific chat id). Enqueue or send via existing Telegram send path (e.g. same as proactive scheduler). Prepend or append `[source]` if provided.

### Remind

- Call the same logic as `exec_set_one_time_reminder` for the configured user (or user derived from payload if supported later). Validate fire_at and label.

### Note

- Insert into shared_notes or a dedicated table with tags (e.g. `["webhook", source]`); or minimal “webhook_log” table for display in a simple “recent webhook events” view later.

### Notes

- Use a single webhook secret for all callers in MVP; multiple tokens or per-caller secrets can be added later.
- Log webhook requests (action, source, success/failure) for debugging; avoid logging full message bodies if they may be sensitive.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| POST with valid secret and action=notify | 200; user receives message in Telegram |
| POST with invalid or missing secret | 401; no message sent |
| POST action=remind with valid fire_at | 200; one-time reminder created for configured user |
| POST with invalid JSON or missing action | 400; clear error body |
| Rate limit exceeded | 429; no processing |
| action=note | 200; note stored; optional confirmation in response |

---

## Out of Scope

- Inbound Telegram webhook (Telegram’s own webhook for updates) — that’s a separate configuration topic.
- Full Zapier “Remy app” with many actions/triggers; this story is “one endpoint, a few actions”.
- Webhook UI (listing, revoking tokens) — config via env only for MVP.
