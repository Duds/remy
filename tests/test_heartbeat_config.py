"""Tests for heartbeat config loader (SAD v7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from remy.scheduler.heartbeat_config import HEARTBEAT_OK_RESPONSE, load_heartbeat_config


def test_heartbeat_ok_constant():
    assert HEARTBEAT_OK_RESPONSE == "HEARTBEAT_OK"


def test_load_heartbeat_config_when_public_missing(monkeypatch):
    """When HEARTBEAT.md does not exist, returns minimal context string."""
    monkeypatch.setattr(
        "remy.scheduler.heartbeat_config.settings",
        type("S", (), {"heartbeat_md_path": "/nonexistent/HEARTBEAT.md"})(),
    )
    result = load_heartbeat_config()
    assert "HEARTBEAT_OK" in result
    assert len(result) > 0


def test_load_heartbeat_config_public_only(tmp_path, monkeypatch):
    """When only public file exists, returns its content."""
    public = tmp_path / "HEARTBEAT.md"
    public.write_text("# Public\n\nGoals: check overdue.")
    monkeypatch.setattr(
        "remy.scheduler.heartbeat_config.settings",
        type("S", (), {"heartbeat_md_path": str(public)})(),
    )
    result = load_heartbeat_config()
    assert "Public" in result
    assert "Goals: check overdue." in result
    assert "Local overrides" not in result


def test_load_heartbeat_config_merges_local(tmp_path, monkeypatch):
    """When public and .local exist, returns merged content."""
    public = tmp_path / "HEARTBEAT.md"
    local = tmp_path / "HEARTBEAT.local.md"
    public.write_text("# Public\n\nGoals.")
    local.write_text("# Local\n\nStale days: 5.")
    monkeypatch.setattr(
        "remy.scheduler.heartbeat_config.settings",
        type("S", (), {"heartbeat_md_path": str(public)})(),
    )
    result = load_heartbeat_config()
    assert "Public" in result
    assert "Goals." in result
    assert "Local overrides" in result
    assert "Local" in result
    assert "Stale days: 5." in result
