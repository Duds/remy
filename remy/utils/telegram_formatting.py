"""
Telegram MarkdownV2 formatting utilities.

Converts standard Markdown to Telegram-compatible MarkdownV2:
- Headers (H1-H4) → visual hierarchy using bold/italic/caps
- Tables → bulleted lists (Telegram has no table support)
- Special character escaping (18+ reserved chars)
- Preserves valid MarkdownV2 formatting:
  - *bold*, _italic_, __underline__, ~strikethrough~
  - ||spoiler||, `code`, ```code blocks```
  - [links](url), >block quotes
"""

import re
import logging

logger = logging.getLogger(__name__)

# Characters that must be escaped in MarkdownV2 (outside code blocks)
_ESCAPE_CHARS = r'_*[]()~`>#+-=|{}.!'


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.
    
    Required characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    This should only be called on text OUTSIDE code blocks.
    """
    return re.sub(f'([{re.escape(_ESCAPE_CHARS)}])', r'\\\1', text)


def _escape_text_content(text: str) -> str:
    """
    Escape special characters in text content, preserving formatting markers.
    
    Preserves: *bold*, _italic_, __underline__, ~strikethrough~, ||spoiler||, [links](url)
    Escapes content inside markers but keeps the markers themselves intact.
    """
    result = []
    i = 0
    
    while i < len(text):
        # Check for [link](url) pattern - must check early
        if text[i] == '[':
            # Find closing ] and then (url)
            bracket_end = text.find(']', i + 1)
            if bracket_end != -1 and bracket_end + 1 < len(text) and text[bracket_end + 1] == '(':
                paren_end = text.find(')', bracket_end + 2)
                if paren_end != -1:
                    # Found a [text](url) pattern
                    link_text = text[i + 1:bracket_end]
                    url = text[bracket_end + 2:paren_end]
                    # Escape the link text, but keep URL as-is (escape special chars in URL)
                    escaped_link_text = _escape_inner_content(link_text)
                    # URLs need specific escaping - only ) needs escaping inside the URL
                    escaped_url = url.replace(')', '\\)')
                    result.append(f'[{escaped_link_text}]({escaped_url})')
                    i = paren_end + 1
                    continue
        
        # Check for ||spoiler|| pattern (must check before single |)
        if text[i:i+2] == '||':
            # Find closing ||
            end = text.find('||', i + 2)
            if end != -1 and end > i + 2:
                # Found a ||content|| pattern - escape content, keep markers
                content = text[i + 2:end]
                escaped_content = _escape_inner_content(content)
                result.append(f'||{escaped_content}||')
                i = end + 2
                continue
        
        # Check for __underline__ pattern (must check before single _)
        if text[i:i+2] == '__':
            # Find closing __
            end = text.find('__', i + 2)
            if end != -1 and end > i + 2:
                # Found a __content__ pattern - escape content, keep markers
                content = text[i + 2:end]
                escaped_content = _escape_inner_content(content)
                result.append(f'__{escaped_content}__')
                i = end + 2
                continue
        
        # Check for ~strikethrough~ pattern
        if text[i] == '~':
            # Find closing ~
            end = text.find('~', i + 1)
            if end != -1 and end > i + 1:
                # Found a ~content~ pattern - escape content, keep markers
                content = text[i + 1:end]
                escaped_content = _escape_inner_content(content)
                result.append(f'~{escaped_content}~')
                i = end + 1
                continue
        
        # Check for *bold* pattern
        if text[i] == '*':
            # Find closing *
            end = text.find('*', i + 1)
            if end != -1 and end > i + 1:
                # Found a *content* pattern - escape content, keep markers
                content = text[i + 1:end]
                escaped_content = _escape_inner_content(content)
                result.append(f'*{escaped_content}*')
                i = end + 1
                continue
        
        # Check for _italic_ pattern (single underscore, not double)
        if text[i] == '_' and (i + 1 >= len(text) or text[i + 1] != '_'):
            # Find closing _ (but not __)
            end = i + 1
            while end < len(text):
                if text[end] == '_' and (end + 1 >= len(text) or text[end + 1] != '_'):
                    break
                end += 1
            if end < len(text) and end > i + 1:
                # Found a _content_ pattern - escape content, keep markers
                content = text[i + 1:end]
                escaped_content = _escape_inner_content(content)
                result.append(f'_{escaped_content}_')
                i = end + 1
                continue
        
        # Check for > block quote at start of line
        if text[i] == '>':
            # Check if this is at the start of a line (or start of text)
            is_line_start = (i == 0 or text[i - 1] == '\n')
            if is_line_start:
                # This is a block quote marker - preserve it
                result.append('>')
                i += 1
                continue
        
        # Regular character - escape if needed
        if text[i] in _ESCAPE_CHARS:
            result.append(f'\\{text[i]}')
        else:
            result.append(text[i])
        i += 1
    
    return ''.join(result)


def _escape_inner_content(text: str) -> str:
    """Escape special chars inside formatting markers (but not * or _ which are the markers)."""
    # Inside *bold* or _italic_, we still need to escape other special chars
    # but NOT the marker chars themselves (they're already the outer delimiters)
    chars_to_escape = r'[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(chars_to_escape)}])', r'\\\1', text)


def _preserve_block_quotes(text: str) -> str:
    """
    Preserve Markdown block quotes for Telegram.
    
    Telegram MarkdownV2 supports > for block quotes.
    Standard Markdown uses > at line start, which Telegram also uses.
    We just need to ensure the > isn't escaped.
    
    This is handled by processing block quote lines specially.
    """
    lines = text.split('\n')
    result = []
    for line in lines:
        # Check if line starts with > (block quote)
        stripped = line.lstrip()
        if stripped.startswith('>'):
            # Mark this as a block quote line - we'll handle it in escaping
            # For now, just pass through (the > will be preserved in _escape_text_content)
            result.append(line)
        else:
            result.append(line)
    return '\n'.join(result)


def _convert_headers(text: str) -> str:
    """
    Convert Markdown headers to Telegram-compatible formatting.
    
    H1 (# )    → *BOLD UPPERCASE*
    H2 (## )   → *Bold Title Case*
    H3 (### )  → *Bold*
    H4 (####)  → _Italic_
    """
    def replace_header(match: re.Match) -> str:
        hashes = match.group(1)
        content = match.group(2).strip()
        level = len(hashes)
        
        if level == 1:
            # H1: Bold uppercase - most prominent
            return f"*{content.upper()}*"
        elif level == 2:
            # H2: Bold title case
            return f"*{content.title()}*"
        elif level == 3:
            # H3: Bold as-is
            return f"*{content}*"
        else:
            # H4+: Italic
            return f"_{content}_"
    
    # Match lines starting with 1-6 # symbols
    return re.sub(r'^(#{1,6})\s+(.+)$', replace_header, text, flags=re.MULTILINE)


def _is_table_separator(line: str) -> bool:
    """Check if a line is a Markdown table separator (e.g. |---|---|)."""
    # Must have at least one | and consist mainly of -, :, |, and whitespace
    if '|' not in line:
        return False
    stripped = line.strip()
    # Remove all valid separator chars and see if anything remains
    cleaned = re.sub(r'[-:|\s]', '', stripped)
    return len(cleaned) == 0 and '-' in stripped


def _convert_tables_to_lists(text: str) -> str:
    """
    Convert Markdown tables to bulleted lists.
    
    Input:
        | Name  | Status |
        |-------|--------|
        | Alice | Done   |
        | Bob   | WIP    |
    
    Output:
        • *Alice:* Done
        • *Bob:* WIP
    
    For tables with more than 2 columns, formats as:
        • *Row1Col1:* Col2, Col3, Col4
    """
    lines = text.split('\n')
    result_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Detect table start: line with | that isn't a separator
        if '|' in line and not _is_table_separator(line):
            # Check if this looks like a table header row
            cells = [c.strip() for c in line.split('|')]
            cells = [c for c in cells if c]  # Remove empty from leading/trailing |
            
            if len(cells) >= 1:
                # Look ahead for separator row
                if i + 1 < len(lines) and _is_table_separator(lines[i + 1]):
                    # This is a table! Extract headers and data rows
                    headers = cells
                    table_rows = []
                    i += 2  # Skip header and separator
                    
                    # Collect data rows
                    while i < len(lines):
                        row_line = lines[i]
                        if '|' not in row_line:
                            break
                        if _is_table_separator(row_line):
                            # Another separator, skip
                            i += 1
                            continue
                        row_cells = [c.strip() for c in row_line.split('|')]
                        row_cells = [c for c in row_cells if c]
                        if row_cells:
                            table_rows.append(row_cells)
                        i += 1
                    
                    # Convert to list format
                    if table_rows:
                        for row in table_rows:
                            if len(row) >= 1:
                                if len(headers) == 2 and len(row) >= 2:
                                    # 2-column table: "• *Col1:* Col2"
                                    result_lines.append(f"• *{row[0]}:* {row[1]}")
                                elif len(row) == 1:
                                    # Single value
                                    result_lines.append(f"• {row[0]}")
                                else:
                                    # Multi-column: "• *First:* rest joined"
                                    rest = ', '.join(row[1:]) if len(row) > 1 else ''
                                    if rest:
                                        result_lines.append(f"• *{row[0]}:* {rest}")
                                    else:
                                        result_lines.append(f"• {row[0]}")
                        result_lines.append('')  # Blank line after table
                    continue
        
        result_lines.append(line)
        i += 1
    
    return '\n'.join(result_lines)


def _extract_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    """
    Extract code blocks and replace with placeholders.
    
    Returns the text with placeholders and a dict mapping placeholder -> original.
    This prevents escaping inside code blocks.
    
    Placeholders use alphanumeric-only format to avoid being escaped.
    """
    placeholders = {}
    counter = [0]
    
    def replace_block(match: re.Match) -> str:
        placeholder = f"CODEBLOCK{counter[0]}CODEBLOCK"
        placeholders[placeholder] = match.group(0)
        counter[0] += 1
        return placeholder
    
    # Match fenced code blocks (```...```) and inline code (`...`)
    # Fenced blocks first (greedy), then inline
    text = re.sub(r'```[\s\S]*?```', replace_block, text)
    text = re.sub(r'`[^`]+`', replace_block, text)
    
    return text, placeholders


def _restore_code_blocks(text: str, placeholders: dict[str, str]) -> str:
    """Restore code block placeholders with original content."""
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def _fix_markdown_formatting(text: str) -> str:
    """
    Fix common Markdown issues that break MarkdownV2.
    
    - Unbalanced asterisks/underscores
    - Nested formatting that Telegram doesn't support
    """
    # Fix unmatched bold markers at end of text
    if text.rstrip().endswith('*') and text.count('*') % 2 == 1:
        text = text.rstrip()[:-1] + '\\*'
    
    if text.rstrip().endswith('_') and text.count('_') % 2 == 1:
        text = text.rstrip()[:-1] + '\\_'
    
    return text


def format_telegram_message(text: str) -> str:
    """
    Format text for Telegram MarkdownV2 compliance.
    
    Processing order:
    1. Extract code blocks (preserve them untouched)
    2. Convert tables to lists
    3. Convert headers to bold/italic hierarchy
    4. Escape special characters (preserving our formatting markers)
    5. Restore code blocks
    
    Args:
        text: Raw Markdown text from Claude or other source
        
    Returns:
        MarkdownV2-compliant text safe for Telegram
    """
    if not text:
        return ""
    
    # 1. Extract code blocks to protect them from processing
    text, placeholders = _extract_code_blocks(text)
    
    # 2. Convert tables to lists (before escaping, so we can use * for bold)
    text = _convert_tables_to_lists(text)
    
    # 3. Convert headers (before escaping, so we can use * and _)
    text = _convert_headers(text)
    
    # 4. Now escape special characters in non-code portions
    # Split by placeholders, escape the non-placeholder parts
    parts = re.split(r'(CODEBLOCK\d+CODEBLOCK)', text)
    escaped_parts = []
    for part in parts:
        if part.startswith('CODEBLOCK') and part.endswith('CODEBLOCK'):
            escaped_parts.append(part)
        else:
            escaped_parts.append(_escape_text_content(part))
    text = ''.join(escaped_parts)
    
    # 5. Restore code blocks
    text = _restore_code_blocks(text, placeholders)
    
    # 6. Final fixes for edge cases
    text = _fix_markdown_formatting(text)
    
    return text
