"""
Message complexity classifier.
Decides whether to route to a simple/cheap model or a complex/capable one.

Fast-path heuristics run first (no network).
Ambiguous messages fall back to a single Haiku call for 2-token classification.
Results are cached (TTL=5 min, max 256 entries) on a normalised key so minor
rephrasing and repeated questions skip the Haiku round-trip entirely.
"""

import hashlib
import logging
import re
import time
from typing import Literal

logger = logging.getLogger(__name__)

# Keywords that strongly signal a complex, agentic or tool-use task
_COMPLEX_PATTERNS = re.compile(
    r"""
    (?xi)
    \bwrite\b.*\b(?:script|function|class|file|test|code)\b
    | \bcreate\b.*\b(?:project|module|app|api|bot|function|script|class)\b
    | \brefactor\b | \bdebug\b | \bfix\s+(?:the|this|a)\b
    | \bbuild\b | \bimplement\b | \bgenerate\s+(?:code|a)\b
    | \bcommit\b | \bgit\b | \bdeploy\b
    | \.py\b | \.ts\b | \.js\b | \.sh\b   # file extensions
    | ```                                   # code fences
    | (?:step\s+\d|first.*then.*finally)    # multi-step instructions
    | /board                                # board command
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Messages that are clearly simple greetings or short questions
_SIMPLE_PATTERNS = re.compile(
    r"^(?:hi|hello|hey|thanks?|thank\s+you|ok|okay|cool|great|sure|yes|no|nope|yep)\b",
    re.IGNORECASE,
)

# Summarisation signals
_SUMMARIZE_PATTERNS = re.compile(
    r"\b(?:summarize|summarise|tldr|tl;dr|recap|sum\s+up|brief(?:ly)?|overview|digest)\b"
    r"|\bwhat(?:'s|\s+is)\s+(?:in|the\s+gist\s+of)\b",
    re.IGNORECASE,
)

# Reasoning / planning signals
_REASONING_PATTERNS = re.compile(
    r"\b(?:plan|strategy|analyse|analyze|think\s+through|walk\s+me\s+through"
    r"|pros?\s+and\s+cons?|trade-?offs?|compare|evaluate|should\s+I|help\s+me\s+decide)\b",
    re.IGNORECASE,
)

ClassificationResult = Literal[
    "routine",         # Short interactive messages, greetings
    "summarization",   # Email summaries, doc summaries
    "reasoning",       # Planning, multi-step tasks, deep analysis
    "safety",          # File writes, financial actions (if any)
    "coding",          # Scripting, code generation
    "persona",         # Roleplay
]

# ---------------------------------------------------------------------------
# In-process classification cache
# ---------------------------------------------------------------------------
_CACHE_TTL = 300        # seconds
_CACHE_MAX = 256        # entries; simple FIFO eviction when full

_cache: dict[str, tuple[ClassificationResult, float]] = {}  # key -> (result, ts)


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for a stable cache key."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text)


def _cache_key(text: str) -> str:
    return hashlib.md5(_normalise(text).encode(), usedforsecurity=False).hexdigest()


def _cache_get(key: str) -> ClassificationResult | None:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[1]) < _CACHE_TTL:
        return entry[0]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, result: ClassificationResult) -> None:
    if len(_cache) >= _CACHE_MAX:
        # Evict oldest entry
        oldest = min(_cache, key=lambda k: _cache[k][1])
        _cache.pop(oldest, None)
    _cache[key] = (result, time.monotonic())


class MessageClassifier:
    """Classify messages into categories for optimal model routing."""

    def __init__(self, claude_client=None) -> None:
        # claude_client injected to avoid circular imports; used only for ambiguous cases
        self._claude = claude_client

    async def classify(self, text: str) -> ClassificationResult:
        """Return a task category for the given message text."""
        stripped = text.strip()
        key = _cache_key(stripped)

        cached = _cache_get(key)
        if cached is not None:
            logger.debug("Classifier: %s (cache hit)", cached)
            return cached

        result = await self._classify_uncached(stripped)
        _cache_set(key, result)
        return result

    async def _classify_uncached(self, stripped: str) -> ClassificationResult:
        # Fast-path: obvious routine cases
        if len(stripped) < 80 and _SIMPLE_PATTERNS.match(stripped):
            logger.debug("Classifier: routine (greeting fast-path)")
            return "routine"

        # Fast-path: obvious coding cases
        if _COMPLEX_PATTERNS.search(stripped):
            logger.debug("Classifier: coding (keyword match)")
            return "coding"

        # Fast-path: summarisation
        if _SUMMARIZE_PATTERNS.search(stripped):
            logger.debug("Classifier: summarization (keyword match)")
            return "summarization"

        # Fast-path: reasoning / planning
        if _REASONING_PATTERNS.search(stripped):
            logger.debug("Classifier: reasoning (keyword match)")
            return "reasoning"

        # Fast-path: short messages default to routine
        if len(stripped) < 100:
            logger.debug("Classifier: routine (short, no specific keywords)")
            return "routine"

        # Ambiguous: ask Haiku for a granular decision
        if self._claude is not None:
            try:
                result = await self._claude.complete(
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Classify this message into ONE category:\n"
                                f"ROUTINE: casual chat, greetings, short questions.\n"
                                f"SUMMARIZATION: asking to summarize text, emails, or documents.\n"
                                f"REASONING: complex planning, multi-step tasks, deep analysis.\n"
                                f"SAFETY: requesting system changes, file writes, or sensitive actions.\n"
                                f"CODING: writing or fixing code, scripts, or technical tasks.\n"
                                f"PERSONA: roleplay or specific character interaction.\n\n"
                                f"Reply with ONLY the category name.\n\n"
                                f'Message: """{stripped[:800]}"""'
                            ),
                        }
                    ],
                    model=None,  # uses settings.model_simple (Haiku)
                    system="You are an intent classifier. Reply only with the category name.",
                    max_tokens=10,
                )
                classification = result.strip().upper()
                if "SUMMARIZATION" in classification:
                    return "summarization"
                if "REASONING" in classification:
                    return "reasoning"
                if "SAFETY" in classification:
                    return "safety"
                if "CODING" in classification:
                    return "coding"
                if "PERSONA" in classification:
                    return "persona"

                return "routine"
            except Exception as e:
                logger.warning("Classifier granular call failed: %s", e)

        # Default to reasoning when uncertain (safe bet for capable models)
        return "reasoning"
