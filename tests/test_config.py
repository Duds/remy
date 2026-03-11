"""Tests for remy/config.py — construct Settings directly, bypassing module singleton."""

from unittest.mock import MagicMock, patch

from remy.config import Settings, save_primary_chat_id


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
    assert "remy.db" in s.db_path
    assert "sessions" in s.sessions_dir


def test_azure_data_dir(monkeypatch):
    # When AZURE_ENVIRONMENT=true and no explicit DATA_DIR, should become /data
    monkeypatch.delenv("DATA_DIR", raising=False)
    s = make_settings(monkeypatch, AZURE_ENVIRONMENT="true")
    assert s.data_dir == "/data"
    assert s.db_path == "/data/remy.db"


def test_soul_md_fallback(monkeypatch, tmp_path):
    s = make_settings(
        monkeypatch,
        SOUL_MD_PATH=str(tmp_path / "nonexistent.md"),
        SOUL_PREFER_COMPACT="false",
    )
    soul = s.soul_md
    assert "remy" in soul.lower() or "assistant" in soul.lower()


def test_soul_md_loads_file(monkeypatch, tmp_path):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("You are the test bot.")
    s = make_settings(
        monkeypatch,
        SOUL_MD_PATH=str(soul_file),
        SOUL_PREFER_COMPACT="false",
    )
    assert s.soul_md == "You are the test bot."


def test_derived_paths_use_data_dir(monkeypatch):
    s = make_settings(monkeypatch, AZURE_ENVIRONMENT="false")
    assert s.sessions_dir.startswith(s.data_dir)
    assert s.logs_dir.startswith(s.data_dir)
    assert s.db_path.startswith(s.data_dir)


def test_gdrive_mount_paths_empty(monkeypatch):
    """GDRIVE_MOUNT_PATHS empty or unset -> gdrive_mount_paths is []."""
    monkeypatch.delenv("GDRIVE_MOUNT_PATHS", raising=False)
    s = make_settings(monkeypatch, GDRIVE_MOUNT_PATHS="")
    assert s.gdrive_mount_paths == []


def test_gdrive_mount_paths_valid_path(monkeypatch, tmp_path):
    """GDRIVE_MOUNT_PATHS set to an existing dir -> included in gdrive_mount_paths."""
    s = make_settings(monkeypatch, GDRIVE_MOUNT_PATHS=str(tmp_path))
    assert s.gdrive_mount_paths == [str(tmp_path)]


def test_gdrive_mount_paths_missing_path(monkeypatch):
    """GDRIVE_MOUNT_PATHS set to nonexistent path -> graceful degradation, []."""
    s = make_settings(
        monkeypatch,
        GDRIVE_MOUNT_PATHS="/nonexistent/drive/mount/path",
    )
    assert s.gdrive_mount_paths == []


def test_save_primary_chat_id_writes_file(tmp_path):
    """Refactor primary chat helper: save_primary_chat_id writes chat_id to primary_chat_file."""
    mock_settings = MagicMock()
    mock_settings.primary_chat_file = str(tmp_path / "primary_chat_id.txt")
    with patch("remy.config.get_settings", return_value=mock_settings):
        save_primary_chat_id(999888)
    assert (tmp_path / "primary_chat_id.txt").read_text().strip() == "999888"


def test_sdk_agent_config_defaults(monkeypatch):
    """US-claude-agent-sdk-migration: model_board_analyst, model_deep_researcher, use_sdk_agent exist and default."""
    s = make_settings(monkeypatch)
    assert hasattr(s, "model_board_analyst")
    assert hasattr(s, "model_deep_researcher")
    assert hasattr(s, "use_sdk_agent")
    assert s.model_board_analyst == ""
    assert s.model_deep_researcher == ""
    assert s.use_sdk_agent is True
