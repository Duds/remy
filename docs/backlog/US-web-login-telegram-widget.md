# User Story: Web Login for Dashboards (Telegram Login Widget)

**Status:** ⬜ Backlog

## Summary
As a user, I want to sign in on the web with my Telegram account (Telegram Login Widget) so that I can view stats and costs in the browser without going through the bot.

---

## Background

**Tier 3 — Nice to have.** Stats and cost views are currently available via the bot (e.g. `/stats`, `/goal-status`, and any admin/costs commands). A web dashboard would allow viewing the same (or a subset) in the browser. To keep auth simple and consistent with the Telegram-first product, use the [Telegram Login Widget](https://core.telegram.org/widgets/login): the user clicks “Log in with Telegram” on a page, Telegram validates the user and returns a hash; the server verifies the hash and establishes a session. Only users whose Telegram user_id is in the allowed list can access the dashboard.

Relevant code: `remy/bot/handlers/core.py` (e.g. /stats), admin/diagnostics handlers, any existing web routes or Flask/FastAPI app that might serve dashboards; `remy/config` for allowed users and bot token.

---

## Acceptance Criteria

1. **Login widget.** A web page (e.g. `/login` or the root of the dashboard) embeds the Telegram Login Widget configured for the Remy bot. On success, the widget returns auth data (id, first_name, username, hash, etc.) to the front end.
2. **Server-side verification.** The backend receives the auth payload (e.g. from a form POST or API call), verifies the hash using the bot token per Telegram’s docs, and checks that `id` is in the allowed users list. If valid, create a session (cookie or token) and redirect to the dashboard.
3. **Dashboard view.** After login, the user can view a dashboard that shows at least: usage stats (e.g. 7d/30d/90d) and cost information consistent with what the bot provides. Data is read-only and scoped to the logged-in user.
4. **Security.** No dashboard access without a valid Telegram Login Widget auth and user_id in the allowed list. Sessions expire or are invalidated appropriately (e.g. session timeout or “log out”).
5. **No bot dependency for read-only view.** The dashboard uses the same data sources as the bot (e.g. api_calls, goals, or analytics) but does not require the user to send a message in Telegram to see the page.

---

## Implementation

**Files:** New or existing web app module (e.g. under `remy/bot/` or `remy/web/`), template or static HTML for login + dashboard, config for `TELEGRAM_BOT_TOKEN` and allowed user IDs.

### Telegram Login Widget verification

- Telegram docs: hash = HMAC-SHA256(secret_key, data_check_string). Secret key = SHA256(bot_token). data_check_string = sorted key=value pairs (auth_date, first_name, id, etc.) newline-separated. Compare computed hash with received hash; reject if mismatch. Check auth_date is recent (e.g. within 5 minutes) to prevent replay.
- Allowed users: from settings (e.g. `telegram_allowed_users`); only those user ids can get a session.

### Session

- Use a signed cookie or a short-lived JWT storing user_id (and optionally expiry). On each dashboard request, verify the session and load data for that user_id.

### Dashboard content

- Reuse or call the same logic that powers `/stats` and cost reporting (e.g. query api_calls, aggregate by period). Expose as HTML tables or simple charts; avoid duplicating business logic.

### Notes

- Bot token must be available server-side for hash verification; never expose it to the client.
- Consider HTTPS only and secure cookie flags in production.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Allowed user completes Telegram Login Widget | Redirect to dashboard; stats/costs visible for that user |
| Disallowed user completes widget (valid hash) | Reject: “Access denied” or redirect to login with message |
| Invalid or tampered hash | Reject: no session |
| Expired session | Redirect to login |
| Direct access to /dashboard without session | Redirect to login |

---

## Out of Scope

- Editing data from the web (e.g. changing goals); read-only in this story.
- OAuth or non-Telegram login providers.
- Full feature parity with all bot commands on the web.
