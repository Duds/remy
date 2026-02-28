"""
Google Docs API client — minimal read and append.
"""

import asyncio
import logging
import re

from .base import with_google_resilience

logger = logging.getLogger(__name__)

_DOC_URL_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")


def extract_doc_id(id_or_url: str) -> str:
    """Return the document ID from a URL, or the string as-is if it's already an ID."""
    m = _DOC_URL_RE.search(id_or_url)
    return m.group(1) if m else id_or_url


def _extract_text(doc: dict) -> str:
    """Extract plain text from a Docs API document response."""
    parts = []
    for elem in doc.get("body", {}).get("content", []):
        paragraph = elem.get("paragraph")
        if paragraph:
            for pe in paragraph.get("elements", []):
                tr = pe.get("textRun")
                if tr:
                    parts.append(tr.get("content", ""))
    return "".join(parts)


class DocsClient:
    """Wraps Google Docs v1 API calls."""

    def __init__(self, token_file: str) -> None:
        self._token_file = token_file

    def _service(self):
        from googleapiclient.discovery import build  # type: ignore[import]
        from .auth import get_credentials
        return build("docs", "v1", credentials=get_credentials(self._token_file))

    async def read_document(self, id_or_url: str) -> tuple[str, str]:
        """
        Fetch and return (doc_title, plain_text) for a Google Doc.
        Raises on auth or API errors.
        """
        doc_id = extract_doc_id(id_or_url)

        def _sync():
            doc = self._service().documents().get(documentId=doc_id).execute()
            title = doc.get("title", "(untitled)")
            text = _extract_text(doc)
            return title, text

        return await with_google_resilience("docs", lambda: asyncio.to_thread(_sync))

    async def append_text(self, id_or_url: str, text: str) -> None:
        """
        Append `text` at the end of the document body (before the final newline).
        """
        doc_id = extract_doc_id(id_or_url)

        def _sync():
            svc = self._service()
            doc = svc.documents().get(documentId=doc_id).execute()
            # Find the end index of the body (last element's endIndex - 1 for the newline)
            content = doc.get("body", {}).get("content", [])
            end_index = 1
            for elem in content:
                ei = elem.get("endIndex")
                if ei:
                    end_index = ei
            # Insert before the trailing newline that Docs always maintains
            svc.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{
                    "insertText": {
                        "location": {"index": end_index - 1},
                        "text": "\n" + text,
                    }
                }]},
            ).execute()

        await with_google_resilience("docs", lambda: asyncio.to_thread(_sync))
