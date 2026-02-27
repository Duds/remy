"""Shared fixtures for remy tests."""

import os
import tempfile

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporary data directory for tests."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Prevent tests from reading real .env or touching real data."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS_RAW", "12345")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_ENVIRONMENT", "false")
