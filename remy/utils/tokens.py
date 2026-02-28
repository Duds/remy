"""
Token counting utilities for system prompt size estimation.

Uses anthropic.count_tokens() if available, otherwise falls back to
character-based estimation (~4 chars per token for English prose).
"""

import logging

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN_PROSE = 4.0
_CHARS_PER_TOKEN_STRUCTURED = 3.5


def count_tokens(text: str, model: str = "claude-sonnet-4-20250514") -> int:
    """
    Estimate token count for text.

    Attempts to use the Anthropic SDK's count_tokens() if available,
    otherwise falls back to character-based estimation.

    Args:
        text: The text to count tokens for.
        model: The model name (used for SDK counting if available).

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    try:
        import anthropic
        client = anthropic.Anthropic()
        result = client.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return result.input_tokens
    except (ImportError, AttributeError, Exception) as e:
        logger.debug("Anthropic token counting unavailable, using estimate: %s", e)

    return estimate_tokens(text)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count using character-based heuristics.

    Uses ~4 chars/token for prose, ~3.5 chars/token for structured content.
    Detects structured content by presence of XML tags, JSON, or code patterns.
    """
    if not text:
        return 0

    structured_markers = ["<", "{", "```", "def ", "class ", "import "]
    is_structured = any(marker in text for marker in structured_markers)

    chars_per_token = _CHARS_PER_TOKEN_STRUCTURED if is_structured else _CHARS_PER_TOKEN_PROSE
    return int(len(text) / chars_per_token)


def format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., '1,234 tokens')."""
    return f"{tokens:,} tokens"
