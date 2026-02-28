"""
Emotional tone detection for affectionate language selection.

Implements:
- Option A: Stateful tone tracking within sessions
- Option C: Memory-aware tone inference using health/stress context

The detected tone is stored on ConversationTurn and persists within a session,
allowing Remy to maintain emotional continuity rather than flip-flopping.
"""

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..models import EmotionalTone

if TYPE_CHECKING:
    from ..memory.embeddings import EmbeddingStore
    from ..memory.knowledge import KnowledgeStore
    from .claude_client import ClaudeClient

logger = logging.getLogger(__name__)

# Time-of-day thresholds (24-hour format, local time)
LATE_NIGHT_START = 23  # 11pm
LATE_NIGHT_END = 5     # 5am

# Patterns for explicit emotional cues
_STRESSED_PATTERNS = re.compile(
    r"\b(stress|stressed|anxious|anxiety|overwhelm|panic|worried|worry|"
    r"freaking out|losing it|can't cope|too much|drowning)\b",
    re.IGNORECASE
)
_CELEBRATORY_PATTERNS = re.compile(
    r"\b(got the|won|passed|promoted|accepted|achieved|nailed|smashed|"
    r"finally done|finished|completed|succeeded|made it|yes!|woohoo|"
    r"amazing news|great news|good news)\b",
    re.IGNORECASE
)
_FRUSTRATED_PATTERNS = re.compile(
    r"\b(frustrated|annoyed|annoying|irritated|ugh|argh|ffs|bloody hell|"
    r"sick of|fed up|had enough|this is ridiculous|what the hell|"
    r"why won't|doesn't work|broken|keeps failing)\b",
    re.IGNORECASE
)
_VULNERABLE_PATTERNS = re.compile(
    r"\b(sad|upset|hurt|lonely|scared|afraid|depressed|down|low|"
    r"rough day|bad day|hard day|struggling|not okay|not coping|"
    r"miss them|miss her|miss him|crying|cried)\b",
    re.IGNORECASE
)
_PLAYFUL_PATTERNS = re.compile(
    r"\b(haha|lol|lmao|😂|🤣|cheeky|banter|joking|kidding|"
    r"just messing|wink|flirt|tease)\b",
    re.IGNORECASE
)
_TIRED_PATTERNS = re.compile(
    r"\b(tired|exhausted|knackered|wiped|drained|sleepy|"
    r"need sleep|can't sleep|insomnia|up late|still awake|"
    r"been at it|long day|14 hours|12 hours)\b",
    re.IGNORECASE
)


