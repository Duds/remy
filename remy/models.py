"""
Pydantic v2 data models for remy.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_used: Optional[str] = None


class SessionContext(BaseModel):
    user_id: int
    session_key: str
    turns: list[ConversationTurn] = Field(default_factory=list)


class Fact(BaseModel):
    category: str  # name, age, location, occupation, preference, relationship, health, project
    content: str
    confidence: float = 1.0


class Goal(BaseModel):
    title: str
    description: Optional[str] = None
    status: Literal["active", "completed", "abandoned"] = "active"


class TelegramUser(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
