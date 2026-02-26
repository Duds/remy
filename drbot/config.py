"""
Central configuration for drbot.
Uses Pydantic BaseSettings for type-safe configuration from environment variables.
"""

import os
from functools import cached_property
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (drbot/config.py → project root)
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

    # Google Workspace (Phase 3) — OAuth client credentials from Google Cloud Console.
    # Run scripts/setup_google_auth.py once to generate data/google_token.json.
    google_client_id: str = ""
    google_client_secret: str = ""

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

    @model_validator(mode="after")
    def configure_data_dir(self) -> "Settings":
        if self.azure_environment and self.data_dir == "./data":
            self.data_dir = "/data"
        return self

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "drbot.db")

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
        """Load and cache SOUL.md content."""
        try:
            with open(self.soul_md_path, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "You are drbot, a personal AI assistant. Be helpful, concise, and honest."


def get_settings() -> "Settings":
    """Return the application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


_settings: Settings | None = None


class _SettingsProxy:
    """Lazy proxy so `from drbot.config import settings` works without eager init."""
    def __getattr__(self, name):
        return getattr(get_settings(), name)


settings = _SettingsProxy()  # type: ignore[assignment]
