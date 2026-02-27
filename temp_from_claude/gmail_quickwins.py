"""
Gmail Quick Wins Script
Account: hello@dalerogers.com.au
Generated: 27 Feb 2026

Implements bulk labelling and deletion actions identified in the Gmail audit.

Requirements:
    pip install google-auth google-auth-oauthlib google-api-python-client

Auth:
    Expects a token.json (or credentials.json for OAuth flow) in the same directory,
    or set GMAIL_TOKEN_PATH env var to the token file location.
    Scopes needed: https://www.googleapis.com/auth/gmail.modify

Usage:
    python gmail_quickwins.py              # dry run — shows what WOULD happen
    python gmail_quickwins.py --execute    # actually applies changes
    python gmail_quickwins.py --action delete_linkedin_noise --execute
    python gmail_quickwins.py --list-actions
"""

import os
import sys
import time
import argparse
from typing import Optional

# ── Auth ──────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "token.json")
CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
USER_ID = "me"


def get_service():
    """Authenticate and return Gmail API service object."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.path.exists(CREDENTIALS_PATH):
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise FileNotFoundError(
                f"No token found at {TOKEN_PATH} and no credentials at {CREDENTIALS_PATH}. "
                "Provide a valid token.json or credentials.json."
            )
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ── Gmail helpers ─────────────────────────────────────────────────────────────

def get_label_id_map(service) -> dict[str, str]:
    """Return dict of {label_name_lower: label_id}."""
    result = service.users().labels().list(userId=USER_ID).execute()
    return {lbl["name"].lower(): lbl["id"] for lbl in result.get("labels", [])}


def search_messages(service, query: str, max_results: int = 5000) -> list[str]:
    """Return list of message IDs matching query."""
    ids = []
    page_token = None
    while True:
        kwargs = {"userId": USER_ID, "q": query, "maxResults": min(500, max_results - len(ids))}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        messages = resp.get("messages", [])
        ids.extend(m["id"] for m in messages)
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= max_results:
            break
    return ids


def batch_modify(service, message_ids: list[str], add_labels: list[str] = None,
                 remove_labels: list[str] = None, dry_run: bool = True) -> int:
    """Apply label changes to messages in batches of 1000. Returns count modified."""
    if not message_ids:
        return 0

    add_labels = add_labels or []
    remove_labels = remove_labels or []
    total = 0

    for i in range(0, len(message_ids), 1000):
        chunk = message_ids[i : i + 1000]
        if not dry_run:
            service.users().messages().batchModify(
                userId=USER_ID,
                body={
                    "ids": chunk,
                    "addLabelIds": add_labels,
                    "removeLabelIds": remove_labels,
                },
            ).execute()
            time.sleep(0.3)  # be gentle with rate limits
        total += len(chunk)

    return total


def trash_messages(service, message_ids: list[str], dry_run: bool = True) -> int:
    """Move messages to trash. Batches via batchModify with TRASH label."""
    return batch_modify(service, message_ids, add_labels=["TRASH"],
                        remove_labels=["INBOX"], dry_run=dry_run)


# ── Action definitions ────────────────────────────────────────────────────────
# Each action is a dict:
#   query        — Gmail search string
#   action       — "trash" | "label"
#   label_name   — (for "label" actions) human-readable label name
#   description  — shown in output
#   category     — "deletion" | "labelling"

ACTIONS = [
    # ── DELETION QUICK WINS ───────────────────────────────────────────────
    {
        "id": "delete_linkedin_noise",
        "category": "deletion",
        "description": "LinkedIn notifications/digests (NOT job alerts)",
        "query": (
            "from:(notifications-noreply@linkedin.com OR messages-noreply@linkedin.com) "
            "after:2025/02/27"
        ),
        "action": "trash",
    },
    {
        "id": "delete_microsoft_store",
        "category": "deletion",
        "description": "Microsoft Store promotional emails",
        "query": "from:Microsoftstore@microsoftstore.microsoft.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_dochub",
        "category": "deletion",
        "description": "DocHub marketing (duplicate emails)",
        "query": "from:noreply@dochub.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_cloudhq",
        "category": "deletion",
        "description": "cloudHQ marketing emails",
        "query": "from:marketing.emails@cloudhq.net after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_youtube",
        "category": "deletion",
        "description": "YouTube comment reply notifications",
        "query": "from:noreply@youtube.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_opentable",
        "category": "deletion",
        "description": "OpenTable restaurant promos",
        "query": "from:OpenTable@mgs.opentable.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_swarm",
        "category": "deletion",
        "description": "Swarm / Foursquare notifications",
        "query": "from:noreply@foursquare.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_pinterest_legal",
        "category": "deletion",
        "description": "Pinterest legal/compliance notices",
        "query": "from:pinbot@legal.pinterest.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_austender_read",
        "category": "deletion",
        "description": "AusTender notifications (already read)",
        "query": "from:No-Reply@tenders.gov.au is:read after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_linkedin_newsletters",
        "category": "deletion",
        "description": "LinkedIn newsletter emails",
        "query": "from:newsletters-noreply@linkedin.com after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_kmart_orders",
        "category": "deletion",
        "description": "Kmart order/refund/collection emails (resolved)",
        "query": "from:DonotReply.OnlineShop@orders.kmart.com.au after:2025/02/27",
        "action": "trash",
    },
    {
        "id": "delete_food_receipts",
        "category": "deletion",
        "description": "Food delivery receipts (Wokitup, Mills & Grills)",
        "query": "from:(info@wokitup.com.au OR no-reply@localserves.com.au) after:2025/02/27",
        "action": "trash",
    },

    # ── LABELLING QUICK WINS ──────────────────────────────────────────────
    {
        "id": "label_radford_nexus",
        "category": "labelling",
        "description": "Radford Nexus Digest → 4-Personal & Family",
        "query": "from:nexus@radford.act.edu.au -has:userlabels after:2025/02/27",
        "action": "label",
        "label_name": "4-Personal & Family",
    },
    {
        "id": "label_radford_accounts",
        "category": "labelling",
        "description": "Radford Accounts (school fees) → 4-Personal & Family",
        "query": "from:accounts@radford.act.edu.au after:2025/02/27",
        "action": "label",
        "label_name": "4-Personal & Family",
    },
    {
        "id": "label_strata",
        "category": "labelling",
        "description": "Strata / Linq Apartments → 4-Personal & Family",
        "query": "from:(info@stratamanager.net.au OR linqapartments.ec@outlook.com.au) after:2025/02/27",
        "action": "label",
        "label_name": "4-Personal & Family",
    },
    {
        "id": "label_hockey_club",
        "category": "labelling",
        "description": "Hockey club receipts (revolutionise) → 4-Personal & Family",
        "query": "from:no-reply@revolutionise.com.au -has:userlabels after:2025/02/27",
        "action": "label",
        "label_name": "4-Personal & Family",
    },
    {
        "id": "label_linkedin_job_alerts",
        "category": "labelling",
        "description": "LinkedIn Job Alerts (unread) → 1-Work & Career",
        "query": "from:jobalerts-noreply@linkedin.com is:unread after:2025/02/27",
        "action": "label",
        "label_name": "1-Work & Career",
    },
    {
        "id": "label_austender_unread",
        "category": "labelling",
        "description": "AusTender notifications (unlabelled) → 1-Work & Career",
        "query": "from:No-Reply@tenders.gov.au -has:userlabels after:2025/02/27",
        "action": "label",
        "label_name": "1-Work & Career",
    },
    {
        "id": "label_hatch_jobs",
        "category": "labelling",
        "description": "Hatch job recommendations → 1-Work & Career",
        "query": "from:(fam@email.hatch.team OR jenna@email.hatch.team) after:2025/02/27",
        "action": "label",
        "label_name": "1-Work & Career",
    },
    {
        "id": "label_cursor",
        "category": "labelling",
        "description": "Cursor AI updates → 2-Projects & Code",
        "query": "from:team@mail.cursor.com after:2025/02/27",
        "action": "label",
        "label_name": "2-Projects & Code",
    },
    {
        "id": "label_finance",
        "category": "labelling",
        "description": "Finance emails (NAB, Ubank, Plenti, Zip, Australian Unity, Crazy Domains) → 3-Finance & Admin",
        "query": (
            "from:(nab@updates.nab.com.au OR noreply@ubank.com.au OR contact@plenti.com.au "
            "OR no-reply@account.zip.co OR customerservice@email.australianunity.com.au "
            "OR noreply@crazydomains.com.au) -has:userlabels after:2025/02/27"
        ),
        "action": "label",
        "label_name": "3-Finance & Admin",
    },
    {
        "id": "label_amazon_orders",
        "category": "labelling",
        "description": "Amazon AU order/dispatch emails → 3-Finance & Admin",
        "query": "from:(shipment-tracking@amazon.com.au OR amazon.co.uk) -has:userlabels after:2025/02/27",
        "action": "label",
        "label_name": "3-Finance & Admin",
    },
    {
        "id": "label_hobbies",
        "category": "labelling",
        "description": "Hobby newsletters (boats, RC, paint, seeds) → 5-Hobbies & Interests",
        "query": (
            "from:(info@clcboats.com OR news@notify.hobbyking.com "
            "OR lincoln@paintonplastic.com OR admin@theseedcollection.com.au) after:2025/02/27"
        ),
        "action": "label",
        "label_name": "5-Hobbies & Interests",
    },
    {
        "id": "label_cbrin",
        "category": "labelling",
        "description": "Canberra Innovation Network events → 7-Community & Events",
        "query": "from:enquiries@cbrin.com.au after:2025/02/27",
        "action": "label",
        "label_name": "7-Community & Events",
    },
    {
        "id": "label_subscriptions",
        "category": "labelling",
        "description": "Subscription services (Linkt, Qantas FF, Stan, Disney+, Airbnb) → 8-Subscriptions & Services",
        "query": (
            "from:(noreply@digital.linkt.com.au OR qantasff@e.qantas.com "
            "OR accounts-noreply@mailer.stan.com.au OR disneyplus@trx.mail2.disneyplus.com "
            "OR discover@airbnb.com) -has:userlabels after:2025/02/27"
        ),
        "action": "label",
        "label_name": "8-Subscriptions & Services",
    },
]


# ── Runner ────────────────────────────────────────────────────────────────────

def run_actions(service, actions: list[dict], dry_run: bool = True,
                action_filter: Optional[str] = None):
    label_map = get_label_id_map(service)

    print(f"\n{'=' * 65}")
    print(f"  Gmail Quick Wins  —  {'DRY RUN (no changes made)' if dry_run else '🚨 LIVE EXECUTION'}")
    print(f"  Account: hello@dalerogers.com.au")
    print(f"{'=' * 65}\n")

    total_affected = 0
    errors = []

    for act in actions:
        if action_filter and act["id"] != action_filter:
            continue

        label = act.get("label_name", "")
        print(f"[{act['category'].upper()}] {act['description']}")
        print(f"  Query: {act['query'][:80]}{'...' if len(act['query']) > 80 else ''}")

        try:
            ids = search_messages(service, act["query"])
            count = len(ids)

            if count == 0:
                print(f"  → No messages found. Skipping.\n")
                continue

            print(f"  → {count} message(s) found", end="")

            if act["action"] == "trash":
                affected = trash_messages(service, ids, dry_run=dry_run)
                print(f" | {'WOULD MOVE' if dry_run else 'MOVED'} {affected} to Trash")

            elif act["action"] == "label":
                label_id = label_map.get(label.lower())
                if not label_id:
                    msg = f"Label '{label}' not found in account. Available labels: {list(label_map.keys())}"
                    print(f"\n  ⚠️  {msg}")
                    errors.append(msg)
                    print()
                    continue
                affected = batch_modify(service, ids, add_labels=[label_id], dry_run=dry_run)
                print(f" | {'WOULD APPLY' if dry_run else 'APPLIED'} label [{label}] to {affected}")

            total_affected += count

        except Exception as e:
            msg = f"Error in action '{act['id']}': {e}"
            print(f"\n  ❌ {msg}")
            errors.append(msg)

        print()

    print(f"{'=' * 65}")
    print(f"  Total messages affected: {total_affected}")
    if dry_run:
        print(f"  ⚠️  DRY RUN — no changes made. Run with --execute to apply.")
    else:
        print(f"  ✅ Done.")
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors:
            print(f"    • {e}")
    print(f"{'=' * 65}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gmail Quick Wins for hello@dalerogers.com.au")
    parser.add_argument("--execute", action="store_true",
                        help="Actually apply changes (default is dry run)")
    parser.add_argument("--action", type=str, default=None,
                        help="Run a single action by ID (see --list-actions)")
    parser.add_argument("--list-actions", action="store_true",
                        help="List all available action IDs and exit")
    parser.add_argument("--category", choices=["deletion", "labelling"], default=None,
                        help="Only run actions of this category")
    args = parser.parse_args()

    if args.list_actions:
        print("\nAvailable actions:\n")
        for cat in ["deletion", "labelling"]:
            print(f"  [{cat.upper()}]")
            for act in ACTIONS:
                if act["category"] == cat:
                    print(f"    {act['id']:<40} {act['description']}")
        print()
        return

    service = get_service()

    actions = ACTIONS
    if args.category:
        actions = [a for a in ACTIONS if a["category"] == args.category]

    run_actions(
        service,
        actions,
        dry_run=not args.execute,
        action_filter=args.action,
    )


if __name__ == "__main__":
    main()
