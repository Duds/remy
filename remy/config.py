"""
Central configuration for remy.
Uses Pydantic BaseSettings for type-safe configuration from environment variables.
"""

import os
from functools import cached_property
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (remy/config.py → project root)
_ENV_FILE = Path(__file__).parent.parent / ".env"


def _load_env_file() -> None:
    """
    Load .env into os.environ, but only for keys that are currently unset
    or set to empty strings. This ensures .env values win over blank shell
    env vars (e.g. ANTHROPIC_API_KEY='') while still allowing explicit
    non-empty shell overrides.
    """
    if not _ENV_FILE.exists():
        return
    from dotenv import dotenv_values
    for key, value in dotenv_values(_ENV_FILE).items():
        if value and not os.environ.get(key):
            os.environ[key] = value


# Run at import time so Settings() sees the correct values
_load_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    # Stored as a raw comma-string; exposed as a list via property
    telegram_allowed_users_raw: str = ""

    # Anthropic
    anthropic_api_key: str
    model_simple: str = "claude-haiku-4-5-20251001"
    model_complex: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 4096

    # Mistral AI
    mistral_api_key: str = ""
    mistral_model_medium: str = "mistral-medium-latest"
    mistral_model_large: str = "mistral-large-latest"

    # Moonshot AI
    moonshot_api_key: str = ""
    moonshot_model_v1: str = "moonshot-v1-8k"
    moonshot_model_v1_128k: str = "moonshot-v1-128k"
    moonshot_model_k2_thinking: str = "moonshot-k2-thinking"

    # Ollama fallback
    ollama_base_url: str = "http://localhost:11434"
    ollama_fallback_model: str = "llama3:latest"
    ollama_timeout: float = 120.0

    # Environment
    azure_environment: bool = False
    data_dir: str = "./data"

    # Logging
    log_level: str = "INFO"

    # Scheduler (cron in user's local timezone)
    briefing_cron: str = "0 7 * * *"
    checkin_cron: str = "0 19 * * *"
    scheduler_timezone: str = "Australia/Sydney"

    # SOUL.md path
    soul_md_path: str = "config/SOUL.md"
    soul_compact_path: str = "config/SOUL.compact.md"
    soul_prefer_compact: bool = True  # Prefer compact version if it exists

    # Memory system (US-improved-persistent-memory)
    fact_merge_threshold: float = 0.15  # ANN cosine distance below which facts are merged

    # Token budget controls (cost and latency safeguards)
    max_input_tokens_per_request: int = 50_000  # Hard ceiling for input context
    max_output_tokens_per_request: int = 4_096  # Hard ceiling for response
    max_tokens_per_user_per_hour: int = 500_000  # Rate limit per user
    max_cost_per_user_per_day_usd: float = 10.0  # Daily spend cap per user

    # Home directory RAG index (US-home-directory-rag)
    rag_index_enabled: bool = True
    rag_index_paths: str = ""  # Comma-separated paths; empty = ~/Projects,~/Documents
    rag_index_extensions: str = ""  # Comma-separated; empty = default set
    rag_reindex_cron: str = "0 3 * * *"  # Nightly at 03:00

    # Google Workspace (Phase 3) — OAuth client credentials from Google Cloud Console.
    # Run scripts/setup_google_auth.py once to generate data/google_token.json.
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── Timeouts (seconds) ──────────────────────────────────────────────────────
    telegram_timeout: float = 30.0
    mistral_timeout: float = 60.0
    moonshot_timeout: float = 120.0
    diagnostic_timeout: float = 10.0

    # ── Rate limiting ───────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 10
    max_concurrent_per_user: int = 2
    max_message_length: int = 10_000
    max_command_length: int = 500

    # ── Circuit breaker ─────────────────────────────────────────────────────────
    cb_failure_threshold: int = 5
    cb_recovery_timeout: float = 60.0

    # ── Intervals (seconds) ─────────────────────────────────────────────────────
    health_check_interval: int = 300
    stale_goal_days: int = 3

    # ── Claude client ───────────────────────────────────────────────────────────
    claude_max_retries: int = 3
    claude_retry_base_delay: float = 2.0
    claude_max_tool_iterations: int = 5
    claude_min_cache_tokens: int = 1024

    # ── Compaction ──────────────────────────────────────────────────────────────
    compaction_token_threshold: int = 50_000
    compaction_keep_recent_messages: int = 20

    # ── File indexing ───────────────────────────────────────────────────────────
    file_index_chunk_chars: int = 1500
    file_index_overlap_chars: int = 200
    file_index_max_file_size: int = 512_000

    # ── Classifier cache ────────────────────────────────────────────────────────
    classifier_cache_ttl: int = 300
    classifier_cache_max: int = 256

    # ── Allowed directories (shared constant) ───────────────────────────────────
    # Comma-separated list of base directories for file operations
    allowed_base_dirs_raw: str = "~/Projects,~/Documents,~/Downloads"

    @property
    def google_token_file(self) -> str:
        return os.path.join(self.data_dir, "google_token.json")

    @property
    def grocery_list_file(self) -> str:
        return os.path.join(self.data_dir, "grocery_list.txt")

    @property
    def telegram_allowed_users(self) -> list[int]:
        """Parse comma-separated user IDs from the raw env string."""
        raw = self.telegram_allowed_users_raw
        if not raw:
            return []
        return [int(x.strip()) for x in raw.split(",") if x.strip()]

    @property
    def allowed_base_dirs(self) -> list[str]:
        """Parse and expand allowed base directories."""
        raw = self.allowed_base_dirs_raw
        if not raw:
            return []
        return [str(Path(d.strip()).expanduser()) for d in raw.split(",") if d.strip()]

    @model_validator(mode="after")
    def configure_data_dir(self) -> "Settings":
        if self.azure_environment and self.data_dir == "./data":
            self.data_dir = "/data"
        return self

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "remy.db")

    @property
    def sessions_dir(self) -> str:
        return os.path.join(self.data_dir, "sessions")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.data_dir, "logs")

    @property
    def primary_chat_file(self) -> str:
        return os.path.join(self.data_dir, "primary_chat_id.txt")

    @cached_property
    def soul_md(self) -> str:
        """
        Load and cache SOUL content.

        Prefers SOUL.compact.md if soul_prefer_compact is True and the file exists.
        Falls back to SOUL.md, then to a minimal default prompt.
        """
        import logging
        logger = logging.getLogger(__name__)

        # Try compact version first if preferred
        if self.soul_prefer_compact:
            try:
                with open(self.soul_compact_path, encoding="utf-8") as f:
                    content = f.read().strip()
                    logger.debug("Loaded compact soul from %s", self.soul_compact_path)
                    return content
            except FileNotFoundError:
                pass

        # Fall back to full SOUL.md
        try:
            with open(self.soul_md_path, encoding="utf-8") as f:
                content = f.read().strip()
                logger.debug("Loaded soul from %s", self.soul_md_path)
                return content
        except FileNotFoundError:
            logger.warning("No SOUL.md found, using default prompt")
            return "You are Remy, a personal AI assistant. Be helpful, concise, and honest."


def get_settings() -> "Settings":
    """Return the application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


_settings: Settings | None = None


class _SettingsProxy:
    """Lazy proxy so `from remy.config import settings` works without eager init."""
    def __getattr__(self, name):
        return getattr(get_settings(), name)


settings = _SettingsProxy()  # type: ignore[assignment]