class ToneDetector:
    """
    Detects emotional tone from messages and memory context.
    
    Uses a combination of:
    1. Explicit emotional language in the message
    2. Time-of-day signals (late night = likely tired)
    3. Punctuation/style analysis (ALL CAPS, exclamation marks)
    4. Memory context (ongoing health issues, recent stressors, deadlines)
    """

    def __init__(
        self,
        knowledge_store: "KnowledgeStore | None" = None,
        embeddings: "EmbeddingStore | None" = None,
        claude_client: "ClaudeClient | None" = None,
    ) -> None:
        self._knowledge = knowledge_store
        self._embeddings = embeddings
        self._claude = claude_client
        self._session_tones: dict[int, EmotionalTone] = {}

    def get_session_tone(self, user_id: int) -> EmotionalTone | None:
        """Get the current emotional tone for a user's session."""
        return self._session_tones.get(user_id)

    def set_session_tone(self, user_id: int, tone: EmotionalTone) -> None:
        """Set the emotional tone for a user's session."""
        self._session_tones[user_id] = tone

    def clear_session_tone(self, user_id: int) -> None:
        """Clear the emotional tone when a session ends or resets."""
        self._session_tones.pop(user_id, None)

    async def detect_tone(
        self,
        user_id: int,
        message: str,
        local_hour: int | None = None,
        use_memory_context: bool = True,
    ) -> EmotionalTone:
        """
        Detect emotional tone from message content and context.
        
        Args:
            user_id: User ID for memory lookup
            message: The user's message text
            local_hour: Hour in user's local timezone (0-23). If None, uses UTC.
            use_memory_context: Whether to check memory for health/stress context
            
        Returns:
            Detected EmotionalTone
        """
        # 1. Check explicit emotional language (highest priority)
        explicit_tone = self._detect_explicit_tone(message)
        if explicit_tone:
            self.set_session_tone(user_id, explicit_tone)
            return explicit_tone

        # 2. Check time-of-day signals
        if local_hour is not None:
            if local_hour >= LATE_NIGHT_START or local_hour < LATE_NIGHT_END:
                # Late night — likely tired, but check message length
                # Short messages at night = probably just tired
                # Long messages at night = might be stressed/working
                if len(message) < 50:
                    self.set_session_tone(user_id, EmotionalTone.TIRED)
                    return EmotionalTone.TIRED

        # 3. Check punctuation/style signals
        style_tone = self._detect_style_tone(message)
        if style_tone:
            self.set_session_tone(user_id, style_tone)
            return style_tone

        # 4. Check memory context for ongoing stressors (Option C)
        if use_memory_context and self._knowledge and self._embeddings:
            memory_tone = await self._detect_from_memory_context(user_id, message)
            if memory_tone:
                self.set_session_tone(user_id, memory_tone)
                return memory_tone

        # 5. Fall back to session tone if we have one (Option A continuity)
        existing_tone = self.get_session_tone(user_id)
        if existing_tone and existing_tone != EmotionalTone.NEUTRAL:
            # Decay strong emotions after a few neutral messages
            # For now, just maintain the tone
            return existing_tone

        # 6. Default to neutral
        return EmotionalTone.NEUTRAL

    def _detect_explicit_tone(self, message: str) -> EmotionalTone | None:
        """Detect tone from explicit emotional language."""
        # Order matters — check more specific/intense emotions first
        if _CELEBRATORY_PATTERNS.search(message):
            return EmotionalTone.CELEBRATORY
        if _VULNERABLE_PATTERNS.search(message):
            return EmotionalTone.VULNERABLE
        if _STRESSED_PATTERNS.search(message):
            return EmotionalTone.STRESSED
        if _FRUSTRATED_PATTERNS.search(message):
            return EmotionalTone.FRUSTRATED
        if _TIRED_PATTERNS.search(message):
            return EmotionalTone.TIRED
        if _PLAYFUL_PATTERNS.search(message):
            return EmotionalTone.PLAYFUL
        return None

    def _detect_style_tone(self, message: str) -> EmotionalTone | None:
        """Detect tone from punctuation and style."""
        # ALL CAPS (more than 3 words) = excited or frustrated
        words = message.split()
        caps_words = [w for w in words if w.isupper() and len(w) > 1]
        if len(caps_words) >= 3:
            # Check if it's positive or negative caps
            if any(w in message.upper() for w in ["YES", "WON", "DID IT", "FINALLY"]):
                return EmotionalTone.CELEBRATORY
            return EmotionalTone.FRUSTRATED

        # Multiple exclamation marks = excited
        if message.count("!") >= 3:
            return EmotionalTone.CELEBRATORY

        # Ellipses = hesitant/vulnerable
        if message.count("...") >= 2:
            return EmotionalTone.VULNERABLE

        return None

    async def _detect_from_memory_context(
        self, user_id: int, message: str
    ) -> EmotionalTone | None:
        """
        Check memory for context that might indicate emotional state.
        
        Looks for:
        - Recent health issues
        - Ongoing stressors
        - Upcoming deadlines
        """
        if not self._knowledge:
            return None

        try:
            # Get all facts to filter by category
            facts = await self._knowledge.get_by_type(
                user_id, "fact", limit=100, min_confidence=0.5
            )

            # Check for health/medical issues
            health_facts = [
                f for f in facts
                if f.metadata.get("category") in ("health", "medical")
            ]

            # Check for deadline pressure
            deadline_facts = [
                f for f in facts
                if f.metadata.get("category") == "deadline"
            ]

            # If there are active health issues and message mentions related topics
            if health_facts:
                health_keywords = ["doctor", "hospital", "appointment", "pain", 
                                   "medication", "treatment", "recovery", "physio"]
                if any(kw in message.lower() for kw in health_keywords):
                    return EmotionalTone.VULNERABLE

            # If there are looming deadlines and message mentions work/tasks
            if deadline_facts:
                deadline_keywords = ["deadline", "due", "finish", "submit", 
                                     "complete", "done", "time", "late"]
                if any(kw in message.lower() for kw in deadline_keywords):
                    return EmotionalTone.STRESSED

            # Semantic search for stress indicators in recent context
            if self._embeddings:
                stress_results = await self._embeddings.search_similar_for_type(
                    user_id,
                    query="stressed worried overwhelmed anxious",
                    source_type="knowledge_fact",
                    limit=3,
                    recency_boost=True,
                )
                if stress_results:
                    # Check if any results are highly relevant (low distance)
                    for result in stress_results:
                        if result.get("distance", 1.0) < 0.3:
                            return EmotionalTone.STRESSED

        except Exception as e:
            logger.debug("Memory context check failed: %s", e)

        return None


async def get_emotional_context_summary(
    user_id: int,
    knowledge_store: "KnowledgeStore",
    embeddings: "EmbeddingStore | None" = None,
) -> dict:
    """
    Retrieve memory context relevant to emotional tone inference.
    
    Returns a dict with:
    - health_issues: List of health/medical facts
    - potential_stressors: Semantically similar stress-related facts
    - upcoming_deadlines: Deadline facts
    - recent_facts_count: Number of facts in last 7 days
    """
    result = {
        "health_issues": [],
        "potential_stressors": [],
        "upcoming_deadlines": [],
        "recent_facts_count": 0,
    }

    try:
        # Get all facts
        facts = await knowledge_store.get_by_type(
            user_id, "fact", limit=100, min_confidence=0.5
        )

        # Filter by category
        result["health_issues"] = [
            {"content": f.content, "category": f.metadata.get("category")}
            for f in facts
            if f.metadata.get("category") in ("health", "medical")
        ]

        result["upcoming_deadlines"] = [
            {"content": f.content}
            for f in facts
            if f.metadata.get("category") == "deadline"
        ]

        # Get memory summary for recent count
        summary = await knowledge_store.get_memory_summary(user_id)
        result["recent_facts_count"] = summary.get("recent_facts_7d", 0)

        # Semantic search for stressors
        if embeddings:
            stress_results = await embeddings.search_similar_for_type(
                user_id,
                query="stress anxiety worry concern problem difficulty",
                source_type="knowledge_fact",
                limit=5,
                recency_boost=True,
            )
            result["potential_stressors"] = [
                {"content": r.get("content", ""), "distance": r.get("distance", 1.0)}
                for r in stress_results
                if r.get("distance", 1.0) < 0.5
            ]

    except Exception as e:
        logger.debug("Failed to get emotional context summary: %s", e)

    return result
