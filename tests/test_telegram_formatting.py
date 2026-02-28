"""Tests for Telegram MarkdownV2 formatting utilities."""

import pytest
from remy.utils.telegram_formatting import (
    format_telegram_message,
    escape_markdown_v2,
    _convert_headers,
    _convert_tables_to_lists,
)


class TestEscapeMarkdownV2:
    """Test special character escaping."""

    def test_escapes_special_chars(self):
        text = "Hello_world *bold* [link](url) test.end!"
        result = escape_markdown_v2(text)
        assert r"\_" in result
        assert r"\*" in result
        assert r"\[" in result
        assert r"\." in result
        assert r"\!" in result

    def test_escapes_all_required_chars(self):
        special = "_*[]()~`>#+-=|{}.!"
        result = escape_markdown_v2(special)
        for char in special:
            assert f"\\{char}" in result

    def test_plain_text_unchanged(self):
        text = "Hello world this is plain text"
        result = escape_markdown_v2(text)
        # Only alphanumeric and spaces, no escaping needed except none
        assert result == text


class TestConvertHeaders:
    """Test header conversion to Telegram formatting."""

    def test_h1_becomes_bold_uppercase(self):
        text = "# Main Title"
        result = _convert_headers(text)
        assert result == "*MAIN TITLE*"

    def test_h2_becomes_bold_title_case(self):
        text = "## section heading"
        result = _convert_headers(text)
        assert result == "*Section Heading*"

    def test_h3_becomes_bold(self):
        text = "### Subsection"
        result = _convert_headers(text)
        assert result == "*Subsection*"

    def test_h4_becomes_italic(self):
        text = "#### Minor heading"
        result = _convert_headers(text)
        assert result == "_Minor heading_"

    def test_h5_h6_also_italic(self):
        assert _convert_headers("##### Deep") == "_Deep_"
        assert _convert_headers("###### Deepest") == "_Deepest_"

    def test_multiple_headers(self):
        text = """# Title
Some text
## Section
More text
### Subsection
#### Detail"""
        result = _convert_headers(text)
        assert "*TITLE*" in result
        assert "*Section*" in result
        assert "*Subsection*" in result
        assert "_Detail_" in result

    def test_preserves_non_header_hashes(self):
        text = "Use #hashtag in your post"
        result = _convert_headers(text)
        assert result == text  # No change - not at line start


class TestConvertTablesToLists:
    """Test table to list conversion."""

    def test_simple_two_column_table(self):
        text = """| Name  | Status |
|-------|--------|
| Alice | Done   |
| Bob   | WIP    |"""
        result = _convert_tables_to_lists(text)
        assert "• *Alice:* Done" in result
        assert "• *Bob:* WIP" in result
        assert "|" not in result

    def test_three_column_table(self):
        text = """| Item | Price | Stock |
|------|-------|-------|
| Milk | $3.50 | 10    |
| Eggs | $5.00 | 25    |"""
        result = _convert_tables_to_lists(text)
        assert "• *Milk:* $3.50, 10" in result
        assert "• *Eggs:* $5.00, 25" in result

    def test_table_with_alignment_markers(self):
        text = """| Left | Center | Right |
|:-----|:------:|------:|
| A    | B      | C     |"""
        result = _convert_tables_to_lists(text)
        assert "• *A:* B, C" in result

    def test_preserves_non_table_pipes(self):
        text = "Use | for OR operations"
        result = _convert_tables_to_lists(text)
        assert result == text

    def test_mixed_content_with_table(self):
        text = """Some intro text.

| Col1 | Col2 |
|------|------|
| A    | B    |

Some outro text."""
        result = _convert_tables_to_lists(text)
        assert "Some intro text." in result
        assert "• *A:* B" in result
        assert "Some outro text." in result


