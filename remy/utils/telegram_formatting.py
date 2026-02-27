import re
import logging

logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.
    Required characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    Exception: characters inside code blocks/inline code should NOT be escaped.
    """
    # Characters that must be escaped in MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def format_telegram_message(text: str) -> str:
    """
    Formats text for Telegram MarkdownV2 compliance.
    1. Converts Markdown headers (# Header) to BOLD CAPS (*HEADER*).
    2. Escapes special characters properly while respecting code blocks.
    """
    if not text:
        return ""

    # 1. Convert headers: # Header -> *HEADER*
    # We do this before escaping so we can use * comfortably
    def replace_header(match):
        level = len(match.group(1))
        content = match.group(2).strip()
        return f"*{content.upper()}*"

    # Match lines starting with # (1 to 6)
    text = re.sub(r'^(#{1,6})\s+(.+)$', replace_header, text, flags=re.MULTILINE)

    # 2. Split by code blocks to avoid escaping inside them
    # This handles both ```blocks``` and `inline`
    parts = re.split(r'(```[\s\S]*?```|`.*?`)', text)
    
    formatted_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Not a code block, escape it
            formatted_parts.append(escape_markdown_v2(part))
        else:
            # Is a code block, keep as is
            formatted_parts.append(part)

    return "".join(formatted_parts)
