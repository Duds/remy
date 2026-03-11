"""Tool context — single injection point for ToolRegistry dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class ToolContext:
    """All dependencies for tool executors. Single injection point for ToolRegistry."""

    logs_dir: str
    knowledge_store: Any = None
    knowledge_extractor: Any = None
    board_orchestrator: Any = None
    claude_client: Any = None
    mistral_client: Any = None
    moonshot_client: Any = None
    ollama_base_url: str = "http://localhost:11434"
    model_complex: str = "claude-sonnet-4-6"
    calendar_client: Any = None
    gmail_client: Any = None
    contacts_client: Any = None
    docs_client: Any = None
    automation_store: Any = None
    scheduler_ref: dict | None = None
    conversation_analyzer: Any = None
    job_store: Any = None
    plan_store: Any = None
    file_indexer: Any = None
    fact_store: Any = None
    goal_store: Any = None
    counter_store: Any = None
