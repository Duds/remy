"""
Google Calendar API client.
Thin async wrapper around the synchronous google-api-python-client.
"""

from __future__ import annotations

import asyncio
import logging
import re

from datetime import date, datetime, timedelta, timezone

from .base import with_google_resilience

logger = logging.getLogger(__name__)

# Matches YYYY-MM-DD
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Matches HH:MM or HH:MM:SS
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def _parse_event_start(start: dict, today: date | None = None) -> str:
    """Return a human-readable time string from an event start dict.

    For timed events: "ddd dd MMM HH:MM" (e.g. "Mon 09 Mar 21:00") so the model
    and user see an unambiguous day. For all-day events: "dd MMM" (Australian
    style). For all-day events that started before `today`: "(ongoing)".
    """
    dt_str = start.get("dateTime")
    if dt_str:
        try:
            dt = datetime.fromisoformat(dt_str)
            return dt.strftime("%a %d %b %H:%M")
        except Exception:
            return dt_str
    # All-day event
    date_str = start.get("date", "")
    if today and date_str:
        try:
            event_date = date.fromisoformat(date_str)
            if event_date < today:
                return "(ongoing)"
            return event_date.strftime("%d %b")
        except ValueError:
            pass
    if date_str:
        try:
            event_date = date.fromisoformat(date_str)
            return event_date.strftime("%d %b")
        except ValueError:
            pass
    return date_str


class CalendarClient:
    """Wraps Google Calendar v3 API calls."""

    def __init__(self, token_file: str, timezone: str = "Australia/Sydney") -> None:
        self._token_file = token_file
        self._timezone = timezone

    def _service(self):
        from googleapiclient.discovery import build  # type: ignore[import]
        from .auth import get_credentials

        return build("calendar", "v3", credentials=get_credentials(self._token_file))

    async def list_events(self, days: int = 7, max_results: int = 20) -> list[dict]:
        """List upcoming events in the primary calendar for the next `days` days."""

        def _sync():
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days)
            result = (
                self._service()
                .events()
                .list(
                    calendarId="primary",
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return result.get("items", [])

        return await with_google_resilience(
            "calendar", lambda: asyncio.to_thread(_sync)
        )

    async def create_event(
        self,
        title: str,
        date_str: str,  # YYYY-MM-DD
        time_str: str,  # HH:MM
        duration_hours: float = 1.0,
        description: str = "",
    ) -> dict:
        """
        Create a calendar event.  date_str and time_str are combined to form
        the start datetime; end = start + duration_hours.
        Returns the created event dict from the API.
        """
        if not _DATE_RE.match(date_str):
            raise ValueError(f"Invalid date format '{date_str}' — expected YYYY-MM-DD")
        if not _TIME_RE.match(time_str):
            raise ValueError(f"Invalid time format '{time_str}' — expected HH:MM")

        start_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        end_dt = start_dt + timedelta(hours=duration_hours)
        tz = self._timezone

        def _sync():
            body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
            }
            return (
                self._service()
                .events()
                .insert(calendarId="primary", body=body)
                .execute()
            )

        return await with_google_resilience(
            "calendar", lambda: asyncio.to_thread(_sync)
        )

    def format_event(self, event: dict) -> str:
        """Return a single-line summary of a calendar event."""
        title = event.get("summary", "(no title)")
        today = datetime.now(timezone.utc).date()
        start = _parse_event_start(event.get("start", {}), today=today)
        location = event.get("location", "")
        loc_suffix = f" @ {location}" if location else ""
        return f"• {start} — {title}{loc_suffix}"
