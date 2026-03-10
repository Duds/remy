# User Story: Gmail Label Creation

**Status:** ✅ Done

## Summary

As a user, I want Remy to create new Gmail labels (including nested labels) so that I can organise emails on the fly during triage without opening Gmail — e.g. "create a label called Hockey under Personal & Family".

---

## Background

Remy could list and apply labels but could not create new ones. The Gmail API supports `POST /gmail/v1/users/me/labels` and accepts a full path for nesting (e.g. `4-Personal & Family/Hockey`).

---

## Acceptance Criteria

1. **Tool: `create_gmail_label`** — Create a new label by name. Supports nested labels via slash notation (e.g. `Parent/Child`).
2. **Natural language** — User can say "create a label called Hockey under Personal & Family" and Remy calls the tool.
3. **Slash command** — `/gmail_create_label <name>` creates the label in one tap (e.g. `/gmail_create_label 4-Personal & Family/Hockey`).
4. **Help text** — `/help` lists the new command.
5. **Graceful degradation** — If Gmail is not configured, return a clear setup message.

---

## Implementation (Done)

- **`remy/google/gmail.py`** — `create_label(name, ...)` calls Gmail API `users().labels().create()`; `name` supports full path for nesting.
- **`remy/ai/tools/email.py`** — `exec_create_gmail_label`; schema in `remy/ai/tools/schemas.py`; registered in `remy/ai/tools/registry.py` and session tool list.
- **`remy/bot/handlers/email.py`** — `gmail_create_label_command` for `/gmail_create_label <name>`.
- **`remy/bot/telegram_bot.py`** — `CommandHandler("gmail_create_label", h)`.
- **`remy/bot/handlers/core.py`** — Help line for `/gmail-create-label`.

---

## Completed

- 2026-03-04: Tool and executor already present; added slash command and help. US closed.
