#!/usr/bin/env python3
"""
Google Workspace integration test script.

Usage:
    python scripts/test_google_integration.py

Tests (in order):
  ✓ Credentials are configured
  ✓ Calendar: list upcoming events
  ✓ Calendar: create a TEST event (then delete it)
  ✓ Gmail: get unread count
  ✓ Gmail: fetch 3 unread email headers
  ✓ Gmail: classify promotional emails
  ✓ Docs: read a document (if doc URL/ID provided)
  ✓ Docs: append test text (if doc URL/ID provided)

Requires Google authentication via ADC (gcloud) or data/google_token.json.
Run scripts/setup_google_auth.py first if not yet authenticated.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

TOKEN_FILE = str(_ROOT / "data" / "google_token.json")

# ── optional: set this to a Google Doc URL or ID to test Docs integration ──
TEST_DOC_ID = os.environ.get("GOOGLE_TEST_DOC_ID", "")  # e.g. export in shell or add to .env


def _ok(msg: str) -> None:
    print(f"  ✅  {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌  {msg}")


def _info(msg: str) -> None:
    print(f"  ℹ️   {msg}")


def _header(msg: str) -> None:
    print(f"\n{'─'*50}\n{msg}\n{'─'*50}")


# ── pre-flight checks ─────────────────────────────────────────────────────────


def check_setup() -> bool:
    _header("Pre-flight: credentials & token")

    try:
        from remy.google.auth import get_credentials
        get_credentials(TOKEN_FILE)
        _ok("Google credentials available (ADC or token file)")
    except Exception as e:
        _fail(f"Google not authenticated: {e}")
        print("\n  Run: python scripts/setup_google_auth.py\n")
        return False

    return True


# ── calendar tests ────────────────────────────────────────────────────────────


async def test_calendar() -> bool:
    _header("Google Calendar")

    from remy.google.calendar import CalendarClient
    cal = CalendarClient(TOKEN_FILE)

    # List events
    try:
        events = await cal.list_events(days=7)
        if events:
            _ok(f"Listed {len(events)} upcoming event(s) in the next 7 days:")
            for e in events[:5]:
                print(f"       {cal.format_event(e)}")
            if len(events) > 5:
                print(f"       …and {len(events) - 5} more")
        else:
            _ok("Listed events — calendar is clear for the next 7 days")
    except Exception as e:
        _fail(f"list_events failed: {e}")
        return False

    # Create a test event (1 minute from now, then delete it)
    try:
        now = datetime.now()
        test_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        test_time = "23:58"  # late enough not to cause distraction
        event = await cal.create_event(
            title="[remy integration test — please delete]",
            date_str=test_date,
            time_str=test_time,
            description="Auto-created by test_google_integration.py — safe to delete",
        )
        event_id = event.get("id", "")
        link = event.get("htmlLink", "")
        _ok(f"Created test event (id: {event_id[:12]}…)")
        if link:
            _info(f"View at: {link}")

        # Delete the test event
        def _delete():
            from googleapiclient.discovery import build
            from remy.google.auth import get_credentials
            svc = build("calendar", "v3", credentials=get_credentials(TOKEN_FILE))
            svc.events().delete(calendarId="primary", eventId=event_id).execute()

        await asyncio.to_thread(_delete)
        _ok("Deleted test event (calendar is clean)")
    except Exception as e:
        _fail(f"create/delete event failed: {e}")
        return False

    return True


# ── gmail tests ───────────────────────────────────────────────────────────────


async def test_gmail() -> bool:
    _header("Gmail")

    from remy.google.gmail import GmailClient
    gmail = GmailClient(TOKEN_FILE)

    # Unread count
    try:
        count = await gmail.get_unread_count()
        _ok(f"Unread count: {count}")
    except Exception as e:
        _fail(f"get_unread_count failed: {e}")
        return False

    # Fetch email headers
    try:
        emails = await gmail.get_unread(limit=3)
        if emails:
            _ok(f"Fetched {len(emails)} unread email header(s):")
            for e in emails:
                print(f"       Subject : {e['subject'][:70]}")
                print(f"       From    : {e['from_addr'][:60]}")
                print(f"       Snippet : {e['snippet'][:80]}")
                print()
        else:
            _ok("Inbox is clear — no unread emails")
    except Exception as e:
        _fail(f"get_unread failed: {e}")
        return False

    # Promotional classification
    try:
        promos = await gmail.classify_promotional(limit=20)
        if promos:
            _ok(f"Classified {len(promos)} promotional email(s):")
            for p in promos[:3]:
                print(f"       {p['subject'][:70]}")
        else:
            _ok("No promotional emails detected (or inbox is clean)")
    except Exception as e:
        _fail(f"classify_promotional failed: {e}")
        return False

    return True


# ── docs tests ────────────────────────────────────────────────────────────────


async def test_docs() -> bool:
    _header("Google Docs")

    if not TEST_DOC_ID:
        _info("No GOOGLE_TEST_DOC_ID set — skipping Docs tests")
        _info("To test: export GOOGLE_TEST_DOC_ID=<doc-url-or-id> and re-run")
        return True

    from remy.google.docs import DocsClient
    docs = DocsClient(TOKEN_FILE)

    # Read document
    try:
        title, text = await docs.read_document(TEST_DOC_ID)
        _ok(f"Read document: '{title}' ({len(text)} chars)")
        if text.strip():
            preview = text.strip()[:200].replace("\n", " ")
            print(f"       Preview : {preview}…")
    except Exception as e:
        _fail(f"read_document failed: {e}")
        return False

    # Append text
    try:
        test_line = f"[remy integration test — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
        await docs.append_text(TEST_DOC_ID, test_line)
        _ok(f"Appended test line to document")
        _info(f"Appended: {test_line}")
    except Exception as e:
        _fail(f"append_text failed: {e}")
        return False

    return True


# ── web search (bonus) ────────────────────────────────────────────────────────


async def test_web_search() -> bool:
    _header("Web Search (bonus — no token needed)")

    from remy.web.search import web_search
    try:
        results = await web_search("python asyncio tutorial", max_results=3)
        if results:
            _ok(f"DuckDuckGo returned {len(results)} result(s):")
            for r in results[:2]:
                print(f"       {r.get('title','')[:70]}")
                print(f"       {r.get('href','')[:80]}")
        else:
            _fail("No results returned — duckduckgo-search may be rate-limited")
            return False
    except Exception as e:
        _fail(f"web_search failed: {e}")
        return False

    return True


# ── main ──────────────────────────────────────────────────────────────────────


async def main():
    print("\n🤖 remy Google Workspace Integration Test\n")

    if not check_setup():
        sys.exit(1)

    results = {}

    results["calendar"] = await test_calendar()
    results["gmail"]    = await test_gmail()
    results["docs"]     = await test_docs()
    results["search"]   = await test_web_search()

    _header("Summary")
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests passed. Google Workspace integration is ready.\n")
    else:
        print("Some tests failed. Check the output above for details.\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
