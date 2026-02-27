# Gmail Quick Wins — Briefing for Remy

**Account:** hello@dalerogers.com.au
**Date:** 27 Feb 2026
**Goal:** Bulk label + bulk delete ~400 emails across 9 categories

---

## What This Is

Dale ran a Gmail audit and identified a backlog of unlabelled and deleteable emails. You're the one with the API tokens, so this is yours to run.

There's a ready-made Python script (`gmail_quickwins.py`) that does everything. It has a **dry run mode** (default) so you can see exactly what it will do before committing.

---

## What the Script Does

**12 deletion actions** — moves to Trash:
- LinkedIn notification noise (digests, "add X", weekly stats) — ~80 emails
- Microsoft Store promos
- DocHub & cloudHQ marketing (repetitive)
- YouTube comment reply notifications
- OpenTable restaurant promos
- Swarm / Foursquare
- Pinterest legal compliance notices
- AusTender notifications (already-read ones only — safe)
- LinkedIn newsletter emails
- Kmart order/collection/refund emails (resolved)
- Food delivery receipts (Wokitup, Mills & Grills)

**13 labelling actions** — applies Dale's existing labels:
| Emails | → Label |
|---|---|
| Radford Nexus Digest (school, daily) | 4-Personal & Family |
| Radford Accounts (school fees) | 4-Personal & Family |
| Strata / Linq Apartments | 4-Personal & Family |
| Hockey club receipts (revolutionise) | 4-Personal & Family |
| LinkedIn Job Alerts (unread) | 1-Work & Career |
| AusTender (unlabelled) | 1-Work & Career |
| Hatch job recommendations | 1-Work & Career |
| Cursor AI updates | 2-Projects & Code |
| Finance emails (NAB, Ubank, Plenti, Zip, Australian Unity, Crazy Domains) | 3-Finance & Admin |
| Amazon AU orders/dispatch | 3-Finance & Admin |
| Hobby newsletters (boats, RC planes, paint, seeds) | 5-Hobbies & Interests |
| Canberra Innovation Network (CBRIN) | 7-Community & Events |
| Subscriptions (Linkt, Qantas FF, Stan, Disney+, Airbnb) | 8-Subscriptions & Services |

---

## Setup

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

Place your token in the same directory as the script:
- `token.json` — OAuth token (preferred), OR
- `credentials.json` — OAuth client credentials (script will prompt for browser auth on first run)

Or set env vars:
```bash
export GMAIL_TOKEN_PATH=/path/to/token.json
export GMAIL_CREDENTIALS_PATH=/path/to/credentials.json
```

**Required OAuth scope:** `https://www.googleapis.com/auth/gmail.modify`

---

## Running It

### Step 1 — Dry run first (no changes made)
```bash
python gmail_quickwins.py
```
This shows you every action and how many messages it would affect. Nothing is modified.

### Step 2 — Review the output, then execute
```bash
python gmail_quickwins.py --execute
```

### Other useful flags

Run only deletions:
```bash
python gmail_quickwins.py --category deletion --execute
```

Run only labelling:
```bash
python gmail_quickwins.py --category labelling --execute
```

Run a single action (useful for testing one at a time):
```bash
python gmail_quickwins.py --action delete_linkedin_noise --execute
```

List all action IDs:
```bash
python gmail_quickwins.py --list-actions
```

---

## Notes

- **Deletion = moves to Trash**, not permanent delete. Gmail auto-purges Trash after 30 days, or Dale can empty it manually.
- The script processes messages in batches of 1,000 using Gmail's `batchModify` API — efficient and within rate limits.
- The `--has:userlabels` filter on some labelling queries means it won't re-label things Dale has already manually labelled.
- The AusTender deletion query uses `is:read` — so it only trashes ones Dale has already opened. Unread ones are left alone.
- If a label name isn't found in the account (e.g. a typo), the script will warn and skip that action rather than erroring out.

---

## Label Names in the Account (confirmed)

Dale's labels use exact names including the number prefix:
- `1-Work & Career`
- `2-Projects & Code`
- `3-Finance & Admin`
- `4-Personal & Family`
- `5-Hobbies & Interests`
- `6-Health & Wellness`
- `7-Community & Events`
- `8-Subscriptions & Services`
- `9-For-Deletion`

The script looks these up dynamically via the Labels API so the IDs don't need to be hardcoded.

---

## Questions?

Ping Dale or refer back to the full audit report (`gmail-audit.html`) which has the rationale behind each decision.
