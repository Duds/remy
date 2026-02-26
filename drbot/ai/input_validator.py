"""
Input validation and sanitization for security.

Guards against:
  - Command injection (shell metacharacters)
  - Prompt injection (crafted model jailbreaks)
  - Rate limiting abuse
  - Excessively long inputs
"""

import logging
import re
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# Tags that MemoryInjector adds as structural wrappers — preserve these exactly.
# Any other XML-like tag found in injected memory content will be escaped.
_SAFE_MEMORY_TAG = re.compile(
    r'^<(?:/?memory|/?facts|/?goals|/?goal|fact\b[^>]*|/fact)>$',
    re.IGNORECASE,
)
_ANY_TAG = re.compile(r'</?[a-zA-Z][^>]*>')

# Shell metacharacters that could trigger injection
_SHELL_INJECTION_PATTERN = re.compile(
    r"""
    (?:
        ;\s*(?:rm|kill|curl|bash|sh|python|eval|exec) |  # dangerous commands after semicolon
        \|\s*(?:nc|netcat|bash|sh) |                     # pipe to shell
        >\s*\/dev\/null |                                 # silent redirection
        \$\(.*\) |                                        # command substitution
        `.*` |                                            # backtick substitution
        &&|;;|&                                           # shell operators (if not normal)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Patterns that suggest prompt injection attacks
_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore.*previous.*instruction|disregard.*prompt|forget.*context", re.IGNORECASE),
    re.compile(r"system.*override|system.*prompt|administrator|root.*access", re.IGNORECASE),
    re.compile(r"role.*play.*as.*admin|pretend.*you.*are.*uncensored", re.IGNORECASE),
]

# Max reasonable input sizes
MAX_MESSAGE_LENGTH = 10_000  # chars
MAX_COMMAND_LENGTH = 500     # chars
MAX_TOPIC_LENGTH = 500       # chars


class RateLimiter:
    """
    Simple per-user rate limiter.
    Tracks last N seconds of messages per user.
    """

    def __init__(self, max_messages_per_minute: int = 10):
        self.max_per_minute = max_messages_per_minute
        self.user_messages: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Check if user is allowed to send a message.
        Returns (allowed: bool, reason_if_denied: str | None)
        """
        now = time.time()
        cutoff = now - 60.0

        # Clean old entries
        if user_id in self.user_messages:
            self.user_messages[user_id] = [t for t in self.user_messages[user_id] if t > cutoff]

        # Check limit
        count = len(self.user_messages[user_id])
        if count >= self.max_per_minute:
            return False, (
                f"Rate limited: {self.max_per_minute} messages per minute. "
                f"Try again in ~{int(60 - (now - self.user_messages[user_id][0]))}s."
            )

        # Record this message
        self.user_messages[user_id].append(now)
        return True, None


def validate_message_input(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> tuple[bool, Optional[str]]:
    """
    Validate a regular message for safety.
    Returns (valid: bool, reason_if_invalid: str | None)
    """
    if not text or not text.strip():
        return False, "Empty message"

    if len(text) > max_length:
        return False, f"Message too long ({len(text)} > {max_length} chars)"

    # Flag but don't block shell injection — user might be asking about shell commands
    if _SHELL_INJECTION_PATTERN.search(text):
        logger.warning("Potential shell injection detected in message: %s…", text[:100])

    # Flag but don't block prompt injection patterns
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning("Potential prompt injection detected in message: %s…", text[:100])
            break

    return True, None


def validate_command_input(command: str, arg: str = "") -> tuple[bool, Optional[str]]:
    """
    Validate command and arguments for safety.
    Returns (valid: bool, reason_if_invalid: str | None)
    """
    if len(command) > MAX_COMMAND_LENGTH:
        return False, "Command too long"

    if len(arg) > MAX_TOPIC_LENGTH:
        return False, f"Argument too long ({len(arg)} > {MAX_TOPIC_LENGTH} chars)"

    return True, None


def sanitize_file_path(path: str, allowed_bases: list[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Sanitize a file path to prevent directory traversal.

    Args:
        path: The path to sanitize
        allowed_bases: List of allowed base directories (e.g., ['/home/user/Projects'])

    Returns:
        (sanitized_path: str | None, error: str | None)

    Example:
        path, err = sanitize_file_path('~/Projects/test.py', [Path.home() / 'Projects'])
        if err:
            return err
        # Safe to use path
    """
    from pathlib import Path

    try:
        # Expand ~ and resolve to absolute path
        resolved = Path(path).expanduser().resolve()

        # Check if it's under an allowed base
        for allowed in allowed_bases:
            allowed_path = Path(allowed).resolve()
            try:
                resolved.relative_to(allowed_path)
                # Safe — it's under the allowed base
                return str(resolved), None
            except ValueError:
                # Not under this allowed base, try next
                continue

        # Not under any allowed base
        return None, f"Path '{path}' is not in allowed directories: {allowed_bases}"

    except (ValueError, RuntimeError) as e:
        return None, f"Invalid path '{path}': {e}"


def sanitize_memory_injection(text: str) -> str:
    """
    Escape any XML-like tags in injected memory content that are not part of
    MemoryInjector's own structural markup.

    MemoryInjector wraps content in <memory>, <facts>, <goals>, <fact>, <goal>
    tags. Any other tag found (e.g. <system>, <instructions>, </memory>) is
    user-derived and could be used for prompt injection — escape it.
    """
    found_tags = _ANY_TAG.findall(text)
    sanitized = text
    warned = False
    for tag in set(found_tags):
        if not _SAFE_MEMORY_TAG.match(tag):
            escaped = tag.replace("<", "&lt;").replace(">", "&gt;")
            sanitized = sanitized.replace(tag, escaped)
            if not warned:
                logger.warning(
                    "Escaped potentially dangerous tag in memory injection: %s", tag
                )
                warned = True
    return sanitized
