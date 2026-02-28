# User Story: Fix Telegram Markdown Header Rendering

✅ Complete — February 2026

**As a user,**  
**I want** Remy's responses to render Markdown headers, tables, and other formatting correctly in the Telegram app,  
**So that** long responses are easy to read and structured as intended.

## Acceptance Criteria

- [x] Convert all header levels (H1–H4) to Telegram-compatible formatting with visual hierarchy:
  - `# H1` → **BOLD UPPERCASE** (most prominent)
  - `## H2` → **Bold Title Case**
  - `### H3` → **Bold**
  - `#### H4` → *Italic*
- [x] Convert Markdown tables to bulleted lists (Telegram has no native table support):
  - 2-column tables: `• *Column1:* Value`
  - Multi-column tables: `• *First:* rest, joined, by, commas`
- [x] Escape all 18+ MarkdownV2 special characters (`_*[]()~\`>#+-=|{}.!`) outside formatting
- [x] Preserve all valid Telegram MarkdownV2 formatting:
  - `*bold*`, `_italic_`, `__underline__`, `~strikethrough~`
  - `||spoiler||` (tap to reveal)
  - `` `code` `` and ` ```code blocks``` `
  - `[links](url)`
  - `> block quotes` (at line start)
- [x] Central `format_telegram_message()` utility in `remy/utils/telegram_formatting.py`

## Background Context

Telegram's `MarkdownV2` does not natively support `#` symbols for headers or pipe-based tables. Headers display as literal `#` text, and tables render as garbled pipe characters. Additionally, `MarkdownV2` is extremely strict about escaping special characters outside of code blocks, which often causes bot crashes on unpredicted output.

## Implementation

**File:** `remy/utils/telegram_formatting.py`

Processing order:
1. Extract code blocks (protect from processing)
2. Convert tables to bulleted lists
3. Convert headers to bold/italic hierarchy
4. Escape special characters in non-code portions
5. Restore code blocks

**Integration:** `StreamingReply._edit_or_skip()` in `remy/bot/streaming.py` calls `format_telegram_message()` before sending.

## Test Cases

| Scenario | Expected |
|----------|----------|
| `# Main Title` | `*MAIN TITLE*` |
| `## Section` | `*Section*` (title case) |
| `### Subsection` | `*Subsection*` |
| `#### Detail` | `_Detail_` |
| 2-column table | Bulleted list with `• *Key:* Value` |
| Multi-column table | `• *First:* col2, col3, col4` |
| Code block with special chars | Preserved unchanged |
| Text with `.` and `!` | Escaped as `\.` and `\!` |
| `*bold*` text | Preserved as `*bold*` |
| `_italic_` text | Preserved as `_italic_` |
| `__underline__` text | Preserved as `__underline__` |
| `~strikethrough~` text | Preserved as `~strikethrough~` |
| `\|\|spoiler\|\|` text | Preserved as `\|\|spoiler\|\|` |
| `[link](url)` | Preserved as `[link](url)` |
| `> quote` at line start | Preserved as block quote |
| `5 > 3` mid-line | Escaped as `5 \> 3` |

## Files Changed

- `remy/utils/telegram_formatting.py` — enhanced formatter
- `tests/test_telegram_formatting.py` — comprehensive test suite
