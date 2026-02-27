"""
Tests for the Google Workspace integration package (Calendar, Gmail, Docs, Contacts).
All Google API calls are mocked — no network access required.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── auth ──────────────────────────────────────────────────────────────────────


def test_is_configured_missing_token(tmp_path):
    from remy.google.auth import is_configured

    missing = str(tmp_path / "nope.json")
    # ADC may be configured on this machine — mock it out so we test the
    # "no token file, no ADC" code path cleanly.
    with patch("remy.google.auth._try_adc", side_effect=Exception("no ADC")):
        result = is_configured(missing)
    assert result is False


def test_is_configured_with_valid_token(tmp_path):
    pytest.importorskip("google.oauth2.credentials", reason="google-auth not installed")
    from remy.google.auth import is_configured

    token_file = str(tmp_path / "token.json")
    fake_creds = MagicMock()
    fake_creds.expired = False

    with patch("google.oauth2.credentials.Credentials") as MockCreds:
        MockCreds.from_authorized_user_file.return_value = fake_creds
        Path(token_file).write_text("{}")
        result = is_configured(token_file)

    assert result is True


# ── docs helpers ──────────────────────────────────────────────────────────────


def test_extract_doc_id_from_url():
    from remy.google.docs import extract_doc_id

    url = "https://docs.google.com/document/d/abc123XYZ/edit"
    assert extract_doc_id(url) == "abc123XYZ"


def test_extract_doc_id_passthrough():
    from remy.google.docs import extract_doc_id

    assert extract_doc_id("abc123XYZ") == "abc123XYZ"


def test_extract_text_from_doc():
    from remy.google.docs import _extract_text

    doc = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "Hello, "}},
                            {"textRun": {"content": "World!"}},
                        ]
                    }
                }
            ]
        }
    }
    assert _extract_text(doc) == "Hello, World!"


def test_extract_text_empty_doc():
    from remy.google.docs import _extract_text

    assert _extract_text({}) == ""


# ── calendar helpers ──────────────────────────────────────────────────────────


def test_format_event_with_time():
    from remy.google.calendar import CalendarClient

    client = CalendarClient.__new__(CalendarClient)
    event = {
        "summary": "Team standup",
        "start": {"dateTime": "2026-03-01T09:00:00+11:00"},
    }
    result = client.format_event(event)
    assert "09:00" in result
    assert "Team standup" in result


def test_format_event_all_day():
    from remy.google.calendar import CalendarClient

    client = CalendarClient.__new__(CalendarClient)
    event = {
        "summary": "Public Holiday",
        "start": {"date": "2026-03-01"},
    }
    result = client.format_event(event)
    assert "2026-03-01" in result
    assert "Public Holiday" in result


def test_format_event_with_location():
    from remy.google.calendar import CalendarClient

    client = CalendarClient.__new__(CalendarClient)
    event = {
        "summary": "Dentist",
        "start": {"dateTime": "2026-03-01T14:00:00+11:00"},
        "location": "123 Main St",
    }
    result = client.format_event(event)
    assert "@ 123 Main St" in result


# ── calendar create_event validation ─────────────────────────────────────────


def test_create_event_bad_date():
    from remy.google.calendar import CalendarClient

    client = CalendarClient("dummy.json")
    with pytest.raises(ValueError, match="Invalid date format"):
        asyncio.run(client.create_event("Meeting", "01-03-2026", "09:00"))


def test_create_event_bad_time():
    from remy.google.calendar import CalendarClient

    client = CalendarClient("dummy.json")
    with pytest.raises(ValueError, match="Invalid time format"):
        asyncio.run(client.create_event("Meeting", "2026-03-01", "9am"))


# ── gmail classification ──────────────────────────────────────────────────────


def test_gmail_is_promotional():
    from remy.google.gmail import _is_promotional

    promo = {
        "subject": "SALE: 50% off this weekend only!",
        "snippet": "Click here to unsubscribe",
        "from_addr": "deals@shop.com",
    }
    assert _is_promotional(promo) is True


def test_gmail_not_promotional():
    from remy.google.gmail import _is_promotional

    normal = {
        "subject": "Re: Project update",
        "snippet": "Here are the notes from today's meeting.",
        "from_addr": "colleague@company.com",
    }
    assert _is_promotional(normal) is False


# ── handler smoke tests ───────────────────────────────────────────────────────


class DummyMessage:
    def __init__(self):
        self.last_text = None
        self.chat = self

    async def reply_text(self, text, parse_mode=None):
        self.last_text = text
        return self


def make_update(user_id=12345):
    class User:
        id = user_id
        username = None
        first_name = None
        last_name = None

    class Update:
        effective_user = User()
        message = DummyMessage()
        effective_chat = User()

    return Update()


def make_context(args=None):
    class Context:
        def __init__(self, a):
            self.args = a or []

    return Context(args)


def test_calendar_not_configured():
    """When google_calendar is None, command returns helpful error."""
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(
        session_manager=None,
        router=None,
        conv_store=None,
        google_calendar=None,
    )
    update = make_update()
    asyncio.run(handlers["calendar"](update, make_context()))
    assert "not configured" in update.message.last_text.lower()


def test_gmail_not_configured():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(
        session_manager=None,
        router=None,
        conv_store=None,
        google_gmail=None,
    )
    update = make_update()
    asyncio.run(handlers["gmail-unread"](update, make_context()))
    assert "not configured" in update.message.last_text.lower()


def test_gdoc_not_configured():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(
        session_manager=None,
        router=None,
        conv_store=None,
        google_docs=None,
    )
    update = make_update()
    asyncio.run(handlers["gdoc"](update, make_context()))
    assert "not configured" in update.message.last_text.lower()


def test_schedule_missing_args():
    from remy.bot.handlers import make_handlers

    mock_cal = MagicMock()
    handlers = make_handlers(
        session_manager=None,
        router=None,
        conv_store=None,
        google_calendar=mock_cal,
    )
    update = make_update()
    # Too few args
    asyncio.run(handlers["schedule"](update, make_context(["Meeting"])))
    assert "Usage:" in update.message.last_text


def test_calendar_command_with_mock():
    """calendar command calls google_calendar.list_events and formats results."""
    from remy.bot.handlers import make_handlers

    mock_cal = MagicMock()
    mock_cal.list_events = AsyncMock(return_value=[
        {
            "summary": "Stand-up",
            "start": {"dateTime": "2026-03-01T09:00:00+11:00"},
        }
    ])
    mock_cal.format_event = MagicMock(return_value="• 09:00 — Stand-up")

    handlers = make_handlers(
        session_manager=None,
        router=None,
        conv_store=None,
        google_calendar=mock_cal,
    )
    update = make_update()
    asyncio.run(handlers["calendar"](update, make_context()))
    assert "Stand-up" in update.message.last_text


def test_gmail_unread_summary_mock():
    from remy.bot.handlers import make_handlers

    mock_gmail = MagicMock()
    mock_gmail.get_unread_summary = AsyncMock(return_value={
        "count": 3,
        "senders": ["alice@example.com", "bob@example.com"],
    })

    handlers = make_handlers(
        session_manager=None,
        router=None,
        conv_store=None,
        google_gmail=mock_gmail,
    )
    update = make_update()
    asyncio.run(handlers["gmail-unread-summary"](update, make_context()))
    assert "3" in update.message.last_text
    assert "alice" in update.message.last_text


# ── contacts helpers ──────────────────────────────────────────────────────────


def _make_person(name="Jane Doe", email="jane@example.com", phone="+61400000000", bday=None):
    """Create a minimal People API person dict for testing."""
    p = {
        "resourceName": "people/c123",
        "names": [{"displayName": name}],
        "emailAddresses": [{"value": email}] if email else [],
        "phoneNumbers": [{"value": phone}] if phone else [],
    }
    if bday:
        month, day = bday
        p["birthdays"] = [{"date": {"month": month, "day": day, "year": 0}}]
    return p


def test_extract_name():
    from remy.google.contacts import _extract_name

    assert _extract_name(_make_person("Alice")) == "Alice"
    assert _extract_name({}) == ""


def test_extract_emails():
    from remy.google.contacts import _extract_emails

    assert _extract_emails(_make_person(email="a@b.com")) == ["a@b.com"]
    assert _extract_emails(_make_person(email="")) == []


def test_extract_birthday_with_date():
    from remy.google.contacts import _extract_birthday
    from datetime import date

    person = _make_person(bday=(3, 15))
    bday = _extract_birthday(person)
    assert bday is not None
    assert bday.month == 3
    assert bday.day == 15


def test_extract_birthday_missing():
    from remy.google.contacts import _extract_birthday

    assert _extract_birthday(_make_person()) is None


def test_format_contact_basic():
    from remy.google.contacts import format_contact

    person = _make_person("Bob Smith", email="bob@example.com", phone="+61400111222")
    result = format_contact(person)
    assert "Bob Smith" in result
    assert "bob@example.com" in result
    assert "+61400111222" in result


def test_format_contact_verbose_with_birthday():
    from remy.google.contacts import format_contact

    person = _make_person("Alice", bday=(7, 4))
    person["biographies"] = [{"value": "Old friend from uni"}]
    result = format_contact(person, verbose=True)
    assert "Alice" in result
    assert "04 Jul" in result
    assert "Old friend from uni" in result


def test_get_sparse_contacts_filters_correctly():
    """get_sparse_contacts returns only contacts missing BOTH email and phone."""
    from remy.google.contacts import ContactsClient

    client = ContactsClient("dummy.json")
    contacts = [
        _make_person("Has email", email="a@b.com", phone=""),
        _make_person("Has phone", email="", phone="+61400000001"),
        _make_person("Has both", email="x@y.com", phone="+61400000002"),
        _make_person("Has neither", email="", phone=""),
    ]
    client.list_contacts = AsyncMock(return_value=contacts)
    sparse = asyncio.run(client.get_sparse_contacts())
    assert len(sparse) == 1
    from remy.google.contacts import _extract_name
    assert _extract_name(sparse[0]) == "Has neither"


def test_get_upcoming_birthdays_today_within_window():
    """Contact with birthday today appears in get_upcoming_birthdays(days=7)."""
    from remy.google.contacts import ContactsClient
    from datetime import date

    today = date.today()
    person = _make_person("Birthday Person", bday=(today.month, today.day))
    client = ContactsClient("dummy.json")
    client.list_contacts = AsyncMock(return_value=[person])
    results = asyncio.run(client.get_upcoming_birthdays(days=7))
    assert len(results) == 1
    assert results[0][1] is person


def test_get_upcoming_birthdays_outside_window():
    """Contact with birthday far away does not appear."""
    from remy.google.contacts import ContactsClient
    from datetime import date, timedelta

    far = date.today() + timedelta(days=60)
    person = _make_person("Future Person", bday=(far.month, far.day))
    client = ContactsClient("dummy.json")
    client.list_contacts = AsyncMock(return_value=[person])
    results = asyncio.run(client.get_upcoming_birthdays(days=7))
    assert results == []


# ── contacts handler smoke tests ─────────────────────────────────────────────


def test_contacts_not_configured():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, google_contacts=None
    )
    update = make_update()
    asyncio.run(handlers["contacts"](update, make_context()))
    assert "not configured" in update.message.last_text.lower()


def test_contacts_search_with_results():
    from remy.bot.handlers import make_handlers

    mock_contacts = MagicMock()
    mock_contacts.search_contacts = AsyncMock(return_value=[
        _make_person("Jane Doe", email="jane@example.com")
    ])
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, google_contacts=mock_contacts
    )
    update = make_update()
    asyncio.run(handlers["contacts"](update, make_context(["Jane"])))
    assert "Jane Doe" in update.message.last_text


def test_contacts_birthday_no_upcoming():
    from remy.bot.handlers import make_handlers

    mock_contacts = MagicMock()
    mock_contacts.get_upcoming_birthdays = AsyncMock(return_value=[])
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, google_contacts=mock_contacts
    )
    update = make_update()
    asyncio.run(handlers["contacts-birthday"](update, make_context()))
    assert "No birthdays" in update.message.last_text


def test_contacts_prune_none_sparse():
    from remy.bot.handlers import make_handlers

    mock_contacts = MagicMock()
    mock_contacts.get_sparse_contacts = AsyncMock(return_value=[])
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, google_contacts=mock_contacts
    )
    update = make_update()
    asyncio.run(handlers["contacts-prune"](update, make_context()))
    assert "All contacts" in update.message.last_text


def test_contacts_note_no_args():
    from remy.bot.handlers import make_handlers

    mock_contacts = MagicMock()
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, google_contacts=mock_contacts
    )
    update = make_update()
    asyncio.run(handlers["contacts-note"](update, make_context()))
    assert "Usage:" in update.message.last_text
