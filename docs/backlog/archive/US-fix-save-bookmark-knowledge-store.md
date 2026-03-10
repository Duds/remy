# User Story: Fix save_bookmark KnowledgeStore AttributeError

**Status:** ✅ Done

## Summary

As a developer, I want `save_bookmark` to work correctly so that Remy doesn't fail when users ask to bookmark content, and so failed tool calls don't add latency or confusing error messages to the conversation.

---

## Background

Logs from 03/03/2026 show:

```
Tool save_bookmark failed: 'KnowledgeStore' object has no attribute 'add'
  File "remy/ai/tools/bookmarks.py", line 28, in exec_save_bookmark
    await registry._knowledge_store.add(
AttributeError: 'KnowledgeStore' object has no attribute 'add'
```

The `KnowledgeStore` API has changed or was never implemented with an `add` method. The tool dispatch catches the error and returns it to the model, but the user experience is degraded and the model may retry or produce a confused reply.

Related: `remy/ai/tools/bookmarks.py`, `remy/memory/` (KnowledgeStore implementation), `remy/ai/tools/registry.py`.

---

## Acceptance Criteria

1. **save_bookmark executes successfully.** When the model invokes `save_bookmark` with valid input, the bookmark is stored and the tool returns success.
2. **Correct API usage.** `bookmarks.py` uses the actual `KnowledgeStore` interface (e.g. `add`, `upsert`, or whatever the store exposes). No `AttributeError`.
3. **Error handling.** Invalid input (e.g. missing URL, empty title) returns a structured error message to the model, not a traceback.
4. **Regression.** Existing bookmark retrieval (if any) continues to work. Other tools that use `KnowledgeStore` are unaffected.
5. **Tests.** Unit test covers successful save and at least one error path.

---

## Implementation

**Files:** `remy/ai/tools/bookmarks.py`, `remy/memory/` (KnowledgeStore class), `tests/test_tools/test_bookmarks.py` (or equivalent).

- Inspect `KnowledgeStore` in `remy/memory/` for the correct method signature (e.g. `upsert`, `add_document`, `insert`).
- Update `exec_save_bookmark` in `bookmarks.py` to call the correct method with the right parameters.
- Add input validation (required fields, URL format) and return a clear error dict on failure.
- Add or update tests for `save_bookmark`.

### Notes

- If `KnowledgeStore` does not support bookmarks, this may require implementing a minimal bookmark storage (e.g. in the existing DB or a separate table) and wiring it to the tool.
- Check whether bookmarks are meant to be RAG-queryable or just stored for later retrieval.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Valid URL + title | Bookmark stored; tool returns success |
| Missing URL | Structured error to model |
| KnowledgeStore.add called | No AttributeError; correct method used |
| Retrieve bookmark (if supported) | Bookmark found |

---

## Out of Scope

- Adding new bookmark features (tags, folders).
- Changing how bookmarks are displayed to the user.
- Other KnowledgeStore consumers.
