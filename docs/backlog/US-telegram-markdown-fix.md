# User Story: Fix Telegram Markdown Header Rendering

**As a user,**  
**I want** Remy's responses to render Markdown headers and other formatting correctly in the Telegram app,  
**So that** long responses are easy to read and structured as intended.

## Acceptance Criteria

- [ ] Convert standard Markdown headers (`# Header`) into a Telegram-compatible format (e.g., Bold + All Caps, or using Telegram's specific MarkdownV2 escapes).
- [ ] Ensure all other Markdown symbols (like `.`, `!`, `-`) are correctly escaped for `MarkdownV2` to avoid "Parse Error" crashes.
- [ ] Implement a central "Telegram Markdown Sanitizer" utility to handle the conversion before sending.
- [ ] Verify that nested lists and code blocks continue to render correctly.

## Background Context

Telegram's `MarkdownV2` does not natively support `#` symbols for headers. It simply displays them as literal text. To achieve a "Header" look, we typically need to use bolding or a specific symbol prefix. Additionally, `MarkdownV2` is extremely strict about escaping special characters outside of code blocks, which often causes bot crashes on unpredicted output.

## Proposed Implementation Strategy

1. Create a utility function `remy/utils/telegram_formatting.py` that parses the raw Markdown from the AI.
2. Transform `#` headers into **BOLD UPPERCASE** or **Bold** lines.
3. Apply comprehensive escaping for the 18+ special characters required by Telegram.
4. Update `remy/bot/handlers.py` (specifically `stream_to_telegram`) to use this utility.
