# User Story: Gmail Label/Folder Search

## Summary
As a user, I want Remy to be able to search emails across all Gmail labels and folders —
not just the default inbox view — so that I can find messages from Promotions, All Mail,
or custom labels without having to switch to Gmail manually.

---

## Background

`GmailClient.search_emails()` in `remy/google/gmail_client.py` currently uses the Gmail
API without specifying a `labelIds` filter, which defaults to `INBOX` only. Emails in
Promotions, Updates, Forums, or custom labels are invisible to Remy even when they are
technically unread or match the search query.

The Gmail API supports filtering by label via the `labelIds` parameter on the
`messages.list` endpoint. Supporting this would allow natural-language queries like
"search all my mail for emails from Kathryn about hockey".

---

## Acceptance Criteria

1. **Optional `labels` parameter on `search_gmail` tool.** Accepts a list of label
   identifiers, e.g. `["INBOX", "PROMOTIONS", "ALL_MAIL"]`. Defaults to `["INBOX"]`
   for backwards-compatible behaviour.
2. **Standard system labels supported:** `INBOX`, `ALL_MAIL`, `PROMOTIONS`, `UPDATES`,
   `FORUMS`, `SENT`, `TRASH`.
3. **Custom label names resolved to IDs.** If the user names a custom label (e.g.
   `"Hockey"`), `GmailClient` fetches the label list and resolves the name to its ID
   before querying. Returns a helpful error if the label is not found.
4. **Natural language works.** Claude can infer the right label from context without the
   user needing to know Gmail's internal label identifiers.
5. **Unread count tool (`gmail_unread_summary`) also optionally queries beyond INBOX.**
6. **No regression:** existing `/gmail-unread` and `/gmail-classify` behaviour is unchanged
   when `labels` is omitted.

---

## Implementation

**Files:** `remy/google/gmail_client.py`, `remy/ai/tool_registry.py`

### 1. `GmailClient` changes

```python
async def search_emails(
    self,
    query: str,
    max_results: int = 10,
    label_ids: list[str] | None = None,  # NEW
) -> list[dict]:
    params = {"q": query, "maxResults": max_results}
    if label_ids:
        params["labelIds"] = label_ids  # Gmail API accepts repeated param
    ...
```

Add a helper:

```python
async def resolve_label_ids(self, names: list[str]) -> list[str]:
    """Convert human-readable label names to Gmail label IDs."""
    ...
```

### 2. `tool_registry.py` schema update

Add `labels` (optional array of strings) to the `search_gmail` tool schema with a
description explaining the supported values and the default behaviour.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `/gmail-unread` (no labels arg) | Searches INBOX only (no regression) |
| "search all my mail for emails from Kathryn" | `ALL_MAIL` label used |
| "any promotions emails about Apple?" | `PROMOTIONS` label used |
| Unknown label name "Nonexistent" | Clear error: "Label 'Nonexistent' not found" |
| Multi-label: `["INBOX", "UPDATES"]` | Results merged and de-duped by message ID |

---

## Out of Scope

- Sending or moving emails between labels (separate story)
- Creating labels (already implemented via `create_gmail_label` tool)
- Pagination beyond `max_results`
