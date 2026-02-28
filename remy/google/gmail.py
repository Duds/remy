"""
Gmail API client — read, search, label, and organise emails.

Security notes:
- Email bodies are untrusted content and must be sanitised before being
  shown to Claude or the user.
- Body extraction is limited to _BODY_MAX_CHARS to avoid context stuffing.
- Callers are responsible for applying sanitize_memory_injection() to any
  content that will be passed back to an LLM.
"""

import asyncio
import base64
import logging

logger = logging.getLogger(__name__)

_BODY_MAX_CHARS = 3000  # truncation limit for email bodies

# Maps human-readable label names → Gmail API label IDs.
# None means "no labelIds filter" (i.e. search all mail).
_SYSTEM_LABELS: dict[str, str | None] = {
    "INBOX":      "INBOX",
    "ALL_MAIL":   None,
    "SENT":       "SENT",
    "TRASH":      "TRASH",
    "SPAM":       "SPAM",
    "PROMOTIONS": "CATEGORY_PROMOTIONS",
    "UPDATES":    "CATEGORY_UPDATES",
    "FORUMS":     "CATEGORY_FORUMS",
    "SOCIAL":     "CATEGORY_SOCIAL",
    "PERSONAL":   "CATEGORY_PERSONAL",
}

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


def _extract_body(msg: dict, max_chars: int = _BODY_MAX_CHARS) -> str:
    """
    Extract plain-text body from a Gmail full-format message.
    Falls back to the snippet if no plain-text part is found.
    """
    def _get_plain(part: dict) -> str:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                try:
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                except Exception:
                    pass
        # Recurse into multipart
        for subpart in part.get("parts", []):
            result = _get_plain(subpart)
            if result:
                return result
        return ""

    text = _get_plain(msg.get("payload", {}))
    if not text:
        text = msg.get("snippet", "")
    return text[:max_chars]


def _parse_headers(msg: dict) -> dict:
    """Return a dict of {header_name: value} from a Gmail message."""
    return {
        h["name"]: h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }


