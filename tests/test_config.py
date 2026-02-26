"""Tests for drbot/config.py — construct Settings directly, bypassing module singleton."""

import pytest
from drbot.config import Settings


def make_settings(monkeypatch, **overrides):
    """Apply env overrides then construct a fresh Settings instance."""
    for k, v in overrides.items():
        monkeypatch.setenv(k.upper(), str(v))
    return Settings()


def test_allowed_users_parsed_from_comma_string(monkeypatch):
    s = make_settings(monkeypatch, TELEGRAM_ALLOWED_USERS_RAW="111,222, 333")
    assert s.telegram_allowed_users == [111, 222, 333]


def test_allowed_users_single_value(monkeypatch):
    s = make_settings(monkeypatch, TELEGRAM_ALLOWED_USERS_RAW="12345")
    assert s.telegram_allowed_users == [12345]


def test_allowed_users_empty_allows_all(monkeypatch):
    s = make_settings(monkeypatch, TELEGRAM_ALLOWED_USERS_RAW="")
    assert s.telegram_allowed_users == []


def test_local_data_dir(monkeypatch):
    # Explicitly set DATA_DIR to test default logic
    s = make_settings(monkeypatch, AZURE_ENVIRONMENT="false", DATA_DIR="./data")
    assert s.data_dir == "./data"
    assert "drbot.db" in s.db_path
    assert "sessions" in s.sessions_dir


def test_azure_data_dir(monkeypatch):
    # When AZURE_ENVIRONMENT=true and no explicit DATA_DIR, should become /data
    monkeypatch.delenv("DATA_DIR", raising=False)
    s = make_settings(monkeypatch, AZURE_ENVIRONMENT="true")
    assert s.data_dir == "/data"
    assert s.db_path == "/data/drbot.db"


def test_soul_md_fallback(monkeypatch, tmp_path):
    s = make_settings(monkeypatch, SOUL_MD_PATH=str(tmp_path / "nonexistent.md"))
    soul = s.soul_md
    assert "drbot" in soul.lower() or "assistant" in soul.lower()


def test_soul_md_loads_file(monkeypatch, tmp_path):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("You are the test bot.")
    s = make_settings(monkeypatch, SOUL_MD_PATH=str(soul_file))
    assert s.soul_md == "You are the test bot."


def test_derived_paths_use_data_dir(monkeypatch):
    s = make_settings(monkeypatch, AZURE_ENVIRONMENT="false")
    assert s.sessions_dir.startswith(s.data_dir)
    assert s.logs_dir.startswith(s.data_dir)
    assert s.db_path.startswith(s.data_dir)
