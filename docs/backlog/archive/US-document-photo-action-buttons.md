# User Story: Document/Photo Action Buttons

**Status:** ✅ Done (Completed: 2026-03-10)

## Summary
As a user, I want to choose what to do with a photo or document (Summarise, Extract tasks, Save) via one-tap inline buttons so that I don't have to type and can quickly pick the right action.

---

## Background

**Phase 8 Tier 2.** When the user sends a photo or document, the bot currently processes it immediately (vision analysis). This story adds inline buttons [Summarise] [Extract tasks] [Save] so the user can pick the action before or after sending.

---

## Acceptance Criteria

1. **Buttons on attachment.** When the user sends a photo or image document, the bot replies with an inline keyboard: [Summarise] [Extract tasks] [Save].
2. **Summarise.** Tapping Summarise runs vision with prompt "Summarise this image briefly."
3. **Extract tasks.** Tapping Extract tasks runs vision with prompt "Extract actionable tasks or to-dos from this image. Return a concise list."
4. **Save.** Tapping Save stores the image context (or a note) as a bookmark/fact; user may be prompted for a note or it is saved with a default label.
5. **Callback data.** Use short token in callback_data (≤64 bytes); store file_id and metadata in a short-lived cache keyed by token.
6. **Existing flow.** Either: (a) show buttons first and act on tap, or (b) process as now and add buttons to the reply for alternate actions. Implementation may choose (a) or (b).

---

## Implementation

**Files:** `remy/bot/handlers/chat.py` (handle_photo, handle_document), `remy/bot/handlers/callbacks.py` (new callback for attach actions).

- Cache: module-level dict or cache with TTL (e.g. 5 min), key = token, value = {file_id, file_type, caption, user_id, mime_type}.
- Callback prefix: `attach_act:s:<token>` (summarise), `attach_act:e:<token>` (extract), `attach_act:v:<token>` (save).
- On callback: look up token, download file, run Claude with the chosen prompt or save flow.

---

## Out of Scope

- Non-image documents (PDF, etc.) — keep current behaviour.
- Multiple attachments in one message.