class GmailClient:
    """Wraps Gmail API v1 calls."""

    def __init__(self, token_file: str) -> None:
        self._token_file = token_file

    def _service(self):
        from googleapiclient.discovery import build  # type: ignore[import]
        from .auth import get_credentials
        return build("gmail", "v1", credentials=get_credentials(self._token_file))

    # ------------------------------------------------------------------
    # Read / search
    # ------------------------------------------------------------------

    async def get_unread(self, limit: int = 5) -> list[dict]:
        """
        Return up to `limit` unread inbox email summaries (metadata only).
        Each dict has: id, from_addr, subject, date, snippet, labels.
        """
        return await self.search("is:unread in:inbox", max_results=limit)

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

    async def resolve_label_ids(self, names: list[str]) -> list[str | None]:
        """
        Resolve human-readable label names to Gmail API label IDs.

        System labels (INBOX, PROMOTIONS, UPDATES, etc.) are resolved via the
        built-in _SYSTEM_LABELS map.  Custom label names are looked up via the
        Labels API (case-insensitive match on label name).

        ALL_MAIL resolves to None — the caller should treat a None entry as
        "no labelIds filter", i.e. search across all mail.

        Raises ValueError if a custom label name is not found.
        """
        resolved: list[str | None] = []
        custom_names: list[str] = []

        for name in names:
            upper = name.upper()
            if upper in _SYSTEM_LABELS:
                resolved.append(_SYSTEM_LABELS[upper])
            else:
                custom_names.append(name)

        if custom_names:
            all_labels = await self.list_labels()
            label_map = {lbl["name"].lower(): lbl["id"] for lbl in all_labels}
            for name in custom_names:
                lid = label_map.get(name.lower())
                if lid is None:
                    raise ValueError(f"Label '{name}' not found in Gmail.")
                resolved.append(lid)

        return resolved

    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_body: bool = False,
        label_ids: list[str | None] | None = None,
    ) -> list[dict]:
        """
        Search Gmail using standard Gmail query syntax (e.g. "from:kate@example.com
        subject:hockey"). Returns up to max_results message summaries.

        label_ids: resolved label IDs from resolve_label_ids().  None in the list
            (or the parameter being None) means no labelIds filter — search all mail.
            Multiple non-None IDs are queried separately and results are merged
            (OR semantics), de-duplicated by message ID.

        If include_body=True, fetches the full plain-text body (truncated to
        _BODY_MAX_CHARS). Use sparingly — one API call per message.
        """
        max_results = min(max_results, 20)

        # If ANY entry is None (ALL_MAIL) or the param is absent, do a single
        # unfiltered call.  Otherwise query each label separately for OR semantics.
        if label_ids is None or None in label_ids:
            filter_labels: list[str | None] = [None]
        else:
            filter_labels = label_ids if label_ids else [None]

        def _sync():
            svc = self._service()
            seen: set[str] = set()
            results: list[dict] = []

            for label_filter in filter_labels:
                remaining = max_results - len(results)
                if remaining <= 0:
                    break
                params: dict = {"userId": "me", "q": query, "maxResults": remaining}
                if label_filter is not None:
                    params["labelIds"] = [label_filter]
                resp = svc.users().messages().list(**params).execute()
                for item in resp.get("messages", []):
                    if item["id"] in seen:
                        continue
                    seen.add(item["id"])
                    fmt = "full" if include_body else "metadata"
                    msg = svc.users().messages().get(
                        userId="me",
                        id=item["id"],
                        format=fmt,
                        **({"metadataHeaders": ["From", "To", "Subject", "Date"]}
                           if not include_body else {}),
                    ).execute()
                    headers = _parse_headers(msg)
                    entry = {
                        "id": item["id"],
                        "from_addr": headers.get("From", ""),
                        "to": headers.get("To", ""),
                        "subject": headers.get("Subject", "(no subject)"),
                        "date": headers.get("Date", ""),
                        "snippet": msg.get("snippet", ""),
                        "labels": msg.get("labelIds", []),
                    }
                    if include_body:
                        entry["body"] = _extract_body(msg)
                    results.append(entry)

            return results

        return await asyncio.to_thread(_sync)

    async def get_message(self, message_id: str, include_body: bool = True) -> dict:
        """
        Fetch a single email by ID.
        Returns full metadata plus plain-text body (if include_body=True).
        """
        def _sync():
            svc = self._service()
            fmt = "full" if include_body else "metadata"
            msg = svc.users().messages().get(
                userId="me",
                id=message_id,
                format=fmt,
            ).execute()
            headers = _parse_headers(msg)
            entry = {
                "id": message_id,
                "from_addr": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
                "labels": msg.get("labelIds", []),
            }
            if include_body:
                entry["body"] = _extract_body(msg)
            return entry

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    async def list_labels(self) -> list[dict]:
        """Return all Gmail labels (system + user-created)."""
        def _sync():
            result = self._service().users().labels().list(userId="me").execute()
            return [
                {"id": lbl["id"], "name": lbl["name"], "type": lbl.get("type", "user")}
                for lbl in result.get("labels", [])
            ]
        return await asyncio.to_thread(_sync)

    async def create_label(
        self,
        name: str,
        label_list_visibility: str = "labelShow",
        message_list_visibility: str = "show",
    ) -> dict:
        """
        Create a new Gmail label.
        Returns {'id': label_id, 'name': label_name}.

        Use slash notation for nesting, e.g. 'Personal/Hockey' creates a
        'Hockey' label nested under an existing 'Personal' parent label.
        """
        def _sync():
            svc = self._service()
            body = {
                "name": name,
                "labelListVisibility": label_list_visibility,
                "messageListVisibility": message_list_visibility,
            }
            result = svc.users().labels().create(userId="me", body=body).execute()
            return {"id": result["id"], "name": result["name"]}

        return await asyncio.to_thread(_sync)

    async def modify_labels(
        self,
        message_ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> int:
        """Add/remove labels from messages. Returns count modified."""
        body: dict = {}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids
        if not body:
            return 0

        def _sync():
            svc = self._service()
            for mid in message_ids:
                svc.users().messages().modify(
                    userId="me", id=mid, body=body
                ).execute()
            return len(message_ids)

        return await asyncio.to_thread(_sync)

    async def mark_read(self, message_ids: list[str]) -> int:
        """Mark messages as read."""
        return await self.modify_labels(message_ids, remove_label_ids=["UNREAD"])

    async def mark_unread(self, message_ids: list[str]) -> int:
        """Mark messages as unread."""
        return await self.modify_labels(message_ids, add_label_ids=["UNREAD"])

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    async def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
    ) -> dict:
        """
        Save a new draft to Gmail Drafts folder.
        Returns {'id': draft_id, 'message_id': message_id}.
        """
        from email.mime.text import MIMEText

        def _sync():
            msg = MIMEText(body, "plain", "utf-8")
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            svc = self._service()
            draft = svc.users().drafts().create(
                userId="me",
                body={"message": {"raw": raw}},
            ).execute()
            return {
                "id": draft["id"],
                "message_id": draft.get("message", {}).get("id", ""),
            }

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    # Classify / archive (existing)
    # ------------------------------------------------------------------

    async def classify_promotional(self, limit: int = 20) -> list[dict]:
        """Return emails from unread inbox that look promotional."""
        emails = await self.get_unread(limit=limit)
        return [e for e in emails if _is_promotional(e)]

    async def archive_messages(self, message_ids: list[str]) -> int:
        """Remove INBOX label from message_ids. Returns count archived."""
        return await self.modify_labels(message_ids, remove_label_ids=["INBOX"])
