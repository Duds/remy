# User Story: Android Phone Setup for SMS and Wallet

**Status:** ⬜ Backlog

## Summary

As a user, I want a single checklist to set up my Android phone so that Remy receives my SMS and Google Wallet notifications via the existing webhooks — without cloud intermediaries and with minimal one-time configuration.

---

## Background

Remy already has **POST /webhook/sms** (US-sms-ingestion) and **POST /webhook/notification** (US-google-wallet-monitoring) implemented. This PBI is the **user-facing setup**: install apps, configure Tailscale, and point the phone at Remy. No backend changes.

**Prerequisites:** Remy running with `SMS_WEBHOOK_SECRET` set in `.env`. Remy’s health server (e.g. port 8080) reachable via Tailscale from the phone.

---

## Acceptance Criteria

1. **SMS setup steps documented.** One checklist covers: install SMS Gateway for Android, install Tailscale on phone and host, get Remy’s Tailscale IP, set webhook URL to `http://<remy-tailscale-ip>:8080/webhook/sms`, set header `X-Secret: <SMS_WEBHOOK_SECRET>`.
2. **Wallet setup steps documented.** Checklist covers: install Tasker, grant Notification Access to Tasker, create profile (Event: Google Wallet notification → Task: HTTP POST to `http://<remy-tailscale-ip>:8080/webhook/notification` with `X-Secret` and JSON body per US-google-wallet-monitoring).
3. **Optional: setup script or doc in repo.** Either a markdown doc (e.g. `docs/setup/android-sms-wallet.md`) or a short script that prints the exact URLs and curl examples for the user’s `SMS_WEBHOOK_SECRET` and Tailscale IP (no secrets in output).
4. **Verification step.** User can confirm SMS and Wallet are working (e.g. send a test SMS, make a test Wallet transaction; Remy receives and user can ask “what texts did I get?” / “what was my last Wallet transaction?”).

---

## Implementation

**Files:** `docs/setup/android-sms-wallet.md` (or equivalent in docs/).

- Reuse the “Phone setup” sections from archived US-sms-ingestion and US-google-wallet-monitoring.
- Include: Tailscale IP how-to, SMS Gateway app settings screenshot or step list, Tasker profile export or step list.
- Link to Remy’s `.env` vars: `SMS_WEBHOOK_SECRET`, optional `SMS_ALLOWED_SENDERS`, `SMS_KEYWORD_FILTER`.

### Notes

- No code changes to Remy; webhooks and tools are already implemented.
- Single-user focus: one primary chat receives alerts.

---

## Test Cases

| Scenario | Expected |
|---------|----------|
| User follows SMS checklist | Incoming SMS triggers Telegram alert and appears in get_sms_messages |
| User follows Wallet checklist | Wallet transaction triggers Telegram alert and appears in get_wallet_transactions |
| Wrong X-Secret | 401; no alert; request logged |

---

## Out of Scope

- Sending SMS from Remy (separate story).
- iMessage / RCS.
- Non-Android devices.
