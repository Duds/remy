"""
Google People API (Contacts) client.
Thin async wrapper around the synchronous google-api-python-client.

Scope required: https://www.googleapis.com/auth/contacts
"""

import asyncio
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Fields to request on every person fetch
_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,birthdays,biographies,"
    "organizations,addresses,metadata"
)

# Minimal fields for list operations (faster)
_LIST_FIELDS = "names,emailAddresses,phoneNumbers,birthdays,metadata"


def _extract_name(person: dict) -> str:
    names = person.get("names", [])
    if names:
        return names[0].get("displayName", "")
    return ""


def _extract_emails(person: dict) -> list[str]:
    return [e.get("value", "") for e in person.get("emailAddresses", []) if e.get("value")]


def _extract_phones(person: dict) -> list[str]:
    return [p.get("value", "") for p in person.get("phoneNumbers", []) if p.get("value")]


def _extract_birthday(person: dict) -> date | None:
    """Return the contact's birthday as a date (year may be 0 = unknown)."""
    for bday in person.get("birthdays", []):
        d = bday.get("date", {})
        month = d.get("month")
        day = d.get("day")
        if month and day:
            year = d.get("year") or 1900
            try:
                return date(year, month, day)
            except ValueError:
                pass
    return None


def format_contact(person: dict, verbose: bool = False) -> str:
    """Return a formatted string summary of a contact."""
    name = _extract_name(person) or "(no name)"
    emails = _extract_emails(person)
    phones = _extract_phones(person)

    lines = [f"*{name}*"]
    if emails:
        lines.append("  📧 " + " | ".join(emails[:3]))
    if phones:
        lines.append("  📞 " + " | ".join(phones[:3]))

    if verbose:
        bday = _extract_birthday(person)
        if bday:
            yr = f" {bday.year}" if bday.year != 1900 else ""
            lines.append(f"  🎂 {bday.strftime('%d %b')}{yr}")
        for org in person.get("organizations", [])[:1]:
            org_name = org.get("name", "")
            title = org.get("title", "")
            if org_name or title:
                lines.append(f"  🏢 {title}{' @ ' + org_name if org_name else ''}")
        for bio in person.get("biographies", [])[:1]:
            text = (bio.get("value") or "").strip()
            if text:
                lines.append(f"  📝 {text[:200]}")

    return "\n".join(lines)


class ContactsClient:
    """Wraps Google People API v1 calls for contact management."""

    def __init__(self, token_file: str) -> None:
        self._token_file = token_file

    def _service(self):
        from googleapiclient.discovery import build  # type: ignore[import]
        from .auth import get_credentials
        return build("people", "v1", credentials=get_credentials(self._token_file))

    async def list_contacts(self, max_results: int = 100) -> list[dict]:
        """
        Return up to max_results contacts with basic fields.
        Each entry is a raw People API person dict.
        """
        def _sync() -> list[dict]:
            svc = self._service()
            results: list[dict] = []
            page_token = None
            while len(results) < max_results:
                kwargs: dict = dict(
                    resourceName="people/me",
                    pageSize=min(100, max_results - len(results)),
                    personFields=_LIST_FIELDS,
                    sortOrder="LAST_NAME_ASCENDING",
                )
                if page_token:
                    kwargs["pageToken"] = page_token
                resp = svc.people().connections().list(**kwargs).execute()
                results.extend(resp.get("connections", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            return results

        return await asyncio.to_thread(_sync)

    async def search_contacts(self, query: str, max_results: int = 10) -> list[dict]:
        """Search contacts by name or email. Returns matching person dicts."""
        def _sync() -> list[dict]:
            svc = self._service()
            resp = svc.people().searchContacts(
                query=query,
                pageSize=max_results,
                readMask=_LIST_FIELDS,
            ).execute()
            return [r.get("person", {}) for r in resp.get("results", [])]

        return await asyncio.to_thread(_sync)

    async def get_contact(self, resource_name: str) -> dict:
        """Fetch full details for a contact by resourceName (e.g. 'people/c123')."""
        def _sync() -> dict:
            return self._service().people().get(
                resourceName=resource_name,
                personFields=_PERSON_FIELDS,
            ).execute()

        return await asyncio.to_thread(_sync)

    async def get_upcoming_birthdays(self, days: int = 14) -> list[tuple[date, dict]]:
        """
        Return (next_occurrence, person) tuples for contacts with birthdays
        within the next `days` days, sorted by date.
        """
        contacts = await self.list_contacts(max_results=500)
        today = date.today()
        cutoff = today + timedelta(days=days)
        results: list[tuple[date, dict]] = []

        for person in contacts:
            bday = _extract_birthday(person)
            if bday is None:
                continue
            # Find the next occurrence this year or next
            for year_offset in (0, 1):
                try:
                    occurrence = date(today.year + year_offset, bday.month, bday.day)
                except ValueError:
                    continue  # invalid date like Feb 29 in non-leap year
                if today <= occurrence <= cutoff:
                    results.append((occurrence, person))
                    break

        results.sort(key=lambda t: t[0])
        return results

    async def update_note(self, resource_name: str, note: str) -> dict:
        """
        Set/replace the biography (notes) field on a contact.
        Returns the updated person dict.
        """
        def _sync() -> dict:
            svc = self._service()
            # Fetch current etag (required for updates)
            current = svc.people().get(
                resourceName=resource_name,
                personFields="biographies,metadata",
            ).execute()
            etag = current.get("etag", "")
            body = {
                "etag": etag,
                "biographies": [{"value": note, "contentType": "TEXT_PLAIN"}],
            }
            return svc.people().updateContact(
                resourceName=resource_name,
                updatePersonFields="biographies",
                body=body,
            ).execute()

        return await asyncio.to_thread(_sync)

    async def delete_contact(self, resource_name: str) -> None:
        """Permanently delete a contact by resourceName."""
        def _sync() -> None:
            self._service().people().deleteContact(
                resourceName=resource_name,
            ).execute()

        await asyncio.to_thread(_sync)

    async def get_sparse_contacts(self, max_results: int = 200) -> list[dict]:
        """
        Return contacts that are 'sparse' — missing both email AND phone.
        Useful for pruning contacts with no useful data.
        """
        contacts = await self.list_contacts(max_results=max_results)
        sparse = []
        for person in contacts:
            has_email = bool(_extract_emails(person))
            has_phone = bool(_extract_phones(person))
            if not has_email and not has_phone:
                sparse.append(person)
        return sparse