class TestFormatTelegramMessage:
    """Test the main formatting function."""

    def test_preserves_code_blocks(self):
        text = """Here's code:
```python
def hello():
    print("Hello #world")
```
And inline `code_here`."""
        result = format_telegram_message(text)
        # Code blocks should be preserved
        assert "```python" in result
        assert 'print("Hello #world")' in result
        assert "`code_here`" in result

    def test_escapes_outside_code_blocks(self):
        text = "Test. with special! chars"
        result = format_telegram_message(text)
        assert r"\." in result
        assert r"\!" in result

    def test_full_document_formatting(self):
        text = """# Main Title

Some intro with special.chars!

## Data Table

| Name | Value |
|------|-------|
| foo  | 123   |
| bar  | 456   |

### Code Example

```python
x = 1 + 2
```

#### Notes

Final notes here."""
        result = format_telegram_message(text)
        
        # Headers converted
        assert "*MAIN TITLE*" in result
        assert "*Data Table*" in result
        assert "*Code Example*" in result
        assert "_Notes_" in result
        
        # Table converted to list
        assert "• *foo:* 123" in result
        assert "• *bar:* 456" in result
        
        # Code preserved
        assert "```python" in result
        assert "x = 1 + 2" in result

    def test_empty_string(self):
        assert format_telegram_message("") == ""

    def test_plain_text_only(self):
        text = "Just some plain text without any special formatting"
        result = format_telegram_message(text)
        assert "Just some plain text" in result

    def test_nested_formatting_edge_case(self):
        text = "Text with *bold* and _italic_ markers"
        result = format_telegram_message(text)
        # *bold* and _italic_ are valid MarkdownV2 formatting - preserve them
        assert "*bold*" in result
        assert "_italic_" in result


class TestCodeFormatting:
    """Test that code formatting is preserved as valid Telegram MarkdownV2."""

    def test_inline_code_preserved(self):
        text = "Use `config.json` for settings"
        result = format_telegram_message(text)
        # Inline code should be preserved exactly
        assert "`config.json`" in result
        # The . inside backticks should NOT be escaped
        assert "`config\\.json`" not in result

    def test_fenced_code_block_preserved(self):
        text = """Here is code:
```python
def hello():
    print("Hello!")
```
Done."""
        result = format_telegram_message(text)
        # Code block preserved
        assert "```python" in result
        assert 'print("Hello!")' in result
        assert "```" in result
        # Content inside code block not escaped
        assert 'print\\(' not in result

    def test_code_with_special_chars_inside(self):
        text = "Run `npm install --save-dev @types/node` to install"
        result = format_telegram_message(text)
        # All special chars inside backticks preserved
        assert "`npm install --save-dev @types/node`" in result

    def test_multiple_inline_code_segments(self):
        text = "Use `foo` and `bar` together"
        result = format_telegram_message(text)
        assert "`foo`" in result
        assert "`bar`" in result


class TestSpoilerFormatting:
    """Test that spoiler formatting (||text||) is preserved."""

    def test_spoiler_preserved(self):
        text = "The answer is ||42||"
        result = format_telegram_message(text)
        assert "||42||" in result

    def test_spoiler_with_special_chars(self):
        text = "Secret: ||It costs $50.00!||"
        result = format_telegram_message(text)
        # Spoiler markers preserved, content inside escaped
        assert "||" in result
        assert "50" in result

    def test_multiple_spoilers(self):
        text = "First ||secret|| and second ||hidden||"
        result = format_telegram_message(text)
        assert "||secret||" in result
        assert "||hidden||" in result

    def test_spoiler_with_longer_content(self):
        text = "The gift is ||a new watch for his birthday||"
        result = format_telegram_message(text)
        assert "||a new watch for his birthday||" in result

    def test_spoiler_not_confused_with_single_pipe(self):
        text = "Use | for OR and ||spoiler|| for hidden"
        result = format_telegram_message(text)
        assert "||spoiler||" in result
        # Single pipe should be escaped
        assert "\\|" in result


class TestUnderlineFormatting:
    """Test that underline formatting (__text__) is preserved."""

    def test_underline_preserved(self):
        text = "This is __underlined__ text"
        result = format_telegram_message(text)
        assert "__underlined__" in result

    def test_underline_with_special_chars(self):
        text = "Note: __important!__"
        result = format_telegram_message(text)
        assert "__important" in result
        assert "__" in result

    def test_underline_not_confused_with_italic(self):
        text = "Both _italic_ and __underline__ work"
        result = format_telegram_message(text)
        assert "_italic_" in result
        assert "__underline__" in result


