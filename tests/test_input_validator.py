import os
from pathlib import Path
import pytest

from drbot.ai.input_validator import (
    sanitize_file_path,
    validate_message_input,
    RateLimiter,
)


def test_validate_message_short():
    valid, reason = validate_message_input("hello")
    assert valid
    assert reason is None


def test_validate_message_empty():
    valid, reason = validate_message_input("")
    assert not valid
    assert "Empty message" in reason


def test_rate_limiter_limits():
    rl = RateLimiter(max_messages_per_minute=2)
    u = 123
    allowed, _ = rl.is_allowed(u)
    assert allowed
    allowed, _ = rl.is_allowed(u)
    assert allowed
    allowed, reason = rl.is_allowed(u)
    assert not allowed
    assert "per minute" in reason


def test_sanitize_file_path_allowed(tmp_path):
    base = tmp_path / "Projects"
    base.mkdir()
    allowed = [str(base)]
    f = base / "test.txt"
    f.write_text("hi")

    path, err = sanitize_file_path(str(f), allowed)
    assert err is None
    assert os.path.samefile(path, f)


def test_sanitize_file_path_denied(tmp_path):
    allowed = [str(tmp_path / "Projects")]
    # try parent directory traversal
    path, err = sanitize_file_path("/etc/passwd", allowed)
    assert err is not None
    assert path is None
