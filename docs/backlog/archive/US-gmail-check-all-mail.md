# User Story: Check All Mail (Beyond INBOX)

**Status:** ✅ Done

<!-- Filename: US-gmail-check-all-mail.md -->

## Summary

As Dale, I want Remy to check unread mail across Gmail labels that Google doesn't surface to the main Inbox (e.g. Promotions, Updates, Forums) so that I don't miss new email that never appears in my default Inbox view.

---

## Background

Google routes many messages into category tabs (Promotions, Updates, Forums, Social) or keeps them out of the default INBOX view. Remy's unread flows today are INBOX-only: `read_emails` and `get_unread` / `get_unread_summary` in `remy/google/gmail.py` use `in:inbox` or the INBOX label. So Remy can report "Inbox is clear" while there are unread emails in Promotions or Updates that Dale might care about.

Related: **US-gmail-label-search** adds optional `labels` to `search_gmail` and supports ALL_MAIL, PROMOTIONS, etc. This story focuses on **unread** flows (read_emails, unread summary, and any briefing/automation that "checks email") so that "check my mail" and morning-briefing email context consider mail beyond INBOX.

---

## Acceptance Criteria

1. **Optional scope for `read_emails`.** The `read_emails` tool accepts an optional parameter (e.g. `scope` or `labels`) that defaults to INBOX for backwards compatibility. When set to a broader scope (e.g. `["INBOX", "PROMOTIONS", "UPDATES"]` or `"all"` / `ALL_MAIL`), Remy fetches unread emails from those labels (or all mail when `ALL_MAIL`).
2. **Unread count and summary beyond INBOX.** `get_unread` and `get_unread_summary` in GmailClient support an optional label/scope so callers can request "unread in INBOX" (current behaviour) or "unread across INBOX + Promotions + Updates" (or all mail). Tool schema and description make it clear when Remy is reporting "inbox only" vs "all mail" or "selected labels".
3. **Morning briefing and automations.** When the morning briefing (or other proactive triggers) fetches "new email" context, they can optionally use the broader scope so the briefing doesn't imply "no new mail" when there is unread mail in other tabs. This may be a setting (e.g. "briefing checks: inbox_only | primary_tabs | all_mail") or a sensible default (e.g. INBOX + PROMOTIONS + UPDATES for "primary tabs").
4. **Clear wording to the user.** When Remy reports unread counts or summaries, it is clear what scope was used (e.g. "12 unread in Inbox" vs "28 unread across Inbox, Promotions, and Updates").
5. **No regression.** When the new parameter is omitted, behaviour is unchanged: INBOX-only for `read_emails`, `get_unread`, and `get_unread_summary`.

---

## Implementation

**Files:** `remy/google/gmail.py`, `remy/ai/tools/schemas.py`, `remy/ai/tools/email.py`, `remy/scheduler/briefings/` (if briefing email context is built there), `remy/bot/handlers/email.py` (if `/gmail-unread` should support a flag).

### 1. GmailClient

- `get_unread(limit=..., label_ids=...)` — when `label_ids` is None, keep current behaviour (`in:inbox` or INBOX label). When provided, use search with `is:unread` and the given label IDs (or no label filter for "all mail").
- `get_unread_count(label_ids=...)` — either sum unread from each label or use a single search count; document behaviour when `label_ids` includes multiple labels.
- `get_unread_summary(label_ids=...)` — delegate to `get_unread_count` and `get_unread` with the same scope.

### 2. read_emails tool

- Add optional `scope` or `labels` to the schema. Options could be: default (INBOX), `primary_tabs` (INBOX + PROMOTIONS + UPDATES), or explicit list. Tool description should tell Claude when to use broader scope (e.g. "user asked to check all mail" or "morning briefing context").

### 3. Briefing / proactive

- If the conversational briefing uses `read_emails` or a similar call to get "new email" context, pass the configured scope (from settings or a constant like `primary_tabs`). If briefing context is built in a different way, ensure that path also respects the chosen scope.

### 4. Slash commands (optional)

- `/gmail-unread` and `/gmail-unread-summary` may gain an optional flag (e.g. `--all` or `--tabs`) to request broader scope; otherwise they remain INBOX-only.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| `read_emails` with no scope | INBOX only (unchanged) |
| `read_emails` with scope primary_tabs or labels INBOX,PROMOTIONS,UPDATES | Unread from those labels returned; reply indicates scope |
| "Check all my new email" / "Any new mail everywhere?" | Remy uses broader scope and reports accordingly |
| Morning briefing, default config | Either INBOX-only or configurable scope; wording reflects scope |
| `get_unread_count()` no args | Same as today (INBOX count) |

---

## Out of Scope

- Changing default Gmail tab behaviour in the Gmail UI.
- Search semantics (covered by US-gmail-label-search); this story is about unread listing and summary flows only.
