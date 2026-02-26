"""
Message complexity classifier.
Decides whether to route to a simple/cheap model or a complex/capable one.

Fast-path heuristics run first (no network).
Ambiguous messages fall back to a single Haiku call for 2-token classification.
"""

import logging
import re
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

ClassificationResult = Literal["simple", "complex"]


class MessageClassifier:
    """Classify messages as 'simple' (cheap model) or 'complex' (powerful model)."""

    def __init__(self, claude_client=None) -> None:
        # claude_client injected to avoid circular imports; used only for ambiguous cases
        self._claude = claude_client

    async def classify(self, text: str) -> ClassificationResult:
        """Return 'simple' or 'complex' for the given message text."""
        stripped = text.strip()

        # Fast-path: obvious simple cases
        if len(stripped) < 80 and _SIMPLE_PATTERNS.match(stripped):
            logger.debug("Classifier: simple (greeting fast-path)")
            return "simple"

        # Fast-path: obvious complex cases
        if _COMPLEX_PATTERNS.search(stripped):
            logger.debug("Classifier: complex (keyword match)")
            return "complex"

        # Fast-path: short messages with no complexity signals
        if len(stripped) < 100:
            logger.debug("Classifier: simple (short, no complex keywords)")
            return "simple"

        # Ambiguous: ask Haiku for a 2-token decision
        if self._claude is not None:
            try:
                result = await self._claude.complete(
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Classify this message as SIMPLE or COMPLEX.\n"
                                f"SIMPLE: casual chat, greetings, short questions.\n"
                                f"COMPLEX: coding, file creation, multi-step tasks, analysis.\n"
                                f"Reply with ONLY the word SIMPLE or COMPLEX.\n\n"
                                f'Message: """{stripped[:400]}"""'
                            ),
                        }
                    ],
                    model=None,  # uses settings.model_simple (Haiku)
                    system="You are a message classifier. Reply only with SIMPLE or COMPLEX.",
                    max_tokens=5,
                )
                classification = result.strip().upper()
                if "COMPLEX" in classification:
                    logger.debug("Classifier: complex (haiku decision)")
                    return "complex"
                logger.debug("Classifier: simple (haiku decision)")
                return "simple"
            except Exception as e:
                logger.warning("Classifier haiku call failed: %s", e)

        # Default to complex when uncertain (better to over-use capable model)
        return "complex"
