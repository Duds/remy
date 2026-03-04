# User Story: Bookmarks with Tag Buttons

**Status:** ⬜ Backlog

## Summary
As a user, I want to assign a tag when saving a bookmark (e.g. [Preferences] [Work] [Personal]) via quick buttons so that I can organise and filter bookmarks without typing.

---

## Background

**Tier 3 — Nice to have.** Bookmarks are saved via `save_bookmark` (and `/save-url`) and stored as facts with `metadata.category = "bookmark"` in the knowledge store (`remy/ai/tools/bookmarks.py`, `remy/memory/knowledge.py`). There is no tag or sub-category today; the only dimension is the free-form note. Adding optional tags (e.g. Preferences, Work, Personal) at save time would improve findability and align with how users think about bookmarks.

Relevant code: `remy/ai/tools/bookmarks.py` (`exec_save_bookmark`, `exec_list_bookmarks`), `remy/ai/tools/schemas.py` (save_bookmark schema), knowledge table and `FACT_CATEGORIES` / metadata.

---

## Acceptance Criteria

1. **Tag set.** A fixed set of bookmark tags is supported (e.g. Preferences, Work, Personal). Configurable via settings or constant; at least these three available.
2. **Save flow with tag.** When the user saves a bookmark (tool or /save-url), they can optionally choose a tag. UX: after URL (and optional note), show inline buttons [Preferences] [Work] [Personal] [Skip]. Choosing one stores the tag in the bookmark’s metadata (e.g. `metadata.tag` or `metadata.bookmark_tag`).
3. **Storage.** Bookmarks store the tag in knowledge metadata (e.g. `{"category": "bookmark", "tag": "work"}`). Existing bookmarks without a tag remain valid (tag optional).
4. **List/filter by tag.** `list_bookmarks` (and `/bookmarks`) accept an optional tag filter so the user can ask “list work bookmarks” or “bookmarks personal”.
5. **Schema and tool.** The `save_bookmark` tool schema documents an optional `tag` parameter (values: preferences, work, personal or equivalent). If the client sends `tag`, it is stored; no need to show buttons when tag is already provided (e.g. from a slash command like `/save-url work <url>`).

---

## Implementation

**Files:** `remy/ai/tools/bookmarks.py`, `remy/ai/tools/schemas.py`, `remy/bot/handlers/web.py` (if /save-url is there) or the handler that invokes save_bookmark and can show inline keyboards.

### Tag constant and storage

Define a small set of allowed tags, e.g. in `bookmarks.py` or config:

```python
BOOKMARK_TAGS = ("preferences", "work", "personal")
```

In `exec_save_bookmark`, accept optional `tag` from `inp`; validate against `BOOKMARK_TAGS`. Build metadata: `{"category": "bookmark", "tag": tag}` if tag else `{"category": "bookmark"}`. Pass to `knowledge_store.add_item(..., metadata)`.

### List filter

In `exec_list_bookmarks`, read `inp.get("tag")` or `inp.get("filter")`. If filter is a known tag, restrict to `metadata.tag == tag`. For knowledge store: when fetching facts with category bookmark, filter in Python or via SQL on JSON extract of metadata (e.g. `json_extract(metadata, '$.tag')`).

### Optional: inline buttons for /save-url

If the save flow is triggered from a command (e.g. `/save-url <url> [note]`), after saving without a tag the bot can reply with “Tag?” and [Preferences] [Work] [Personal] [Skip]. Callback updates the same bookmark’s metadata with the chosen tag (requires storing pending bookmark id in callback payload or doing a “last bookmark for user” update). Alternatively, require tag in the command or tool only and add buttons in a later iteration.

### Schema change

Add to `save_bookmark` tool input schema:

- `tag` (optional): string, enum ["preferences", "work", "personal"] — tag for the bookmark.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Save bookmark with tag “work” | Stored with metadata.tag = "work"; list_bookmarks filter=work returns it |
| Save bookmark with no tag | Stored with category bookmark only; list returns it when no filter |
| list_bookmarks filter=personal | Only bookmarks with tag personal returned |
| Invalid tag value in tool | Reject with clear message or ignore invalid tag |
| Existing bookmarks (no tag) | Still listed; filter by tag excludes them (or include “untagged” filter if desired) |

---

## Out of Scope

- User-defined tags (only fixed set in this story).
- Tag management UI (rename/merge tags).
- Tags for other entity types (goals, facts) — separate story.