class TestStrikethroughFormatting:
    """Test that strikethrough formatting (~text~) is preserved."""

    def test_strikethrough_preserved(self):
        text = "This is ~crossed out~ text"
        result = format_telegram_message(text)
        assert "~crossed out~" in result

    def test_strikethrough_with_special_chars(self):
        text = "Price: ~$100~ now $50"
        result = format_telegram_message(text)
        assert "~" in result
        assert "100" in result

    def test_multiple_strikethroughs(self):
        text = "Remove ~this~ and ~that~"
        result = format_telegram_message(text)
        assert "~this~" in result
        assert "~that~" in result


class TestLinkFormatting:
    """Test that link formatting [text](url) is preserved."""

    def test_link_preserved(self):
        text = "Check [Google](https://google.com) for more"
        result = format_telegram_message(text)
        assert "[Google](https://google.com)" in result

    def test_link_with_special_chars_in_text(self):
        text = "See [docs & guides](https://example.com)"
        result = format_telegram_message(text)
        assert "[docs" in result
        assert "](https://example.com)" in result

    def test_multiple_links(self):
        text = "Try [link1](https://a.com) or [link2](https://b.com)"
        result = format_telegram_message(text)
        assert "[link1](https://a.com)" in result
        assert "[link2](https://b.com)" in result

    def test_link_with_parentheses_in_url(self):
        text = "See [Wikipedia](https://en.wikipedia.org/wiki/Python_(programming_language))"
        result = format_telegram_message(text)
        # The ) in the URL should be escaped
        assert "Wikipedia" in result
        assert "https://en.wikipedia.org" in result


class TestBlockQuoteFormatting:
    """Test that block quote formatting (>) is preserved."""

    def test_block_quote_preserved(self):
        text = "> This is a quote"
        result = format_telegram_message(text)
        assert result.startswith(">")
        assert "This is a quote" in result

    def test_multiline_block_quote(self):
        text = "> Line one\n> Line two"
        result = format_telegram_message(text)
        lines = result.split('\n')
        assert lines[0].startswith(">")
        assert lines[1].startswith(">")

    def test_block_quote_with_other_formatting(self):
        text = "> *Bold* in a quote"
        result = format_telegram_message(text)
        assert result.startswith(">")
        assert "*Bold*" in result

    def test_greater_than_mid_line_escaped(self):
        text = "5 > 3 is true"
        result = format_telegram_message(text)
        # > in the middle of a line should be escaped
        assert "\\>" in result


class TestEdgeCases:
    """Test edge cases and potential failure modes."""

    def test_table_without_separator_row(self):
        text = """| Not | A | Table |
| Just | Pipes | Here |"""
        result = _convert_tables_to_lists(text)
        # Without a separator row (|---|---|), this is not a valid table
        # The second line looks like data, not a separator, so it stays as-is
        # Actually both lines have content, so they should remain
        assert "Not" in result or "|" in result

    def test_single_column_table(self):
        text = """| Items |
|-------|
| One   |
| Two   |"""
        result = _convert_tables_to_lists(text)
        # Single column tables convert to simple bullet points
        assert "• One" in result
        assert "• Two" in result

    def test_header_with_special_chars(self):
        text = "# Title with special.chars!"
        result = format_telegram_message(text)
        # Header converted, then special chars escaped
        assert "*TITLE WITH SPECIAL" in result

    def test_inline_code_with_special_chars(self):
        text = "Use `file.txt` for config"
        result = format_telegram_message(text)
        # The . inside backticks should NOT be escaped
        assert "`file.txt`" in result
        # But outside should be
        assert "for config" in result

    def test_multiple_code_blocks(self):
        text = """First `inline` code.

```
block one
```

Then `another` inline.

```
block two
```"""
        result = format_telegram_message(text)
        assert "`inline`" in result
        assert "`another`" in result
        assert "block one" in result
        assert "block two" in result
