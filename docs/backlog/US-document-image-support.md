# User Story: Document/File Image Support

⬜ Backlog — P2

## Summary
As a user, I want to send images as Telegram document messages (uncompressed, original quality)
and have Remy analyse them — not just compressed photos sent via the photo API.

---

## Background

Phase 7 implemented `handle_photo` in `bot/handlers.py`, which handles Telegram `photo`
messages. Telegram automatically compresses these to JPEG.

However, the Phase 7.4 checklist also specified a `document_handler` for uncompressed images
sent as files. This was never implemented. Currently:

- Sending a photo the normal way → handled ✅
- Sending an image as a file (uncompressed, "Send as file" in Telegram) → **silently ignored**
- Sending a PNG, WebP, or HEIC as a document → **silently ignored**

The `document` message type in Telegram carries a `mime_type` field and the original bytes,
making MIME detection straightforward. Documents also avoid Telegram's JPEG compression, which
matters for screenshots, whiteboards, and receipts where text legibility is important.

---

## Acceptance Criteria

1. **`handle_document` handler registered** alongside `handle_photo`.
2. **Images sent as documents are processed** identically to photos: base64-encoded and passed
   to Claude as an Anthropic image content block.
3. **MIME type is read from Telegram metadata**, not hardcoded. Supported types:
   `image/jpeg`, `image/png`, `image/gif`, `image/webp`. All others return:
   `"❌ Unsupported file type. Send images as JPEG, PNG, GIF, or WebP."`
4. **Size limit enforced before download**: reject documents > 5 MB with a clear message
   (check `document.file_size` before calling `get_file()`).
5. **Non-image documents ignored gracefully**: PDFs, ZIPs, etc. receive:
   `"I can only analyse image files. For documents, try copying and pasting the text."`
6. **Conversation history placeholder**: `[document: filename.png]` (includes filename if
   available from `document.file_name`).
7. **No new dependencies.**

---

## Implementation

**File:** `remy/bot/handlers.py`

### 1. Add `handle_document`

Mirror the `handle_photo` function but:
- Access `update.message.document` instead of `update.message.photo[-1]`
- Check `document.mime_type` against the allowlist before downloading
- Check `document.file_size` before downloading (reject > 5 MB)
- Use `document.file_name` (if present) in the history placeholder

```python
ALLOWED_DOC_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_DOC_SIZE = 5 * 1024 * 1024  # 5 MB

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _reject_unauthorized(update):
        return
    doc = update.message.document
    if not doc.mime_type or doc.mime_type not in ALLOWED_DOC_MIMES:
        await update.message.reply_text(
            "I can only analyse image files (JPEG, PNG, GIF, WebP). "
            "For other documents, try copying and pasting the text."
        )
        return
    if doc.file_size and doc.file_size > MAX_DOC_SIZE:
        await update.message.reply_text("❌ Image too large (max 5 MB).")
        return
    # ... remainder mirrors handle_photo, using doc.mime_type as media_type
    # and f"[document: {doc.file_name or 'image'}]" as history placeholder
```

### 2. Register the handler

In the `return {}` dict at the end of `make_handlers()`:

```python
"document": handle_document,
```

And in `remy/bot/telegram_bot.py`, register with `MessageHandler`:

```python
app.add_handler(MessageHandler(filters.Document.ALL, handlers["document"]))
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| Send PNG as file ("Send as file" in Telegram) | Remy analyses it correctly with `image/png` MIME type |
| Send WebP as file | Analysed correctly with `image/webp` |
| Send PDF as document | `"I can only analyse image files…"` response |
| Send ZIP as document | Same graceful rejection |
| Send image > 5 MB | `"❌ Image too large (max 5 MB)."` |
| Send image with no mime_type set | Treated as unsupported — rejection message |
| Caption included with document image | Caption used as user prompt (same as photo handler) |

---

## Notes

- Telegram photo messages remain JPEG-compressed. The hardcoded `"image/jpeg"` MIME in
  `handle_photo` is correct and should not be changed.
- Only the document handler needs dynamic MIME detection.

---

## Out of Scope

- HEIC/HEIF support (not in Anthropic's supported MIME list)
- Video files
- PDF parsing / text extraction
- Storing document images to disk
