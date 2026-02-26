"""
Gmail API client — lightweight read access with promotional email classification.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Keywords that suggest a promotional / newsletter email
_PROMO_KEYWORDS = frozenset({
    "unsubscribe", "newsletter", "marketing", "promotion", "sale", "deal",
    "offer", "discount", "coupon", "% off", "free shipping", "limited time",
    "act now", "special offer", "click here", "opt out",
})


def _is_promotional(email: dict) -> bool:
    """Heuristic: check subject + snippet for promotional keywords."""
    text = (
        email.get("subject", "") + " " +
        email.get("snippet", "") + " " +
        email.get("from_addr", "")
    ).lower()
    return any(kw in text for kw in _PROMO_KEYWORDS)


class GmailClient:
    """Wraps Gmail API v1 calls."""

    def __init__(self, token_file: str) -> None:
        self._token_file = token_file

    def _service(self):
        from googleapiclient.discovery import build  # type: ignore[import]
        from .auth import get_credentials
        return build("gmail", "v1", credentials=get_credentials(self._token_file))

    async def get_unread(self, limit: int = 5) -> list[dict]:
        """
        Return up to `limit` unread inbox email summaries (metadata only — fast).
        Each dict has: id, from_addr, subject, date, snippet.
        """
        def _sync():
            svc = self._service()
            msgs = svc.users().messages().list(
                userId="me",
                q="is:unread in:inbox",
                maxResults=limit,
            ).execute()
            items = msgs.get("messages", [])
            results = []
            for item in items:
                msg = svc.users().messages().get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                results.append({
                    "id": item["id"],
                    "from_addr": headers.get("From", ""),
                    "subject":   headers.get("Subject", "(no subject)"),
                    "date":      headers.get("Date", ""),
                    "snippet":   msg.get("snippet", ""),
                })
            return results
        return await asyncio.to_thread(_sync)

    async def get_unread_count(self) -> int:
        """Return total unread count in inbox."""
        def _sync():
            result = self._service().users().labels().get(
                userId="me", id="INBOX"
            ).execute()
            return result.get("messagesUnread", 0)
        return await asyncio.to_thread(_sync)

    async def get_unread_summary(self) -> dict:
        """Return {count, senders} for unread inbox."""
        count = await self.get_unread_count()
        if count == 0:
            return {"count": 0, "senders": []}
        emails = await self.get_unread(limit=min(count, 20))
        senders = list({e["from_addr"] for e in emails})[:10]
        return {"count": count, "senders": senders}

    async def classify_promotional(self, limit: int = 20) -> list[dict]:
        """Return emails from unread inbox that look promotional."""
        emails = await self.get_unread(limit=limit)
        return [e for e in emails if _is_promotional(e)]

    async def archive_messages(self, message_ids: list[str]) -> int:
        """Remove INBOX label from message_ids. Returns count archived."""
        def _sync():
            svc = self._service()
            for mid in message_ids:
                svc.users().messages().modify(
                    userId="me",
                    id=mid,
                    body={"removeLabelIds": ["INBOX"]},
                ).execute()
            return len(message_ids)
        return await asyncio.to_thread(_sync)
